import json
import tempfile
from pathlib import Path
from datetime import date
from unittest.mock import patch


# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def test_daily_fx_rate_fetcher_cache() -> None:
    """Test that DailyFXRateFetcher caches rates correctly."""
    from taxes.fx_rates import DailyFXRateFetcher

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "fx_rates.json"
        fetcher = DailyFXRateFetcher(cache_file=cache_file)

        # Test EUR rate is always 1.0
        assert fetcher.get_rate(date(2024, 1, 15), "EUR") == 1.0

        # Test fallback rates for unknown dates (mock daily API to fail)
        with patch.object(fetcher, "_fetch_daily_from_api", return_value=None):
            with patch.object(fetcher, "_fetch_annual_from_api", return_value=None):
                rate = fetcher.get_rate(date(2020, 1, 1), "USD")
                assert rate == 1.1421  # fallback for 2020

        # Test cache file was created
        assert cache_file.exists()
        with open(cache_file) as f:
            cache = json.load(f)
        assert "2020-01-01" in cache
        assert cache["2020-01-01"]["USD"] == 1.1421


def test_daily_fx_rate_fetcher_fallback_chain() -> None:
    """Test the fallback chain: daily API -> annual API -> fallback table."""
    from taxes.fx_rates import DailyFXRateFetcher

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "fx_rates.json"
        fetcher = DailyFXRateFetcher(cache_file=cache_file)

        # Mock the daily API to fail, annual API to fail, should use fallback
        with patch.object(fetcher, "_fetch_daily_from_api", return_value=None):
            with patch.object(fetcher, "_fetch_annual_from_api", return_value=None):
                rate = fetcher.get_rate(date(2024, 6, 15), "USD")
                assert rate == 1.0825  # 2024 fallback


def test_daily_fx_rate_fetcher_annual_fallback() -> None:
    """Test that annual API is used when daily API fails."""
    from taxes.fx_rates import DailyFXRateFetcher

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "fx_rates.json"
        fetcher = DailyFXRateFetcher(cache_file=cache_file)

        # Mock daily API to fail, annual API to succeed
        with patch.object(fetcher, "_fetch_daily_from_api", return_value=None):
            with patch.object(fetcher, "_fetch_annual_from_api", return_value={"USD": 1.10, "CHF": 0.96, "EUR": 1.0}):
                rate = fetcher.get_rate(date(2024, 6, 15), "USD")
                assert rate == 1.10


def test_daily_fx_rate_fetcher_daily_api_success() -> None:
    """Test that daily API rate is used when available."""
    from taxes.fx_rates import DailyFXRateFetcher

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "fx_rates.json"
        fetcher = DailyFXRateFetcher(cache_file=cache_file)

        # Mock daily API to succeed
        with patch.object(fetcher, "_fetch_daily_from_api", return_value={"USD": 1.09, "CHF": 0.94, "EUR": 1.0}):
            rate = fetcher.get_rate(date(2024, 6, 15), "USD")
            assert rate == 1.09


def test_fetch_daily_from_api_parses_single_date_response() -> None:
    """Test Frankfurter's direct rate shape for a single-date query."""
    from taxes.fx_rates import DailyFXRateFetcher

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"amount":1.0,"base":"EUR","date":"2025-01-15","rates":{"CHF":0.9394,"USD":1.03}}'

    with tempfile.TemporaryDirectory() as tmpdir:
        fetcher = DailyFXRateFetcher(cache_file=Path(tmpdir) / "fx_rates.json")
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            rates = fetcher._fetch_daily_from_api(date(2025, 1, 15), ["USD", "CHF", "EUR"])

    assert rates == {"EUR": 1.0, "USD": 1.03, "CHF": 0.9394}


def test_get_rates_for_date() -> None:
    """Test get_rates_for_date returns all currencies."""
    from taxes.fx_rates import DailyFXRateFetcher

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "fx_rates.json"
        fetcher = DailyFXRateFetcher(cache_file=cache_file)

        with patch.object(fetcher, "_fetch_daily_from_api", return_value={"USD": 1.09, "CHF": 0.94, "EUR": 1.0}):
            rates = fetcher.get_rates_for_date(date(2024, 6, 15))
            assert rates["USD"] == 1.09
            assert rates["CHF"] == 0.94
            assert rates["EUR"] == 1.0


if __name__ == "__main__":
    # Allow running the test directly with python
    test_daily_fx_rate_fetcher_cache()
    test_daily_fx_rate_fetcher_fallback_chain()
    test_daily_fx_rate_fetcher_annual_fallback()
    test_daily_fx_rate_fetcher_daily_api_success()
    test_fetch_daily_from_api_parses_single_date_response()
    test_get_rates_for_date()
    print("All tests passed!")
