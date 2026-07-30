import sys
from pathlib import Path

import polars as pl
from loguru import logger

from taxes.fx_rates import FALLBACK_FX_RATES


def load_csv(
    path: Path,
    encoding: str,
    separator: str,
    date_col: str,
    amount_col: str,
    withholding_tax_col: str,
) -> pl.DataFrame:
    """Load a Swissquote CSV and normalize its date and amount columns."""
    try:
        dataframe = pl.read_csv(
            path,
            encoding=encoding,
            separator=separator,
            try_parse_dates=True,
            schema_overrides={date_col: pl.String},
        )
    except FileNotFoundError:
        sys.exit(f"Fehler: Datei '{path}' nicht gefunden")
    except (ValueError, OSError) as error:
        logger.error(f"Failed to read CSV '{path}': {error}")
        sys.exit(f"Fehler beim Einlesen der CSV: {error}")

    if date_col not in dataframe.columns:
        sys.exit(f"Fehler: Spalte '{date_col}' nicht gefunden")

    dataframe = dataframe.with_columns(
        pl.col(date_col).str.to_datetime(format="%d-%m-%Y %H:%M:%S", strict=False).alias(date_col)
    )
    if dataframe[date_col].is_null().any():
        invalid_dates = dataframe.filter(pl.col(date_col).is_null()).head(5)
        sys.exit(f"Fehler: Ungültige Datumsformate in Spalte '{date_col}':\n{invalid_dates}")

    if amount_col in dataframe.columns:
        if dataframe[amount_col].dtype == pl.String:
            dataframe = dataframe.with_columns(
                pl.col(amount_col).str.replace_all(",", ".").str.replace("-", "0").cast(pl.Float64).alias(amount_col)
            )
        else:
            dataframe = dataframe.with_columns(pl.col(amount_col).cast(pl.Float64).alias(amount_col))

    if withholding_tax_col in dataframe.columns:
        if dataframe[withholding_tax_col].dtype == pl.String:
            dataframe = dataframe.with_columns(
                pl.col(withholding_tax_col)
                .str.replace_all(",", ".")
                .str.replace_all(r"^-$", "0")
                .cast(pl.Float64)
                .alias(withholding_tax_col)
            )
        else:
            dataframe = dataframe.with_columns(pl.col(withholding_tax_col).cast(pl.Float64).alias(withholding_tax_col))

    return dataframe


def detect_tax_year(dataframe: pl.DataFrame, date_col: str, requested_year: int | None = None) -> int:
    """Detect the tax year, or select one explicitly for a historical CSV."""
    years = dataframe[date_col].dt.year().drop_nulls().unique()
    if len(years) == 0:
        sys.exit("Fehler: Keine gültigen Daten in Datumsspalte")
    years_list = sorted(years.to_list())
    if requested_year is not None:
        if requested_year not in years_list:
            sys.exit(f"Fehler: Steuerjahr {requested_year} ist nicht in der CSV enthalten")
        return requested_year
    if len(years) > 1:
        years_str = ", ".join(map(str, years_list))
        sys.exit(
            f"Fehler: Transaktionen aus mehreren Jahren gefunden: {years_str}. "
            "Bitte --tax-year für das auszuwertende Jahr angeben."
        )
    return int(years[0])


def validate_data(dataframe: pl.DataFrame, amount_col: str, currency_col: str, type_col: str) -> None:
    """Validate transaction data for completeness and known currencies."""
    issues: list[str] = []

    if dataframe[amount_col].is_null().any():
        issues.append(f"Fehlende Werte in '{amount_col}'")
    if dataframe[currency_col].is_null().any():
        issues.append(f"Fehlende Werte in '{currency_col}'")
    if dataframe[type_col].is_null().any():
        issues.append(f"Fehlende Werte in '{type_col}'")

    known_currencies = set(FALLBACK_FX_RATES[2025])
    currencies = set(dataframe[currency_col].drop_nulls().unique().to_list())
    unknown_currencies = currencies - known_currencies
    if unknown_currencies:
        issues.append(f"Unbekannte Währungen (kein FX-Kurs): {sorted(unknown_currencies)}")

    if issues:
        sys.exit("Validierungsfehler:\n  - " + "\n  - ".join(issues))
