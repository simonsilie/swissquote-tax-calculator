import sys
from pathlib import Path

import polars as pl
from loguru import logger

from taxes.fx_rates import FALLBACK_FX_RATES

DATE_FORMAT = "%d-%m-%Y %H:%M:%S"
_SAMPLE_LIMIT = 5
_ROW_NUMBER_LIMIT = 10
# CSV line numbering: line 1 is the header, data rows start at line 2.
_ROW_NUMBER_OFFSET = 2


def _row_numbers(dataframe: pl.DataFrame, mask: pl.Series, limit: int = _ROW_NUMBER_LIMIT) -> list[int]:
    """Return the CSV line numbers (1-based, header = line 1) of rows matching ``mask``."""
    return (
        dataframe.with_row_index("CSV_Zeile", offset=_ROW_NUMBER_OFFSET)
        .filter(mask)
        .get_column("CSV_Zeile")
        .head(limit)
        .to_list()
    )


def _format_numbered_rows(entries: list[tuple[int, object]], total: int) -> str:
    """Format ``[(line number, raw value)]`` samples plus a count of the rest."""
    lines = [f"  Zeile {number}: {value!r}" for number, value in entries]
    hidden = total - len(entries)
    if hidden > 0:
        lines.append(f"  ... und {hidden} weitere Zeilen")
    return "\n".join(lines)


def load_csv(
    path: Path,
    encoding: str,
    separator: str,
    date_col: str,
    amount_col: str,
    withholding_tax_col: str,
) -> pl.DataFrame:
    """Load a Swissquote CSV and strictly validate its date and amount columns."""
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

    dataframe = _validate_and_parse_dates(dataframe, date_col)
    dataframe = _parse_numeric_column(dataframe, amount_col)
    dataframe = _parse_numeric_column(dataframe, withholding_tax_col)

    return dataframe


def _validate_and_parse_dates(dataframe: pl.DataFrame, date_col: str) -> pl.DataFrame:
    """Parse the date column, reporting invalid values with CSV line numbers."""
    raw_dates = dataframe.get_column(date_col)
    parsed_dates = raw_dates.str.to_datetime(format=DATE_FORMAT, strict=False)

    invalid_mask = parsed_dates.is_null()
    if invalid_mask.any():
        raw_values = dataframe.filter(invalid_mask).get_column(date_col).head(_SAMPLE_LIMIT).to_list()
        total = int(invalid_mask.sum())
        entries = list(zip(_row_numbers(dataframe, invalid_mask), raw_values, strict=True))
        sys.exit(
            f"Fehler: Ungültige Datumsformate in Spalte '{date_col}' "
            f"(erwartet '{DATE_FORMAT}', {total} betroffene Zeilen):\n"
            f"{_format_numbered_rows(entries, total)}"
        )

    return dataframe.with_columns(parsed_dates.alias(date_col))


def _parse_numeric_column(dataframe: pl.DataFrame, column: str) -> pl.DataFrame:
    """Parse a CSV column to Float64, reporting invalid values with line numbers.

    String values are normalized (thousand separators, decimal commas) before a
    non-strict cast. An empty cell becomes null (reported later as a missing
    value); a bare ``-`` is treated as 0, matching the Swissquote export
    convention. Any other unparseable value aborts with the affected rows.
    """
    if column not in dataframe.columns:
        return dataframe

    dtype = dataframe.schema[column]
    if dtype != pl.String:
        return dataframe.with_columns(pl.col(column).cast(pl.Float64).alias(column))

    raw = pl.col(column).str.strip_chars()
    cleaned = raw.str.replace_all(",", ".").str.replace_all("'", "")
    numeric = (
        pl.when(cleaned.is_null() | (cleaned == ""))
        .then(pl.lit(None, dtype=pl.Float64))
        .when(cleaned == "-")
        .then(pl.lit(0.0))
        .otherwise(cleaned.cast(pl.Float64, strict=False))
    )
    candidate = dataframe.with_columns(numeric.alias(column))

    # Invalid format: the raw cell has content but did not parse to a number.
    invalid_mask = (
        candidate.get_column(column).is_null()
        & dataframe.get_column(column).is_not_null()
        & (dataframe.get_column(column).str.strip_chars() != "")
    )
    if invalid_mask.any():
        raw_values = (
            dataframe.filter(invalid_mask)
            .get_column(column)
            .head(_SAMPLE_LIMIT)
            .to_list()
        )
        total = int(invalid_mask.sum())
        entries = list(zip(_row_numbers(dataframe, invalid_mask), raw_values, strict=True))
        sys.exit(
            f"Fehler: Ungültige Zahlenformate in Spalte '{column}' "
            f"({total} betroffene Zeilen):\n{_format_numbered_rows(entries, total)}"
        )

    return candidate


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

    for column in (amount_col, currency_col, type_col):
        if column not in dataframe.columns:
            continue
        null_mask = dataframe.get_column(column).is_null()
        if null_mask.any():
            numbers = _row_numbers(dataframe, null_mask)
            issues.append(f"Fehlende Werte in '{column}' (z.B. Zeile(n): {numbers})")

    known_currencies = set(FALLBACK_FX_RATES[2025])
    currencies = set(dataframe[currency_col].drop_nulls().unique().to_list())
    unknown_currencies = currencies - known_currencies
    if unknown_currencies:
        issues.append(f"Unbekannte Währungen (kein FX-Kurs): {sorted(unknown_currencies)}")

    if issues:
        sys.exit("Validierungsfehler:\n  - " + "\n  - ".join(issues))
