#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import polars as pl

from taxes.currency_conversion import apply_fx_rates_annual, apply_fx_rates_daily
from taxes.fx_rates import CACHE_FILE, DailyFXRateFetcher
from taxes.reporting import export_details, format_amount, print_section
from taxes.stock_sales import calculate_realized_stock_results
from taxes.transactions import detect_tax_year, load_csv, validate_data

DEFAULT_DIVIDEND_TYPES: list[str] = ["Dividende"]
DEFAULT_INTEREST_TYPES: list[str] = ["Zinsen auf Einlagen"]
DEFAULT_PURCHASE_TYPES: list[str] = ["Kauf"]
DEFAULT_SALE_TYPES: list[str] = ["Verkauf"]

DEFAULT_COLUMNS: dict[str, str] = {
    "date": "Datum",
    "name": "Name",
    "transaction_type": "Transaktionen",
    "currency": "Währung",
    "net_amount": "Nettobetrag",
    "net_amount_eur": "Nettobetrag_EUR",
    "isin": "ISIN",
    "quantity": "Anzahl",
}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the Swissquote tax evaluation tool."""
    parser = argparse.ArgumentParser(
        description="Steuerauswertung für Swissquote-Transaktionen",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("csv_file", type=Path, nargs="?", help="Pfad zur CSV-Datei (Swissquote Export)")
    parser.add_argument("--encoding", default="latin1", help="CSV-Encoding")
    parser.add_argument("--sep", default=";", help="CSV-Trennzeichen")
    parser.add_argument("--tax-year", type=int, help="Steuerjahr bei CSV-Dateien mit Transaktionshistorie")
    help_text_usd = (
        "EUR/USD Kurs (im annual-Modus: Jahresdurchschnitt, im daily-Modus: Überschreibt automatische Kurse)"
    )
    parser.add_argument(
        "--fx-usd",
        type=float,
        default=None,
        help=help_text_usd,
    )
    help_text_chf = (
        "EUR/CHF Kurs (im annual-Modus: Jahresdurchschnitt, im daily-Modus: Überschreibt automatische Kurse)"
    )
    parser.add_argument(
        "--fx-chf",
        type=float,
        default=None,
        help=help_text_chf,
    )
    parser.add_argument("--fx-eur", type=float, default=None, help="EUR/EUR Kurs (standardmäßig 1.0)")
    parser.add_argument(
        "--fx-mode",
        choices=["daily", "annual"],
        default="daily",
        help="Wechselkurs-Modus: 'daily' = Tageskurse pro Transaktionsdatum (Standard), 'annual' = Jahresdurchschnitt",
    )
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
    parser.add_argument("--col-isin", default=DEFAULT_COLUMNS["isin"], help="ISIN-Spalte")
    parser.add_argument("--col-quantity", default=DEFAULT_COLUMNS["quantity"], help="Anzahl-Spalte")
    parser.add_argument(
        "--col-eur",
        default=DEFAULT_COLUMNS["net_amount_eur"],
        help="EUR-Spalte (Output)",
    )
    parser.add_argument("--round", action="store_true", help="Ergebnisse auf ganze Euro runden")
    parser.add_argument("--no-details", action="store_true", help="Details nicht ausgeben")
    parser.add_argument("--output", help="Ergebnisse in CSV-Datei schreiben")
    parser.add_argument("--clear-cache", action="store_true", help="FX-Rates-Cache löschen und beenden")
    return parser.parse_args()


def main() -> None:
    """Evaluate Swissquote transaction CSV for German tax declarations (Anlage KAP / KAP-INV)."""
    args = parse_args()

    if args.clear_cache:
        if DailyFXRateFetcher.clear_cache():
            print(f"FX-Rates-Cache gelöscht ({CACHE_FILE}).")
        else:
            print(f"FX-Rates-Cache existiert nicht ({CACHE_FILE}) – nichts zu löschen.")
        return

    if args.csv_file is None:
        sys.exit("Fehler: csv_file ist erforderlich (z.B. steuer-auswertung transaktionen.csv)")

    df = load_csv(args.csv_file, args.encoding, args.sep, args.col_date, args.col_amount)

    required_cols: list[str] = [args.col_type, args.col_currency, args.col_amount]
    missing: list[str] = [c for c in required_cols if c not in df.columns]
    if missing:
        sys.exit(f"Fehler: Fehlende Spalten in CSV: {missing}")

    tax_year: int = detect_tax_year(df, args.col_date, args.tax_year)
    validate_data(df, args.col_amount, args.col_currency, args.col_type)

    rate_overrides: dict[str, float] = {}
    if args.fx_usd is not None:
        rate_overrides["USD"] = args.fx_usd
    if args.fx_chf is not None:
        rate_overrides["CHF"] = args.fx_chf
    if args.fx_eur is not None:
        rate_overrides["EUR"] = args.fx_eur

    fetcher = DailyFXRateFetcher(rate_overrides=rate_overrides)

    if args.fx_mode == "daily":
        print(f"=== AUSWERTUNG FÜR STEUERJAHR {tax_year} (Tageskurse) ===")
        df = apply_fx_rates_daily(df, fetcher, args.col_date, args.col_currency, args.col_amount, args.col_eur)
    else:
        if len(df[args.col_date].dt.year().unique()) > 1:
            sys.exit("Fehler: --fx-mode annual unterstützt keine mehrjährigen CSV-Dateien")
        print(f"=== AUSWERTUNG FÜR STEUERJAHR {tax_year} (Jahresdurchschnitt) ===")
        df = apply_fx_rates_annual(
            df,
            fetcher,
            tax_year,
            args.col_currency,
            args.col_amount,
            args.col_eur,
            args.fx_usd,
            args.fx_chf,
            args.fx_eur,
        )

    tax_year_df = df.filter(pl.col(args.col_date).dt.year() == tax_year)
    dividends: pl.DataFrame = tax_year_df.filter(pl.col(args.col_type).is_in(args.dividend_types))
    interest: pl.DataFrame = tax_year_df.filter(pl.col(args.col_type).is_in(args.interest_types))
    stock_sales = calculate_realized_stock_results(
        df,
        args.purchase_types,
        args.sale_types,
        args.col_date,
        args.col_type,
        args.col_isin,
        args.col_quantity,
        args.col_eur,
    ).filter(pl.col(args.col_date).dt.year() == tax_year)

    total_dividends: float = dividends[args.col_eur].sum()
    total_interest: float = interest[args.col_eur].sum()
    total_stock_sales: float = float(stock_sales["Gewinn_Verlust_EUR"].sum())

    dividend_text = f"1. Anlage KAP-INV (Zeile 4 - ETF-Ausschüttungen): {format_amount(total_dividends, args.round)}"
    print(dividend_text)
    zinsen_text = f"2. Anlage KAP (Zeile 19 - Ausländische Zinsen):   {format_amount(total_interest, args.round)}"
    print(zinsen_text)
    stock_sales_text = (
        f"3. Realisierte Gewinne/Verluste aus Aktienverkäufen: {format_amount(total_stock_sales, args.round)}"
    )
    print(stock_sales_text)

    if not args.no_details:
        detail_cols: list[str] = [
            args.col_date,
            args.col_name,
            args.col_amount,
            args.col_currency,
            args.col_eur,
        ]
        print_section("Details Dividenden", dividends, detail_cols, args.col_eur, args.round)
        print_section("Details Zinsen", interest, detail_cols, args.col_eur, args.round)
        print_section(
            "Details Aktienverkäufe",
            stock_sales,
            [
                args.col_date,
                args.col_isin,
                args.col_quantity,
                "Verkaufserloes_EUR",
                "Anschaffungskosten_EUR",
                "Gewinn_Verlust_EUR",
            ],
            "Gewinn_Verlust_EUR",
            args.round,
        )

    if args.output:
        export_details(dividends, interest, stock_sales, args.output, args.sep)
        print(f"\nDetails nach '{args.output}' exportiert")


if __name__ == "__main__":
    main()
