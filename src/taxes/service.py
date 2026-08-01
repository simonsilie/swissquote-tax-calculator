from dataclasses import dataclass
from pathlib import Path

import polars as pl
from loguru import logger

from taxes.currency_conversion import apply_fx_rates_daily
from taxes.fx_rates import DailyFXRateFetcher
from taxes.stock_sales import calculate_realized_stock_results
from taxes.transactions import detect_tax_year, load_csv, validate_data
from taxes.withholding_tax import (
    FUND_FORM,
    DOMESTIC_SHARE_FORM,
    FOREIGN_SHARE_FORM,
    WithholdingTaxSummary,
    classify_embedded_withholding_taxes,
    classify_standalone_withholding_taxes,
    load_security_tax_rules,
    tag_dividend_forms,
)

DEFAULT_DIVIDEND_TYPES: list[str] = ["Dividende"]
DEFAULT_INTEREST_TYPES: list[str] = ["Zinsen auf Einlagen"]
DEFAULT_WITHHOLDING_TAX_TYPES: list[str] = ["Steuerrückbehalt", "Quellensteuer", "Withholding Tax"]
DEFAULT_PURCHASE_TYPES: list[str] = ["Kauf"]
DEFAULT_SALE_TYPES: list[str] = ["Verkauf"]
DEFAULT_WITHHOLDING_TAX_RULES_FILE = Path("withholding-tax-rules.toml")

DEFAULT_COLUMNS: dict[str, str] = {
    "date": "Datum",
    "name": "Name",
    "transaction_type": "Transaktionen",
    "currency": "Währung",
    "net_amount": "Nettobetrag",
    "net_amount_eur": "Nettobetrag_EUR",
    "gross_amount_eur": "Bruttobetrag_EUR",
    "withholding_tax": "Kosten",
    "withholding_tax_eur": "Quellensteuer_EUR",
    "isin": "ISIN",
    "quantity": "Anzahl",
}


@dataclass
class TaxCalculationResult:
    tax_year: int
    df: pl.DataFrame
    tax_year_df: pl.DataFrame
    dividends: pl.DataFrame
    interest: pl.DataFrame
    withholding_tax_transactions: pl.DataFrame
    stock_sales: pl.DataFrame
    total_interest: float
    total_stock_sales: float
    dividend_tax_summary: WithholdingTaxSummary
    interest_tax_summary: WithholdingTaxSummary
    standalone_tax_summary: WithholdingTaxSummary
    withholding_tax_summary: WithholdingTaxSummary
    domestic_share_dividends: pl.DataFrame
    foreign_share_dividends: pl.DataFrame
    fund_dividends: pl.DataFrame
    total_domestic_share_dividends: float
    total_foreign_share_dividends: float
    total_fund_dividends: float
    stock_gains: float
    stock_losses: float
    col_date: str
    col_name: str
    col_amount: str
    col_currency: str
    col_type: str
    col_eur: str
    col_gross_eur: str
    col_withholding_tax: str
    col_withholding_tax_eur: str
    col_isin: str
    col_quantity: str
    round: bool


def calculate_taxes(
    csv_file: Path,
    tax_year: int | None = None,
    encoding: str = "latin1",
    sep: str = ";",
    dividend_types: list[str] | None = None,
    interest_types: list[str] | None = None,
    withholding_tax_types: list[str] | None = None,
    purchase_types: list[str] | None = None,
    sale_types: list[str] | None = None,
    col_date: str | None = None,
    col_name: str | None = None,
    col_type: str | None = None,
    col_currency: str | None = None,
    col_amount: str | None = None,
    col_withholding_tax: str | None = None,
    col_withholding_tax_eur: str | None = None,
    col_isin: str | None = None,
    col_quantity: str | None = None,
    col_eur: str | None = None,
    col_gross_eur: str | None = None,
    round_amount: bool = False,
    withholding_tax_rules_path: Path | None = None,
) -> TaxCalculationResult:
    if dividend_types is None:
        dividend_types = DEFAULT_DIVIDEND_TYPES
    if interest_types is None:
        interest_types = DEFAULT_INTEREST_TYPES
    if withholding_tax_types is None:
        withholding_tax_types = DEFAULT_WITHHOLDING_TAX_TYPES
    if purchase_types is None:
        purchase_types = DEFAULT_PURCHASE_TYPES
    if sale_types is None:
        sale_types = DEFAULT_SALE_TYPES
    if col_date is None:
        col_date = DEFAULT_COLUMNS["date"]
    if col_name is None:
        col_name = DEFAULT_COLUMNS["name"]
    if col_type is None:
        col_type = DEFAULT_COLUMNS["transaction_type"]
    if col_currency is None:
        col_currency = DEFAULT_COLUMNS["currency"]
    if col_amount is None:
        col_amount = DEFAULT_COLUMNS["net_amount"]
    if col_withholding_tax is None:
        col_withholding_tax = DEFAULT_COLUMNS["withholding_tax"]
    if col_withholding_tax_eur is None:
        col_withholding_tax_eur = DEFAULT_COLUMNS["withholding_tax_eur"]
    if col_isin is None:
        col_isin = DEFAULT_COLUMNS["isin"]
    if col_quantity is None:
        col_quantity = DEFAULT_COLUMNS["quantity"]
    if col_eur is None:
        col_eur = DEFAULT_COLUMNS["net_amount_eur"]
    if col_gross_eur is None:
        col_gross_eur = DEFAULT_COLUMNS["gross_amount_eur"]

    if withholding_tax_rules_path is None and DEFAULT_WITHHOLDING_TAX_RULES_FILE.is_file():
        withholding_tax_rules_path = DEFAULT_WITHHOLDING_TAX_RULES_FILE

    try:
        withholding_tax_rules = load_security_tax_rules(withholding_tax_rules_path)
    except ValueError as error:
        raise ValueError(f"Fehler beim Laden der Quellensteuer-Regeln: {error}") from error

    df = load_csv(
        csv_file,
        encoding,
        sep,
        col_date,
        col_amount,
        col_withholding_tax,
    )

    required_cols: list[str] = [col_type, col_currency, col_amount]
    missing: list[str] = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Fehler: Fehlende Spalten in CSV: {missing}")

    resolved_tax_year: int = detect_tax_year(df, col_date, tax_year)
    validate_data(df, col_amount, col_currency, col_type)

    fetcher = DailyFXRateFetcher()

    logger.info(f"=== AUSWERTUNG FÜR STEUERJAHR {resolved_tax_year} ===")
    df = apply_fx_rates_daily(df, fetcher, col_date, col_currency, col_amount, col_eur)

    if col_withholding_tax in df.columns:
        df = apply_fx_rates_daily(
            df,
            fetcher,
            col_date,
            col_currency,
            col_withholding_tax,
            col_withholding_tax_eur,
        )

    if col_withholding_tax_eur in df.columns:
        df = df.with_columns(
            (pl.col(col_eur) + pl.col(col_withholding_tax_eur).abs().fill_null(0.0)).alias(col_gross_eur)
        )
    else:
        df = df.with_columns(pl.col(col_eur).alias(col_gross_eur))

    tax_year_df = df.filter(pl.col(col_date).dt.year() == resolved_tax_year)
    dividends: pl.DataFrame = tax_year_df.filter(pl.col(col_type).is_in(dividend_types))
    interest: pl.DataFrame = tax_year_df.filter(pl.col(col_type).is_in(interest_types))
    withholding_tax_transactions: pl.DataFrame = tax_year_df.filter(pl.col(col_type).is_in(withholding_tax_types))
    try:
        stock_sales = calculate_realized_stock_results(
            df,
            purchase_types,
            sale_types,
            col_date,
            col_type,
            col_isin,
            col_quantity,
            col_eur,
        ).filter(pl.col(col_date).dt.year() == resolved_tax_year)
    except ValueError as error:
        raise ValueError(f"Fehler: {error}") from error

    total_interest: float = float(interest[col_gross_eur].sum())
    total_stock_sales: float = float(stock_sales["Gewinn_Verlust_EUR"].sum())
    dividend_tax_summary = WithholdingTaxSummary()
    interest_tax_summary = WithholdingTaxSummary()
    standalone_tax_summary = WithholdingTaxSummary()
    if col_withholding_tax_eur in df.columns:
        dividends, dividend_tax_summary = classify_embedded_withholding_taxes(
            dividends,
            withholding_tax_rules,
            col_isin,
            col_eur,
            col_withholding_tax_eur,
        )
        interest, interest_tax_summary = classify_embedded_withholding_taxes(
            interest,
            withholding_tax_rules,
            col_isin,
            col_eur,
            col_withholding_tax_eur,
        )
    withholding_tax_transactions, standalone_tax_summary = classify_standalone_withholding_taxes(
        withholding_tax_transactions,
        withholding_tax_rules,
        col_isin,
        col_eur,
    )
    combined_withholding_tax_summary = dividend_tax_summary + interest_tax_summary + standalone_tax_summary

    dividends = tag_dividend_forms(dividends, withholding_tax_rules, col_isin)
    domestic_share_dividends = dividends.filter(pl.col("Formular") == DOMESTIC_SHARE_FORM)
    foreign_share_dividends = dividends.filter(pl.col("Formular") == FOREIGN_SHARE_FORM)
    fund_dividends = dividends.filter(pl.col("Formular") == FUND_FORM)
    total_domestic_share_dividends: float = float(domestic_share_dividends[col_gross_eur].sum())
    total_foreign_share_dividends: float = float(foreign_share_dividends[col_gross_eur].sum())
    total_fund_dividends: float = float(fund_dividends[col_gross_eur].sum())

    stock_gains = float(stock_sales.filter(pl.col("Gewinn_Verlust_EUR") > 0)["Gewinn_Verlust_EUR"].sum())
    stock_losses = float(stock_sales.filter(pl.col("Gewinn_Verlust_EUR") < 0)["Gewinn_Verlust_EUR"].sum())

    return TaxCalculationResult(
        tax_year=resolved_tax_year,
        df=df,
        tax_year_df=tax_year_df,
        dividends=dividends,
        interest=interest,
        withholding_tax_transactions=withholding_tax_transactions,
        stock_sales=stock_sales,
        total_interest=total_interest,
        total_stock_sales=total_stock_sales,
        dividend_tax_summary=dividend_tax_summary,
        interest_tax_summary=interest_tax_summary,
        standalone_tax_summary=standalone_tax_summary,
        withholding_tax_summary=combined_withholding_tax_summary,
        domestic_share_dividends=domestic_share_dividends,
        foreign_share_dividends=foreign_share_dividends,
        fund_dividends=fund_dividends,
        total_domestic_share_dividends=total_domestic_share_dividends,
        total_foreign_share_dividends=total_foreign_share_dividends,
        total_fund_dividends=total_fund_dividends,
        stock_gains=stock_gains,
        stock_losses=stock_losses,
        col_date=col_date,
        col_name=col_name,
        col_amount=col_amount,
        col_currency=col_currency,
        col_type=col_type,
        col_eur=col_eur,
        col_gross_eur=col_gross_eur,
        col_withholding_tax=col_withholding_tax,
        col_withholding_tax_eur=col_withholding_tax_eur,
        col_isin=col_isin,
        col_quantity=col_quantity,
        round=round_amount,
    )
