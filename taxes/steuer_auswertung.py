#!/usr/bin/env python3
import argparse
import sys
from typing import Optional

import polars as pl

from taxes.fx_rates import DailyFXRateFetcher, FALLBACK_FX_RATES

DEFAULT_DIVIDEND_TYPES: list[str] = ["Dividende"]
DEFAULT_INTEREST_TYPES: list[str] = ["Zinsen auf Einlagen"]

DEFAULT_COLUMNS: dict[str, str] = {
    "date": "Datum",
    "name": "Name",
    "transaction_type": "Transaktionen",
    "currency": "Währung",
    "net_amount": "Nettobetrag",
    "net_amount_eur": "Nettobetrag_EUR",
}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the Swissquote tax evaluation tool."""
    parser = argparse.ArgumentParser(
        description="Steuerauswertung für Swissquote-Transaktionen",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("csv_file", help="Pfad zur CSV-Datei (Swissquote Export)")
    parser.add_argument("--encoding", default="latin1", help="CSV-Encoding")
    parser.add_argument("--sep", default=";", help="CSV-Trennzeichen")
    help_text_usd = "EUR/USD Kurs (im annual-Modus: Jahresdurchschnitt, im daily-Modus: Überschreibt automatische Kurse)"
    parser.add_argument(
        "--fx-usd",
        type=float,
        default=None,
        help=help_text_usd,
    )
    help_text_chf = "EUR/CHF Kurs (im annual-Modus: Jahresdurchschnitt, im daily-Modus: Überschreibt automatische Kurse)"
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
        "--col-eur",
        default=DEFAULT_COLUMNS["net_amount_eur"],
        help="EUR-Spalte (Output)",
    )
    parser.add_argument("--round", action="store_true", help="Ergebnisse auf ganze Euro runden")
    parser.add_argument("--no-details", action="store_true", help="Details nicht ausgeben")
    parser.add_argument("--output", help="Ergebnisse in CSV-Datei schreiben")
    return parser.parse_args()


def load_csv(path: str, encoding: str, sep: str, date_col: str, amount_col: str) -> pl.DataFrame:
    """Load and preprocess a Swissquote CSV export.

    Handles Latin1 encoding, semicolon separators, date parsing, and
    amount field normalization (comma-to-period, dash-to-zero).
    """
    try:
        df = pl.read_csv(
            path,
            encoding=encoding,
            separator=sep,
            try_parse_dates=True,
            schema_overrides={date_col: pl.String},
        )
    except FileNotFoundError:
        sys.exit(f"Fehler: Datei '{path}' nicht gefunden")
    except Exception as e:
        sys.exit(f"Fehler beim Einlesen der CSV: {e}")

    if date_col not in df.columns:
        sys.exit(f"Fehler: Spalte '{date_col}' nicht gefunden")

    df = df.with_columns(pl.col(date_col).str.to_datetime(format="%d-%m-%Y %H:%M:%S", strict=False).alias(date_col))
    if df[date_col].is_null().any():
        bad = df.filter(pl.col(date_col).is_null()).head(5)
        sys.exit(f"Fehler: Ungültige Datumsformate in Spalte '{date_col}':\n{bad}")

    if amount_col in df.columns:
        if df[amount_col].dtype == pl.String:
            df = df.with_columns(
                pl.col(amount_col).str.replace_all(",", ".").str.replace("-", "0").cast(pl.Float64).alias(amount_col)
            )
        else:
            df = df.with_columns(pl.col(amount_col).cast(pl.Float64).alias(amount_col))

    return df


def detect_tax_year(df: pl.DataFrame, date_col: str) -> int:
    """Detect the tax year from transaction dates and enforce single-year range."""
    years = df[date_col].dt.year().drop_nulls().unique()
    if len(years) == 0:
        sys.exit("Fehler: Keine gültigen Daten in Datumsspalte")
    if len(years) > 1:
        years_list = sorted(years.to_list())
        years_str = ", ".join(map(str, years_list))
        sys.exit(
            f"Fehler: Transaktionen aus mehreren Jahren gefunden: {years_str}. Bitte pro Steuerjahr separat auswerten."
        )
    return int(years[0])


def validate_data(df: pl.DataFrame, amount_col: str, currency_col: str, type_col: str, date_col: str) -> None:
    """Validate transaction data for completeness and known currencies."""
    issues: list[str] = []

    if df[amount_col].is_null().any():
        issues.append(f"Fehlende Werte in '{amount_col}'")

    if df[currency_col].is_null().any():
        issues.append(f"Fehlende Werte in '{currency_col}'")

    if df[type_col].is_null().any():
        issues.append(f"Fehlende Werte in '{type_col}'")

    known_currencies: set = set(FALLBACK_FX_RATES[2025].keys())
    unknown_currencies: set = set(df[currency_col].drop_nulls().unique().to_list()) - known_currencies
    if unknown_currencies:
        issues.append(f"Unbekannte Währungen (kein FX-Kurs): {sorted(unknown_currencies)}")

    if issues:
        sys.exit("Validierungsfehler:\n  - " + "\n  - ".join(issues))


def format_amount(val: float, do_round: bool) -> str:
    """Format a Euro amount for display, optionally rounding to whole Euros."""
    if do_round:
        return f"{round(val)} EUR"
    return f"{val:.2f} EUR"


def print_section(title: str, df: pl.DataFrame, columns: list[str], amount_col: str, do_round: bool) -> None:
    """Print a titled section of transaction details with a sum total."""
    print(f"\n--- {title} ---")
    if df.is_empty():
        print("Keine Einträge")
        return
    display_cols: list[str] = [c for c in columns if c in df.columns]
    with pl.Config(
        tbl_rows=-1,
        tbl_cols=-1,
        fmt_str_lengths=100,
        tbl_hide_column_data_types=True,
        tbl_hide_dtype_separator=True,
        tbl_hide_dataframe_shape=True,
    ):
        print(df.select(display_cols))
    total: float = float(df[amount_col].sum())
    print(f"Summe: {format_amount(total, do_round)}")


def apply_fx_rates_daily(
    df: pl.DataFrame,
    fetcher: DailyFXRateFetcher,
    date_col: str,
    currency_col: str,
    amount_col: str,
    eur_col: str,
) -> pl.DataFrame:
    """Apply per-transaction daily exchange rates to convert amounts to EUR."""
    return df.with_columns(
        pl.struct([pl.col(date_col), pl.col(currency_col), pl.col(amount_col)])
        .map_elements(
            lambda row: (
                row[amount_col] / fetcher.get_rate(row[date_col].date(), row[currency_col])
                if row[currency_col] != "EUR"
                else row[amount_col]
            ),
            return_dtype=pl.Float64,
        )
        .alias(eur_col)
    )


def apply_fx_rates_annual(
    df: pl.DataFrame,
    fetcher: DailyFXRateFetcher,
    tax_year: int,
    currency_col: str,
    amount_col: str,
    eur_col: str,
    cli_usd: Optional[float],
    cli_chf: Optional[float],
    cli_eur: Optional[float],
) -> pl.DataFrame:
    """Apply annual-average exchange rates to convert amounts to EUR."""
    # If all three CLI rates are provided, use them directly without API calls
    if cli_usd is not None and cli_chf is not None and cli_eur is not None:
        annual_rates = {"USD": cli_usd, "CHF": cli_chf, "EUR": cli_eur}
    else:
        annual_rates = fetcher.fetch_annual_rates(tax_year)
        if annual_rates is None:
            annual_rates = fetcher.get_fallback_rates(tax_year)

        if cli_usd is not None:
            annual_rates["USD"] = cli_usd
        if cli_chf is not None:
            annual_rates["CHF"] = cli_chf
        if cli_eur is not None:
            annual_rates["EUR"] = cli_eur

    print(
        f"  Wechselkurse (Jahresdurchschnitt {tax_year}): "
        f"EUR/USD={annual_rates['USD']:.4f}, EUR/CHF={annual_rates['CHF']:.4f}"
    )

    return df.with_columns(
        pl.when(pl.col(currency_col) == "USD")
        .then(pl.col(amount_col) / annual_rates["USD"])
        .when(pl.col(currency_col) == "CHF")
        .then(pl.col(amount_col) / annual_rates["CHF"])
        .when(pl.col(currency_col) == "EUR")
        .then(pl.col(amount_col) / annual_rates["EUR"])
        .otherwise(pl.col(amount_col))
        .alias(eur_col)
    )


def main() -> None:
    """Evaluate Swissquote transaction CSV for German tax declarations (Anlage KAP / KAP-INV)."""
    args = parse_args()

    df = load_csv(args.csv_file, args.encoding, args.sep, args.col_date, args.col_amount)

    required_cols: list[str] = [args.col_type, args.col_currency, args.col_amount]
    missing: list[str] = [c for c in required_cols if c not in df.columns]
    if missing:
        sys.exit(f"Fehler: Fehlende Spalten in CSV: {missing}")

    tax_year: int = detect_tax_year(df, args.col_date)
    validate_data(df, args.col_amount, args.col_currency, args.col_type, args.col_date)

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

    dividends: pl.DataFrame = df.filter(pl.col(args.col_type).is_in(args.dividend_types))
    interest: pl.DataFrame = df.filter(pl.col(args.col_type).is_in(args.interest_types))

    total_dividends: float = dividends[args.col_eur].sum()
    total_interest: float = interest[args.col_eur].sum()

    dividend_text = f"1. Anlage KAP-INV (Zeile 4 - ETF-Ausschüttungen): {format_amount(total_dividends, args.round)}"
    print(dividend_text)
    zinsen_text = f"2. Anlage KAP (Zeile 19 - Ausländische Zinsen):   {format_amount(total_interest, args.round)}"
    print(zinsen_text)

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

    if args.output:
        output_df: pl.DataFrame = pl.concat(
            [
                dividends.with_columns(pl.lit("Dividende").alias("Kategorie")),
                interest.with_columns(pl.lit("Zinsen").alias("Kategorie")),
            ]
        )
        output_df.write_csv(args.output, separator=args.sep)
        print(f"\nDetails nach '{args.output}' exportiert")


if __name__ == "__main__":
    main()
