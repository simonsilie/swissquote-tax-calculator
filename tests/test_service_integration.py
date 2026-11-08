from pathlib import Path

import polars as pl
import pytest

from taxes.service import TaxConfig, calculate_taxes
from tests.fakes import FakeFXRateFetcher


CSV_CONTENT = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;US ETF;US0000000001;85.00;-15.00;USD
"""

FUND_SALE_CSV_CONTENT = """Datum;Transaktionen;Name;ISIN;Anzahl;Nettobetrag;Kosten;Währung
01-01-2025 09:00:00;Kauf;World ETF;IE00B3RBWM25;10.0;-1000.00;0.00;EUR
01-03-2025 09:00:00;Verkauf;World ETF;IE00B3RBWM25;10.0;1200.00;0.00;EUR
"""

FUND_RULES_TOML = """[[security]]
isin = "IE00B3RBWM25"
source_country = "IE"
tax_treatment = "foreign"
max_creditable_rate = 0.0
instrument = "fund"
"""


def write_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "transactions.csv"
    csv_file.write_text(CSV_CONTENT, encoding="latin1")
    return csv_file


def test_local_rules_are_loaded_with_an_injected_rate_source(tmp_path: Path) -> None:
    """calculate_taxes converts amounts with the injected rate source."""
    # Arrange
    (tmp_path / "withholding-tax-rules.toml").write_text(
        '[[country]]\nisin_prefix = "US"\nsource_country = "US"\n'
        'tax_treatment = "foreign"\nmax_creditable_rate = 0.15\n',
        encoding="utf-8",
    )
    fetcher = FakeFXRateFetcher({"USD": 2.0, "CHF": 1.0})
    config = TaxConfig(csv_file=write_csv(tmp_path), tax_year=2025, fx_fetcher=fetcher)

    # Act
    result = calculate_taxes(config)

    # Assert
    # 85.00 USD net + 15.00 USD tax = 100.00 USD gross at 2.0 USD/EUR = 50 EUR
    assert result.dividends.total_foreign_shares == pytest.approx(50.0)
    assert result.withholding_tax_summary.foreign_creditable == pytest.approx(7.5)
    assert result.withholding_tax_summary.unclassified == pytest.approx(0.0)


def test_unmapped_isin_tax_is_not_credited_without_a_rule(tmp_path: Path) -> None:
    """Without any rules file, an unmapped ISIN's tax stays unclassified, not creditable."""
    # Arrange
    fetcher = FakeFXRateFetcher({"USD": 2.0, "CHF": 1.0})
    config = TaxConfig(csv_file=write_csv(tmp_path), tax_year=2025, fx_fetcher=fetcher)

    # Act
    result = calculate_taxes(config)

    # Assert
    # Unmapped US ISIN without a rule: tax is not creditable towards line 41.
    assert result.withholding_tax_summary.foreign_creditable == pytest.approx(0.0)
    assert result.withholding_tax_summary.unclassified == pytest.approx(7.5)
    assert result.dividends.transactions["Bruttobetrag_EUR"].to_list() == [pytest.approx(50.0)]
    assert isinstance(result.df, pl.DataFrame)


def test_fund_sales_are_not_reported_as_stock_sales(tmp_path: Path) -> None:
    """Sales of securities flagged ``instrument = "fund"`` abort instead of misreporting."""
    csv_file = tmp_path / "transactions.csv"
    csv_file.write_text(FUND_SALE_CSV_CONTENT, encoding="latin1")
    rules_file = tmp_path / "withholding-tax-rules.toml"
    rules_file.write_text(FUND_RULES_TOML, encoding="utf-8")

    with pytest.raises(ValueError, match="IE00B3RBWM25"):
        calculate_taxes(
            TaxConfig(
                csv_file=csv_file,
                tax_year=2025,
                fx_fetcher=FakeFXRateFetcher({"USD": 1.0}),
                withholding_tax_rules_path=rules_file,
            )
        )
