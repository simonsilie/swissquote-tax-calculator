from datetime import date
from email.message import Message
from random import Random
from urllib.error import HTTPError, URLError

import pytest

from taxes.fx_rates import DailyFXRateFetcher, _fetch_with_retry
from tests.fakes import FakeJsonAPI, FakeUrlOpener, MemoryFXRateCache


def test_eur_rate_needs_no_api_request() -> None:
    # Arrange
    fetcher = DailyFXRateFetcher(cache=MemoryFXRateCache(), fetch_json=FakeJsonAPI(), offline=False)

    # Act
    rate = fetcher.get_rate(date(2024, 1, 15), "EUR")

    # Assert
    assert rate == 1.0


def test_daily_rates_are_persisted_and_reused() -> None:
    # Arrange
    cache = MemoryFXRateCache()
    fetcher = DailyFXRateFetcher(
        cache=cache, fetch_json=FakeJsonAPI({"rates": {"USD": 1.09, "CHF": 0.94}}), offline=False
    )

    # Act
    rates = fetcher.get_rates_for_date(date(2024, 6, 15))
    cached = DailyFXRateFetcher(cache=cache, fetch_json=FakeJsonAPI(), offline=False)
    reloaded_rates = cached.get_rates_for_date(date(2024, 6, 15))

    # Assert
    assert rates == {"USD": 1.09, "CHF": 0.94, "EUR": 1.0}
    assert reloaded_rates == rates
    assert cache.rates == {"2024-06-15": rates}


@pytest.mark.parametrize(("year", "expected"), [(2020, 1.1421), (2024, 1.0825)])
def test_fallback_rates_stay_out_of_persistent_cache(year: int, expected: float) -> None:
    # Arrange
    cache = MemoryFXRateCache()
    fetcher = DailyFXRateFetcher(cache=cache, fetch_json=FakeJsonAPI(None), offline=False)

    # Act
    rate = fetcher.get_rate(date(year, 1, 1), "USD")
    repeated_rate = fetcher.get_rate(date(year, 1, 1), "USD")

    # Assert
    assert rate == expected
    assert repeated_rate == expected
    assert cache.rates == {}


def test_fallback_rate_does_not_block_a_later_api_request() -> None:
    # Arrange
    cache = MemoryFXRateCache()
    first = DailyFXRateFetcher(cache=cache, fetch_json=FakeJsonAPI(None), offline=False)
    first.get_rate(date(2025, 6, 2), "USD")
    second = DailyFXRateFetcher(
        cache=cache, fetch_json=FakeJsonAPI({"rates": {"USD": 1.0801, "CHF": 0.94}}), offline=False
    )

    # Act
    rate = second.get_rate(date(2025, 6, 2), "USD")

    # Assert
    assert rate == 1.0801
    assert cache.rates["2025-06-02"]["USD"] == 1.0801


@pytest.mark.parametrize(
    "response",
    [
        {"rates": {"CHF": 0.9394, "USD": 1.03}},
        {"rates": {"2025-01-15": {"CHF": 0.9394, "USD": 1.03}}},
    ],
)
def test_daily_api_response_shapes(response: dict[object, object]) -> None:
    # Arrange
    fetcher = DailyFXRateFetcher(cache=MemoryFXRateCache(), fetch_json=FakeJsonAPI(response), offline=False)

    # Act
    rates = fetcher.get_rates_for_date(date(2025, 1, 15))

    # Assert
    assert rates == {"EUR": 1.0, "USD": 1.03, "CHF": 0.9394}


@pytest.mark.parametrize("response", [{}, {"rates": []}, {"rates": {"JPY": 150.0}}])
def test_unusable_api_responses_use_fallback(response: dict[object, object]) -> None:
    # Arrange
    cache = MemoryFXRateCache()
    fetcher = DailyFXRateFetcher(cache=cache, fetch_json=FakeJsonAPI(response), offline=False)

    # Act
    rate = fetcher.get_rate(date(2025, 1, 15), "USD")

    # Assert
    assert rate == 1.05
    assert cache.rates == {}


def test_offline_mode_uses_fallback_even_with_cached_daily_rates() -> None:
    # Arrange
    fetcher = DailyFXRateFetcher(
        cache=MemoryFXRateCache({"2025-01-15": {"USD": 1.10}}), fetch_json=FakeJsonAPI(), offline=True
    )

    # Act
    rate = fetcher.get_rate(date(2025, 1, 15), "USD")

    # Assert
    assert rate == 1.05


def test_fetch_with_retry_succeeds_after_transient_failures() -> None:
    # Arrange
    opener = FakeUrlOpener(URLError("connection reset"), b"{truncated", b'{"rates": {"USD": 1.05}}')
    delays: list[float] = []
    random = Random(0)
    expected_random = Random(0)

    # Act
    data = _fetch_with_retry(
        "https://api.frankfurter.dev/v1/2025-01-15",
        open_url=opener,
        sleep=delays.append,
        jitter=random.uniform,
    )

    # Assert
    assert data == {"rates": {"USD": 1.05}}
    assert delays == [1.0 + expected_random.uniform(0, 0.5), 2.0 + expected_random.uniform(0, 1.0)]


@pytest.mark.parametrize("status", [None, 408, 429, 503])
def test_fetch_with_retry_gives_up_after_max_attempts(status: int | None) -> None:
    # Arrange
    error = (
        URLError("network down")
        if status is None
        else HTTPError("https://example.test", status, "error", Message(), None)
    )
    opener = FakeUrlOpener(error, error, error)
    delays: list[float] = []

    # Act
    data = _fetch_with_retry(
        "https://api.frankfurter.dev/v1/2025-01-15",
        max_attempts=3,
        open_url=opener,
        sleep=delays.append,
        jitter=Random(0).uniform,
    )

    # Assert
    assert data is None
    assert len(delays) == 2
    assert 1.0 <= delays[0] <= 1.5
    assert 2.0 <= delays[1] <= 3.0


def test_fetch_with_retry_does_not_retry_client_errors() -> None:
    # Arrange
    error = HTTPError("https://example.test", 404, "Not Found", Message(), None)
    # A second response would succeed if the client error were incorrectly retried.
    opener = FakeUrlOpener(error, b'{"rates": {"USD": 1.05}}')
    delays: list[float] = []

    # Act
    data = _fetch_with_retry(
        "https://api.frankfurter.dev/v1/2025-01-15",
        open_url=opener,
        sleep=delays.append,
        jitter=Random(0).uniform,
    )

    # Assert
    assert data is None
    assert delays == []
