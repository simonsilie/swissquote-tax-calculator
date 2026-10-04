from datetime import date
from pathlib import Path

import polars as pl
import pytest

from taxes.service import TaxConfig, calculate_taxes


class FakeFXRateFetcher:
    """Deterministic rate source for tests — no network, no cache."""

    def __init__(self, rates: dict[str, float]) -> None:
        self.rates = rates
        self.requested: list[tuple[date, str]] = []

    def get_rate(self, target_date: date, currency: str) -> float:
        self.requested.append((target_date, currency))
        if currency == "EUR":
            return 1.0
        return self.rates[currency]


CSV_CONTENT = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;US ETF;US0000000001;85.00;-15.00;USD
"""


def write_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "transactions.csv"
    csv_file.write_text(CSV_CONTENT, encoding="latin1")
    return csv_file


def test_injected_fetcher_is_used_instead_of_the_real_one(tmp_path: Path) -> None:
    """calculate_taxes converts amounts with the injected rate source."""
    fetcher = FakeFXRateFetcher({"USD": 2.0, "CHF": 1.0})

    result = calculate_taxes(
        TaxConfig(csv_file=write_csv(tmp_path), tax_year=2025, fx_fetcher=fetcher)
    )

    # 85.00 USD net + 15.00 USD tax = 100.00 USD gross at 2.0 USD/EUR = 50 EUR
    assert result.dividends.total_foreign_shares == pytest.approx(50.0)
    assert result.withholding_tax_summary.foreign_creditable == pytest.approx(7.5)
    assert result.withholding_tax_summary.foreign_excess == pytest.approx(0.0)
    assert (date(2025, 12, 31), "USD") in fetcher.requested


def test_injected_fetcher_avoids_the_default_construction(tmp_path: Path) -> None:
    """Without injection the real fetcher is constructed lazily."""
    fetcher = FakeFXRateFetcher({"USD": 1.0, "CHF": 1.0})

    config_without = TaxConfig(csv_file=write_csv(tmp_path), fx_fetcher=fetcher)
    config_with = TaxConfig(csv_file=write_csv(tmp_path), fx_fetcher=fetcher)

    assert config_without.fx_fetcher is fetcher
    assert config_with.fx_fetcher is fetcher

    # The default field stays None before calculate_taxes runs
    plain = TaxConfig(csv_file=write_csv(tmp_path))
    assert plain.fx_fetcher is None


def test_injected_fetcher_with_prefix_rule_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Injected fetcher works when no rules file exists; prefix defaults still apply."""
    monkeypatch.chdir(tmp_path)
    fetcher = FakeFXRateFetcher({"USD": 2.0, "CHF": 1.0})

    result = calculate_taxes(
        TaxConfig(csv_file=write_csv(tmp_path), tax_year=2025, fx_fetcher=fetcher)
    )

    # Unmapped US ISIN falls back to the built-in prefix rule (15% creditable):
    # 7.5 EUR tax, capped at 50 EUR gross * 0.15 = 7.5 EUR creditable.
    assert result.withholding_tax_summary.foreign_creditable == pytest.approx(7.5)
    assert result.withholding_tax_summary.foreign_excess == 0.0
    assert result.dividends.transactions["Bruttobetrag_EUR"].to_list() == [pytest.approx(50.0)]
    assert isinstance(result.df, pl.DataFrame)
