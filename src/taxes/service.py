from dataclasses import dataclass, field
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
class TaxConfig:
    """Input configuration for a tax calculation run.

    Bundles the CSV source, column mappings, transaction-type mappings, and
    output options so that ``calculate_taxes`` takes a single object instead
    of 23 loose parameters. Field defaults mirror the Swissquote standard
    export; the CLI passes user overrides into a fresh instance.
    """

    csv_file: Path
    tax_year: int | None = None
    encoding: str = "latin1"
    sep: str = ";"
    dividend_types: list[str] = field(default_factory=lambda: DEFAULT_DIVIDEND_TYPES.copy())
    interest_types: list[str] = field(default_factory=lambda: DEFAULT_INTEREST_TYPES.copy())
    withholding_tax_types: list[str] = field(default_factory=lambda: DEFAULT_WITHHOLDING_TAX_TYPES.copy())
    purchase_types: list[str] = field(default_factory=lambda: DEFAULT_PURCHASE_TYPES.copy())
    sale_types: list[str] = field(default_factory=lambda: DEFAULT_SALE_TYPES.copy())
    col_date: str = DEFAULT_COLUMNS["date"]
    col_name: str = DEFAULT_COLUMNS["name"]
    col_type: str = DEFAULT_COLUMNS["transaction_type"]
    col_currency: str = DEFAULT_COLUMNS["currency"]
    col_amount: str = DEFAULT_COLUMNS["net_amount"]
    col_withholding_tax: str = DEFAULT_COLUMNS["withholding_tax"]
    col_withholding_tax_eur: str = DEFAULT_COLUMNS["withholding_tax_eur"]
    col_isin: str = DEFAULT_COLUMNS["isin"]
    col_quantity: str = DEFAULT_COLUMNS["quantity"]
    col_eur: str = DEFAULT_COLUMNS["net_amount_eur"]
    col_gross_eur: str = DEFAULT_COLUMNS["gross_amount_eur"]
    round_amount: bool = False
    withholding_tax_rules_path: Path | None = None


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


def calculate_taxes(config: TaxConfig) -> TaxCalculationResult:
    tax_year = config.tax_year
    encoding = config.encoding
    sep = config.sep
    dividend_types = config.dividend_types
    interest_types = config.interest_types
    withholding_tax_types = config.withholding_tax_types
    purchase_types = config.purchase_types
    sale_types = config.sale_types
    col_date = config.col_date
    col_name = config.col_name
    col_type = config.col_type
    col_currency = config.col_currency
    col_amount = config.col_amount
    col_withholding_tax = config.col_withholding_tax
    col_withholding_tax_eur = config.col_withholding_tax_eur
    col_isin = config.col_isin
    col_quantity = config.col_quantity
    col_eur = config.col_eur
    col_gross_eur = config.col_gross_eur
    round_amount = config.round_amount

    withholding_tax_rules_path = config.withholding_tax_rules_path
    if withholding_tax_rules_path is None and DEFAULT_WITHHOLDING_TAX_RULES_FILE.is_file():
        withholding_tax_rules_path = DEFAULT_WITHHOLDING_TAX_RULES_FILE

    try:
        withholding_tax_rules = load_security_tax_rules(withholding_tax_rules_path)
    except ValueError as error:
        raise ValueError(f"Fehler beim Laden der Quellensteuer-Regeln: {error}") from error

    df = load_csv(
        config.csv_file,
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
