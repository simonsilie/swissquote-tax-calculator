#!/usr/bin/env python3
import sys
from argparse import Namespace
from pathlib import Path

import configargparse
from loguru import logger

from taxes.elster_export import export_elster_mapping
from taxes.fx_rates import CACHE_FILE, DailyFXRateFetcher
from taxes.reporting import (
    export_details,
    format_amount,
    print_section,
    print_stock_sale_tax_note,
)
from taxes.service import (
    DEFAULT_COLUMNS,
    DEFAULT_DIVIDEND_TYPES,
    DEFAULT_INTEREST_TYPES,
    DEFAULT_PURCHASE_TYPES,
    DEFAULT_SALE_TYPES,
    DEFAULT_WITHHOLDING_TAX_TYPES,
    TaxCalculationResult,
    calculate_taxes,
)


def parse_args() -> Namespace:
    """Parse CLI arguments for the Swissquote tax evaluation tool."""
    parser = configargparse.ArgParser(
        auto_env_var_prefix="SWISSQUOTE_TAX_",
        description="Steuerauswertung für Swissquote-Transaktionen",
        formatter_class=configargparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        is_config_file=True,
        help="Pfad zu einer Config-Datei; CLI-Argumente überschreiben deren Werte",
    )
    parser.add_argument("csv_file", type=Path, nargs="?", help="Pfad zur CSV-Datei (Swissquote Export)")
    parser.add_argument("--encoding", default="latin1", help="CSV-Encoding")
    parser.add_argument("--sep", default=";", help="CSV-Trennzeichen")
    parser.add_argument("--tax-year", type=int, help="Steuerjahr bei CSV-Dateien mit Transaktionshistorie")
    parser.add_argument(
        "--dividend-types",
        nargs="+",
        default=DEFAULT_DIVIDEND_TYPES,
        help="Transaktionstypen für Dividenden",
    )
    parser.add_argument(
        "--interest-types",
        nargs="+",
        default=DEFAULT_INTEREST_TYPES,
        help="Transaktionstypen für Zinsen",
    )
    parser.add_argument(
        "--withholding-tax-types",
        nargs="+",
        default=DEFAULT_WITHHOLDING_TAX_TYPES,
        help="Transaktionstypen für separate Quellensteuer-Buchungen",
    )
    parser.add_argument(
        "--purchase-types",
        nargs="+",
        default=DEFAULT_PURCHASE_TYPES,
        help="Transaktionstypen für Wertpapierkäufe",
    )
    parser.add_argument(
        "--sale-types",
        nargs="+",
        default=DEFAULT_SALE_TYPES,
        help="Transaktionstypen für Wertpapierverkäufe",
    )
    parser.add_argument("--col-date", default=DEFAULT_COLUMNS["date"], help="Datum-Spalte")
    parser.add_argument("--col-name", default=DEFAULT_COLUMNS["name"], help="Name-Spalte")
    parser.add_argument(
        "--col-type",
        default=DEFAULT_COLUMNS["transaction_type"],
        help="Transaktionstyp-Spalte",
    )
    parser.add_argument("--col-currency", default=DEFAULT_COLUMNS["currency"], help="Währung-Spalte")
    parser.add_argument("--col-amount", default=DEFAULT_COLUMNS["net_amount"], help="Nettobetrag-Spalte")
    parser.add_argument(
        "--col-withholding-tax",
        default=DEFAULT_COLUMNS["withholding_tax"],
        help="Spalte mit einbehaltener Quellensteuer (optional)",
    )
    parser.add_argument(
        "--col-withholding-tax-eur",
        default=DEFAULT_COLUMNS["withholding_tax_eur"],
        help="EUR-Spalte fuer Quellensteuer (Output)",
    )
    parser.add_argument("--col-isin", default=DEFAULT_COLUMNS["isin"], help="ISIN-Spalte")
    parser.add_argument("--col-quantity", default=DEFAULT_COLUMNS["quantity"], help="Anzahl-Spalte")
    parser.add_argument(
        "--col-eur",
        default=DEFAULT_COLUMNS["net_amount_eur"],
        help="EUR-Spalte (Output)",
    )
    parser.add_argument(
        "--col-gross-eur",
        default=DEFAULT_COLUMNS["gross_amount_eur"],
        help="EUR-Spalte für die Bruttoerträge vor Quellensteuer (Output)",
    )
    parser.add_argument("--round", action="store_true", help="Ergebnisse auf ganze Euro runden")
    parser.add_argument("--no-details", action="store_true", help="Details nicht ausgeben")
    parser.add_argument("--output", help="Ergebnisse in CSV-Datei schreiben")
    parser.add_argument(
        "--export-summary",
        default=True,
        action="store_true",
        help="ELSTER-Mapping-Datei (tax_summary_elster.md) generieren (Standard: an)",
    )
    parser.add_argument(
        "--no-export-summary",
        dest="export_summary",
        action="store_false",
        help="Keine ELSTER-Mapping-Datei generieren",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=Path("."),
        help="Ausgabeverzeichnis fuer die ELSTER-Mapping-Datei (Standard: aktuelles Verzeichnis)",
    )
    parser.add_argument(
        "--withholding-tax-rules",
        type=Path,
        help="TOML-Datei zur ISIN-basierten Klassifizierung von Quellensteuern (Standard: lokale withholding-tax-rules.toml)",
    )
    parser.add_argument("--clear-cache", action="store_true", help="FX-Rates-Cache löschen und beenden")
    return parser.parse_args()


def _print_cli_output(result: TaxCalculationResult) -> None:
    rt = result
    wts = rt.withholding_tax_summary
    logger.info("1. Dividenden (Bruttoerträge vor Quellensteuer):")
    logger.info(
        "   Anlage KAP (Zeile 18 - Inländische Kapitalerträge, deutsche Aktien): "
        f"{format_amount(rt.total_domestic_share_dividends, rt.round)}"
    )
    logger.info(
        "   Anlage KAP (Zeile 19 - Ausländische Kapitalerträge, ausländische Aktien): "
        f"{format_amount(rt.total_foreign_share_dividends, rt.round)}"
    )
    logger.info(
        "   Anlage KAP-INV (Zeile 4 - Investmentfonds-/ETF-Ausschüttungen): "
        f"{format_amount(rt.total_fund_dividends, rt.round)}"
    )
    zinsen_text = f"2. Anlage KAP (Zeile 19 - Ausländische Zinsen):   {format_amount(rt.total_interest, rt.round)}"
    logger.info(zinsen_text)
    if rt.col_withholding_tax_eur in rt.df.columns or not rt.withholding_tax_transactions.is_empty():
        logger.info(
            "3. Anlage KAP (Zeile 41 - Anrechenbare ausländische Steuern): "
            f"{format_amount(wts.foreign_creditable, rt.round)}"
        )
        for country, amount in wts.foreign_creditable_by_country:
            logger.info(f"   {country}: {format_amount(amount, rt.round)}")
        logger.info(
            "   Davon Quellensteuer auf Dividenden: "
            f"{format_amount(rt.dividend_tax_summary.foreign_creditable, rt.round)}"
        )
        logger.info(
            f"   Davon Quellensteuer auf Zinsen: {format_amount(rt.interest_tax_summary.foreign_creditable, rt.round)}"
        )
        if wts.foreign_excess:
            logger.info(
                f"   Nicht anrechenbarer ausländischer Steuerüberhang: {format_amount(wts.foreign_excess, rt.round)}"
            )
        if wts.swiss_refundable:
            logger.info(
                "   Davon Schweizer Verrechnungssteuer, separat rückforderbar: "
                f"{format_amount(wts.swiss_refundable, rt.round)} "
                "(Über eF85 direkt bei der Schweizer ESTV zurückzufordern)"
            )
        logger.info("4. Anlage KAP (Steueranrechnung):")
        logger.info(f"   Zeile 37 - Kapitalertragsteuer: {format_amount(wts.domestic_capital_gains_tax, rt.round)}")
        logger.info(f"   Zeile 38 - Solidaritätszuschlag: {format_amount(wts.domestic_solidarity_surcharge, rt.round)}")
        logger.info(
            f"   Summe deutsche Kapitalertragsteuer einschließlich Soli: {format_amount(wts.domestic, rt.round)}"
        )
        if wts.unclassified:
            logger.info(
                "   Nicht in Zeile 41 (fehlende ISIN-Regel oder Bruttobetrag): "
                f"{format_amount(wts.unclassified, rt.round)}"
            )
    stock_sales_text = (
        f"5. Realisierte Gewinne/Verluste aus Aktienverkäufen: {format_amount(rt.total_stock_sales, rt.round)}"
    )
    logger.info(stock_sales_text)
    print_stock_sale_tax_note(rt.stock_sales, "Gewinn_Verlust_EUR", rt.round)


def _print_cli_details(result: TaxCalculationResult) -> None:
    rt = result
    detail_cols: list[str] = [
        rt.col_date,
        rt.col_name,
        rt.col_amount,
        rt.col_currency,
        rt.col_eur,
        rt.col_gross_eur,
        rt.col_withholding_tax,
        rt.col_withholding_tax_eur,
        "Formular",
        "Quellenstaat",
        "Steuerbehandlung",
        "Anrechenbare_Quellensteuer_EUR",
        "Nicht_anrechenbare_Quellensteuer_EUR",
        "Inlaendische_Kapitalertragsteuer_EUR",
        "Solidaritaetszuschlag_EUR",
        "Nicht_klassifizierte_Steuer_EUR",
    ]
    print_section("Details Dividenden", rt.dividends, detail_cols, rt.col_gross_eur, rt.round)
    print_section("Details Zinsen", rt.interest, detail_cols, rt.col_gross_eur, rt.round)
    print_section(
        "Details separate Quellensteuer-Buchungen",
        rt.withholding_tax_transactions,
        detail_cols,
        rt.col_eur,
        rt.round,
    )
    print_section(
        "Details Aktienverkäufe",
        rt.stock_sales,
        [
            rt.col_date,
            rt.col_isin,
            rt.col_quantity,
            "Verkaufserloes_EUR",
            "Anschaffungskosten_EUR",
            "Gewinn_Verlust_EUR",
        ],
        "Gewinn_Verlust_EUR",
        rt.round,
    )


def main() -> None:
    """Evaluate Swissquote transaction CSV for German tax declarations (Anlage KAP / KAP-INV)."""
    logger.remove()
    logger.add(sys.stdout, format="<level>{level: <8}</level> | {message}", level="INFO")
    args = parse_args()

    if args.clear_cache:
        if DailyFXRateFetcher.clear_cache():
            logger.info(f"FX-Rates-Cache gelöscht ({CACHE_FILE}).")
        else:
            logger.info(f"FX-Rates-Cache existiert nicht ({CACHE_FILE}) – nichts zu löschen.")
        return

    if args.csv_file is None:
        sys.exit("Fehler: csv_file ist erforderlich (z.B. swissquote-tax-calculator transaktionen.csv)")

    try:
        result = calculate_taxes(
            csv_file=args.csv_file,
            tax_year=args.tax_year,
            encoding=args.encoding,
            sep=args.sep,
            dividend_types=args.dividend_types,
            interest_types=args.interest_types,
            withholding_tax_types=args.withholding_tax_types,
            purchase_types=args.purchase_types,
            sale_types=args.sale_types,
            col_date=args.col_date,
            col_name=args.col_name,
            col_type=args.col_type,
            col_currency=args.col_currency,
            col_amount=args.col_amount,
            col_withholding_tax=args.col_withholding_tax,
            col_withholding_tax_eur=args.col_withholding_tax_eur,
            col_isin=args.col_isin,
            col_quantity=args.col_quantity,
            col_eur=args.col_eur,
            col_gross_eur=args.col_gross_eur,
            round_amount=args.round,
            withholding_tax_rules_path=args.withholding_tax_rules,
        )
    except ValueError as error:
        sys.exit(str(error))

    _print_cli_output(result)

    if not args.no_details:
        _print_cli_details(result)

    if args.output:
        export_details(result.dividends, result.interest, result.stock_sales, args.output, args.sep)
        logger.info(f"\nDetails nach '{args.output}' exportiert")

    if args.export_summary:
        export_elster_mapping(
            output_dir=args.export_dir,
            tax_year=result.tax_year,
            total_domestic_share_dividends=result.total_domestic_share_dividends,
            total_foreign_share_dividends=result.total_foreign_share_dividends,
            total_interest=result.total_interest,
            total_fund_dividends=result.total_fund_dividends,
            withholding_tax_summary=result.withholding_tax_summary,
            stock_gains=result.stock_gains,
            stock_losses=result.stock_losses,
            fund_dividends=result.fund_dividends,
            round_amount=result.round,
        )


if __name__ == "__main__":
    main()
