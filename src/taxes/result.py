"""Typed results of a tax calculation run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from taxes.withholding_tax import WithholdingTaxSummary

if TYPE_CHECKING:
    from taxes.service import TaxConfig


@dataclass(frozen=True)
class DividendSummary:
    """Dividend income grouped by the German tax form it is reported on.

    ``transactions`` holds every dividend of the tax year including the
    ``Formular`` and ``Fundart`` tag columns. The three frames split it by
    form: domestic shares (Anlage KAP inländisch), foreign shares (Anlage
    KAP ausländisch), and funds/ETFs (Anlage KAP-INV). ``tax_summary``
    contains the withholding tax embedded in the dividend rows.
    """

    transactions: pl.DataFrame
    domestic_shares: pl.DataFrame
    foreign_shares: pl.DataFrame
    funds: pl.DataFrame
    total_domestic_shares: float
    total_foreign_shares: float
    total_funds: float
    tax_summary: WithholdingTaxSummary


@dataclass(frozen=True)
class InterestSummary:
    """Interest income of the tax year with its embedded withholding tax."""

    transactions: pl.DataFrame
    total: float
    tax_summary: WithholdingTaxSummary


@dataclass(frozen=True)
class StockSalesSummary:
    """Realized stock sales (FIFO) of the tax year, split into gains and losses."""

    transactions: pl.DataFrame
    total: float
    gains: float
    losses: float


@dataclass(frozen=True)
class Result:
    """Outcome of ``calculate_taxes`` for a single tax year.

    Income categories are grouped into dedicated summaries; standalone
    withholding-tax bookings stay on the result because they belong to no
    income category. ``config`` echoes the configuration that produced the
    result so display code can address the transaction columns.
    """

    tax_year: int
    config: TaxConfig
    df: pl.DataFrame
    tax_year_df: pl.DataFrame
    dividends: DividendSummary
    interest: InterestSummary
    stock_sales: StockSalesSummary
    withholding_tax_transactions: pl.DataFrame
    standalone_tax_summary: WithholdingTaxSummary
    withholding_tax_summary: WithholdingTaxSummary
