"""Presentation layer for the Streamlit app.

Converts a tax calculation :class:`~taxes.result.Result` into plain-data
view models and wraps the calculation and ELSTER export behind thin
functions. The app imports only this module, which keeps Streamlit
decoupled from the business logic and the UI logic unit-testable
without Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from taxes.elster_export import export_elster_mapping
from taxes.reporting import format_amount
from taxes.result import Result
from taxes.service import TaxConfig, calculate_taxes

__all__ = [
    "DetailTab",
    "DetailsView",
    "Metric",
    "Result",
    "ResultsView",
    "WithholdingTaxView",
    "build_details_view",
    "build_results_view",
    "calculate",
    "export_summary",
]

# Computed columns shown in the detail tabs in addition to the configured
# input columns; the first three describe stock sales instead of income.
_DETAIL_COLUMNS: tuple[str, ...] = (
    "Formular",
    "Quellenstaat",
    "Steuerbehandlung",
    "Anrechenbare_Quellensteuer_EUR",
    "Nicht_anrechenbare_Quellensteuer_EUR",
    "Inlaendische_Kapitalertragsteuer_EUR",
    "Solidaritaetszuschlag_EUR",
    "Nicht_klassifizierte_Steuer_EUR",
)
_SALE_COLUMNS: tuple[str, ...] = (
    "Verkaufserloes_EUR",
    "Anschaffungskosten_EUR",
    "Gewinn_Verlust_EUR",
)


@dataclass(frozen=True)
class Metric:
    """A single labeled, pre-formatted figure."""

    label: str
    value: str


@dataclass(frozen=True)
class WithholdingTaxView:
    """Withholding-tax sections 3 and 4 of the results summary."""

    creditable_metric: Metric
    country_breakdown: tuple[tuple[str, str], ...]
    split_metrics: tuple[Metric, ...]
    excess_note: str | None
    swiss_refund_note: str | None
    credit_metrics: tuple[Metric, ...]
    unclassified_note: str | None


@dataclass(frozen=True)
class ResultsView:
    """View model for the results summary page."""

    tax_year: int
    dividend_metrics: tuple[Metric, ...]
    interest_metric: Metric
    withholding_tax: WithholdingTaxView | None
    stock_metrics: tuple[Metric, ...]


@dataclass(frozen=True)
class DetailTab:
    """One transaction table of the details expander."""

    title: str
    transactions: pl.DataFrame
    total: str | None


@dataclass(frozen=True)
class DetailsView:
    """View model for the transaction details expander."""

    tabs: tuple[DetailTab, ...]


def calculate(csv_file: Path, tax_year: int | None = None, round_amount: bool = False) -> Result:
    """Run the tax calculation with the options the app collects."""
    config = TaxConfig(csv_file=csv_file, tax_year=tax_year, round_amount=round_amount)
    return calculate_taxes(config)


def build_results_view(result: Result) -> ResultsView:
    """Map a calculation result onto the five summary sections."""

    def fmt(value: float) -> str:
        return format_amount(value, result.config.round_amount)

    withholding_tax: WithholdingTaxView | None = None
    if result.config.col_withholding_tax_eur in result.df.columns or not result.withholding_tax_transactions.is_empty():
        summary = result.withholding_tax_summary
        withholding_tax = WithholdingTaxView(
            creditable_metric=Metric("Zeile 41", fmt(summary.foreign_creditable)),
            country_breakdown=tuple(
                (country, fmt(amount)) for country, amount in summary.foreign_creditable_by_country
            ),
            split_metrics=(
                Metric("Davon Dividenden", fmt(result.dividends.tax_summary.foreign_creditable)),
                Metric("Davon Zinsen", fmt(result.interest.tax_summary.foreign_creditable)),
            ),
            excess_note=(
                f"Nicht anrechenbarer Steuerüberhang: {fmt(summary.foreign_excess)}" if summary.foreign_excess else None
            ),
            swiss_refund_note=(
                f"Schweizer Verrechnungssteuer (separat rückforderbar): {fmt(summary.swiss_refundable)}"
                if summary.swiss_refundable
                else None
            ),
            credit_metrics=(
                Metric("Zeile 37 - Kapitalertragsteuer", fmt(summary.domestic_capital_gains_tax)),
                Metric("Zeile 38 - Soli", fmt(summary.domestic_solidarity_surcharge)),
                Metric("Summe dt. KapSt + Soli", fmt(summary.domestic)),
            ),
            unclassified_note=(
                f"Nicht klassifizierte Steuer: {fmt(summary.unclassified)}" if summary.unclassified else None
            ),
        )

    return ResultsView(
        tax_year=result.tax_year,
        dividend_metrics=(
            Metric("Anlage KAP Zeile 18 - Inländisch", fmt(result.dividends.total_domestic_shares)),
            Metric("Anlage KAP Zeile 19 - Ausländisch", fmt(result.dividends.total_foreign_shares)),
            Metric("Anlage KAP-INV Zeile 4 - Fonds/ETFs", fmt(result.dividends.total_funds)),
        ),
        interest_metric=Metric("Zeile 19", fmt(result.interest.total)),
        withholding_tax=withholding_tax,
        stock_metrics=(
            Metric("Aktiengewinne", fmt(result.stock_sales.gains)),
            Metric("Aktienverluste", fmt(result.stock_sales.losses)),
            Metric("Summe", fmt(result.stock_sales.total)),
        ),
    )


def _detail_columns(result: Result) -> tuple[str, ...]:
    config = result.config
    return (
        config.col_date,
        config.col_name,
        config.col_amount,
        config.col_currency,
        config.col_eur,
        config.col_gross_eur,
        config.col_withholding_tax,
        config.col_withholding_tax_eur,
        *_DETAIL_COLUMNS,
    )


def _sale_columns(result: Result) -> tuple[str, ...]:
    config = result.config
    return (config.col_date, config.col_isin, config.col_quantity, *_SALE_COLUMNS)


def _detail_tab(
    result: Result,
    title: str,
    transactions: pl.DataFrame,
    columns: tuple[str, ...],
    sum_col: str | None,
) -> DetailTab:
    """Slice a transaction frame to the columns the UI can show."""
    sliced = transactions.select([column for column in columns if column in transactions.columns])
    total: str | None = None
    if sum_col is not None and not transactions.is_empty():
        total = f"Summe: {format_amount(float(transactions[sum_col].sum()), result.config.round_amount)}"
    return DetailTab(title=title, transactions=sliced, total=total)


def build_details_view(result: Result) -> DetailsView:
    """Map the transaction frames onto the four detail tabs."""
    detail_columns = _detail_columns(result)
    return DetailsView(
        tabs=(
            _detail_tab(
                result,
                "Dividenden",
                result.dividends.transactions,
                detail_columns,
                result.config.col_gross_eur,
            ),
            _detail_tab(
                result,
                "Zinsen",
                result.interest.transactions,
                detail_columns,
                result.config.col_gross_eur,
            ),
            _detail_tab(
                result,
                "Quellensteuer-Buchungen",
                result.withholding_tax_transactions,
                detail_columns,
                result.config.col_eur,
            ),
            _detail_tab(
                result,
                "Aktienverkäufe",
                result.stock_sales.transactions,
                _sale_columns(result),
                None,
            ),
        )
    )


def export_summary(result: Result, output_dir: Path) -> Path:
    """Generate the ELSTER mapping files for the download buttons."""
    return export_elster_mapping(
        output_dir=output_dir,
        tax_year=result.tax_year,
        total_domestic_share_dividends=result.dividends.total_domestic_shares,
        total_foreign_share_dividends=result.dividends.total_foreign_shares,
        total_interest=result.interest.total,
        total_fund_dividends=result.dividends.total_funds,
        withholding_tax_summary=result.withholding_tax_summary,
        stock_gains=result.stock_sales.gains,
        stock_losses=result.stock_sales.losses,
        fund_dividends=result.dividends.funds,
        round_amount=result.config.round_amount,
    )
