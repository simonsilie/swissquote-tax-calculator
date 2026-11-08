import json
from datetime import date
from pathlib import Path

from taxes.fx_rates import DailyFXRateFetcher, JsonFXRateCache
from tests.fakes import FakeJsonAPI


def test_daily_rates_survive_a_new_fetcher(tmp_path: Path) -> None:
    # Arrange
    cache_file = tmp_path / "cache" / "fx_rates.json"
    fetcher = DailyFXRateFetcher(
        cache_file=cache_file, fetch_json=FakeJsonAPI({"rates": {"USD": 1.09, "CHF": 0.94}}), offline=False
    )
    fetcher.get_rates_for_date(date(2024, 6, 15))

    # Act
    second = DailyFXRateFetcher(cache_file=cache_file, fetch_json=FakeJsonAPI(), offline=False)
    rates = second.get_rates_for_date(date(2024, 6, 15))

    # Assert
    assert rates == {"USD": 1.09, "CHF": 0.94, "EUR": 1.0}
    assert json.loads(cache_file.read_text(encoding="utf-8")) == {"2024-06-15": rates}
    assert not cache_file.with_suffix(".tmp").exists()


def test_fallback_is_not_written_to_disk(tmp_path: Path) -> None:
    # Arrange
    cache_file = tmp_path / "fx_rates.json"
    fetcher = DailyFXRateFetcher(cache_file=cache_file, fetch_json=FakeJsonAPI(None), offline=False)

    # Act
    rate = fetcher.get_rate(date(2025, 6, 2), "USD")

    # Assert
    assert rate == 1.05
    assert not cache_file.exists()


def test_corrupt_cache_starts_empty(tmp_path: Path) -> None:
    # Arrange
    cache_file = tmp_path / "fx_rates.json"
    cache_file.write_text("{truncated", encoding="utf-8")
    cache = JsonFXRateCache(cache_file)

    # Act
    rates = cache.load()

    # Assert
    assert rates == {}


def test_clear_cache_removes_only_the_given_file(tmp_path: Path) -> None:
    # Arrange
    cache_file = tmp_path / "fx_rates.json"
    cache_file.write_text("{}", encoding="utf-8")

    # Act
    removed = DailyFXRateFetcher.clear_cache(cache_file)
    removed_again = DailyFXRateFetcher.clear_cache(cache_file)

    # Assert
    assert removed is True
    assert removed_again is False
    assert not cache_file.exists()
