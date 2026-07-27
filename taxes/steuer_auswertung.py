#!/usr/bin/env python3
import argparse
import json
import statistics
import sys
import urllib.request
from urllib.error import URLError
from typing import Optional

import polars as pl


# Hardcoded fallback annual average rates (EZB)
FALLBACK_FX_RATES: dict[int, dict[str, float]] = {
    2025: {"USD": 1.05, "CHF": 0.93, "EUR": 1.00},
    2024: {"USD": 1.0825, "CHF": 0.9525, "EUR": 1.00},
    2023: {"USD": 1.0812, "CHF": 0.9718, "EUR": 1.00},
    2022: {"USD": 1.0534, "CHF": 1.0048, "EUR": 1.00},
    2021: {"USD": 1.1829, "CHF": 1.0811, "EUR": 1.00},
    2020: {"USD": 1.1421, "CHF": 1.0706, "EUR": 1.00},
}

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


def fetch_annual_fx_rates(year: int) -> Optional[dict[str, float]]:
    """Fetch annual average EUR/USD and EUR/CHF rates from frankfurter.dev API."""
    url = f"https://api.frankfurter.dev/v1/{year}-01-01..{year}-12-31?from=EUR&to=USD,CHF"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; TaxScript/1.0)")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.load(response)
    except URLError, json.JSONDecodeError, KeyError:
        return None

    rates = data.get("rates", {})
    usd_rates = [v["USD"] for v in rates.values() if "USD" in v]
    chf_rates = [v["CHF"] for v in rates.values() if "CHF" in v]

    if not usd_rates or not chf_rates:
        return None

    return {
        "USD": round(statistics.mean(usd_rates), 4),
        "CHF": round(statistics.mean(chf_rates), 4),
        "EUR": 1.00,
    }


def get_fx_rates_for_year(
    year: int,
    cli_usd: Optional[float],
    cli_chf: Optional[float],
    cli_eur: Optional[float],
) -> dict[str, float]:
    """Get FX rates for a year: CLI args (if provided) > API > fallback table."""
    if cli_usd is not None or cli_chf is not None or cli_eur is not None:
        usd_rate = cli_usd if cli_usd is not None else None
        chf_rate = cli_chf if cli_chf is not None else None
        eur_rate = cli_eur if cli_eur is not None else None

        if usd_rate is not None and chf_rate is not None and eur_rate is not None:
            return {"USD": usd_rate, "CHF": chf_rate, "EUR": eur_rate}

        api_rates = fetch_annual_fx_rates(year)
        if api_rates is None:
            api_rates = FALLBACK_FX_RATES.get(year, FALLBACK_FX_RATES[2025])

        if usd_rate is not None:
            api_rates["USD"] = usd_rate
        if chf_rate is not None:
            api_rates["CHF"] = chf_rate
        if eur_rate is not None:
            api_rates["EUR"] = eur_rate

        return api_rates

    api_rates = fetch_annual_fx_rates(year)
    if api_rates:
        print(
            f"  Wechselkurse (Jahresdurchschnitt {year} via frankfurter.dev): "
            f"EUR/USD={api_rates['USD']:.4f}, EUR/CHF={api_rates['CHF']:.4f}"
        )
        return api_rates

    fallback = FALLBACK_FX_RATES.get(year, FALLBACK_FX_RATES[2025])
    fallback_rate_usd = fallback["USD"]
    fallback_rate_chf = fallback["CHF"]
    print(f"  Wechselkurse (Fallback für {year}): EUR/USD={fallback_rate_usd:.4f}, EUR/CHF={fallback_rate_chf:.4f}")
    return fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Steuerauswertung für Swissquote-Transaktionen",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("csv_file", help="Pfad zur CSV-Datei (Swissquote Export)")
    parser.add_argument("--encoding", default="latin1", help="CSV-Encoding")
    parser.add_argument("--sep", default=";", help="CSV-Trennzeichen")
    help_text_usd = "EUR/USD Kurs (Jahresdurchschnitt für erkanntes Jahr, wenn nicht angegeben)"
    parser.add_argument(
        "--fx-usd",
        type=float,
        default=None,
        help=help_text_usd,
    )
    help_text_chf = "EUR/CHF Kurs (Jahresdurchschnitt für erkanntes Jahr, wenn nicht angegeben)"
    parser.add_argument(
        "--fx-chf",
        type=float,
        default=None,
        help=help_text_chf,
    )
    parser.add_argument("--fx-eur", type=float, default=None, help="EUR/EUR Kurs (standardmäßig 1.0)")
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
    if do_round:
        return f"{round(val)} EUR"
    return f"{val:.2f} EUR"


def print_section(title: str, df: pl.DataFrame, columns: list[str], amount_col: str, do_round: bool) -> None:
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


def main() -> None:
    args = parse_args()

    df = load_csv(args.csv_file, args.encoding, args.sep, args.col_date, args.col_amount)

    required_cols: list[str] = [args.col_type, args.col_currency, args.col_amount]
    missing: list[str] = [c for c in required_cols if c not in df.columns]
    if missing:
        sys.exit(f"Fehler: Fehlende Spalten in CSV: {missing}")

    tax_year: int = detect_tax_year(df, args.col_date)
    validate_data(df, args.col_amount, args.col_currency, args.col_type, args.col_date)

    fx_rates: dict[str, float] = get_fx_rates_for_year(tax_year, args.fx_usd, args.fx_chf, args.fx_eur)

    df = df.with_columns(
        pl.when(pl.col(args.col_currency) == "USD")
        .then(pl.col(args.col_amount) / fx_rates["USD"])
        .when(pl.col(args.col_currency) == "CHF")
        .then(pl.col(args.col_amount) / fx_rates["CHF"])
        .when(pl.col(args.col_currency) == "EUR")
        .then(pl.col(args.col_amount) / fx_rates["EUR"])
        .otherwise(pl.col(args.col_amount))
        .alias(args.col_eur)
    )

    dividends: pl.DataFrame = df.filter(pl.col(args.col_type).is_in(args.dividend_types))
    interest: pl.DataFrame = df.filter(pl.col(args.col_type).is_in(args.interest_types))

    total_dividends: float = dividends[args.col_eur].sum()
    total_interest: float = interest[args.col_eur].sum()

    print(f"=== AUSWERTUNG FÜR STEUERJAHR {tax_year} ===")
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
