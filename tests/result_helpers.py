"""Explicit calculation results for presentation tests, without running the pipeline."""

from datetime import datetime
from pathlib import Path

import polars as pl

from taxes.result import DividendSummary, InterestSummary, Result, StockSalesSummary
from taxes.service import TaxConfig
from taxes.withholding_tax import WithholdingTaxSummary


def sample_result(*, with_tax: bool = True, swiss: bool = False) -> Result:
    gross = 65.0 if swiss else 42.5
    tax_amount = 35.0 if swiss else 7.5
    total = gross + tax_amount if with_tax else 100.0
    country = "CH" if swiss else "US"
    tax = (
        WithholdingTaxSummary(
            foreign_creditable=15.0 if swiss else 7.5,
            foreign_excess=20.0 if swiss else 0.0,
            swiss_refundable=20.0 if swiss else 0.0,
            foreign_creditable_by_country=((country, 15.0 if swiss else 7.5),),
        )
        if with_tax
        else WithholdingTaxSummary()
    )
    transactions = pl.DataFrame(
        {
            "Datum": [datetime(2025, 12, 31, 15, 57, 9)],
            "Name": ["Example share"],
            "Transaktionen": ["Dividende"],
            "Nettobetrag": [gross if with_tax else total],
            "Währung": ["EUR"],
            "Nettobetrag_EUR": [gross if with_tax else total],
            "Bruttobetrag_EUR": [total],
            "Formular": ["Anlage KAP ausländisch" if with_tax else "Anlage KAP inländisch"],
            "Quellenstaat": [country if with_tax else "DE"],
            "Steuerbehandlung": ["foreign" if with_tax else "domestic"],
            "Anrechenbare_Quellensteuer_EUR": [tax.foreign_creditable],
            "Nicht_anrechenbare_Quellensteuer_EUR": [tax.foreign_excess],
            "Inlaendische_Kapitalertragsteuer_EUR": [0.0],
            "Solidaritaetszuschlag_EUR": [0.0],
            "Nicht_klassifizierte_Steuer_EUR": [0.0],
        }
    )
    if with_tax:
        transactions = transactions.with_columns(
            pl.lit(-tax_amount).alias("Kosten"), pl.lit(-tax_amount).alias("Quellensteuer_EUR")
        )
    empty = transactions.head(0)
    sales = pl.DataFrame(
        schema={
            "Datum": pl.Datetime,
            "ISIN": pl.String,
            "Anzahl": pl.Float64,
            "Verkaufserloes_EUR": pl.Float64,
            "Anschaffungskosten_EUR": pl.Float64,
            "Gewinn_Verlust_EUR": pl.Float64,
        }
    )
    return Result(
        tax_year=2025,
        config=TaxConfig(csv_file=Path("transactions.csv")),
        df=transactions,
        tax_year_df=transactions,
        dividends=DividendSummary(
            transactions=transactions,
            domestic_shares=empty if with_tax else transactions,
            foreign_shares=transactions if with_tax else empty,
            funds=empty,
            total_domestic_shares=0.0 if with_tax else total,
            total_foreign_shares=total if with_tax else 0.0,
            total_funds=0.0,
            tax_summary=tax,
        ),
        interest=InterestSummary(transactions=empty, total=0.0, tax_summary=WithholdingTaxSummary()),
        stock_sales=StockSalesSummary(transactions=sales, total=0.0, gains=0.0, losses=0.0),
        withholding_tax_transactions=empty,
        standalone_tax_summary=WithholdingTaxSummary(),
        withholding_tax_summary=tax,
    )
