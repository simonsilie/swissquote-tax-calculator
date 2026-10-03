#!/usr/bin/env python3
import json
import os
import random
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional, Sequence
from urllib.error import URLError

from loguru import logger


FALLBACK_FX_RATES: dict[int, dict[str, float]] = {
    2025: {"USD": 1.05, "CHF": 0.93, "EUR": 1.00},
    2024: {"USD": 1.0825, "CHF": 0.9525, "EUR": 1.00},
    2023: {"USD": 1.0812, "CHF": 0.9718, "EUR": 1.00},
    2022: {"USD": 1.0534, "CHF": 1.0048, "EUR": 1.00},
    2021: {"USD": 1.1829, "CHF": 1.0811, "EUR": 1.00},
    2020: {"USD": 1.1421, "CHF": 1.0706, "EUR": 1.00},
}

DEFAULT_CURRENCIES: tuple[str, ...] = ("USD", "CHF", "EUR")
CACHE_DIR = Path.home() / ".cache" / "swissquote-tax"
CACHE_FILE = CACHE_DIR / "fx_rates.json"

# Retry configuration for transient API failures.
API_MAX_ATTEMPTS = 3
API_INITIAL_BACKOFF_SECONDS = 1.0
API_BACKOFF_MULTIPLIER = 2.0
API_REQUEST_TIMEOUT_SECONDS = 10

# HTTP status codes considered transient and worth retrying.
HTTP_REQUEST_TIMEOUT = 408
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERRORS_START = 500


def _is_retryable_http_error(error: urllib.error.HTTPError) -> bool:
    """Only server-side and rate-limit responses are worth retrying."""
    return (
        error.code >= HTTP_SERVER_ERRORS_START
        or error.code in (HTTP_REQUEST_TIMEOUT, HTTP_TOO_MANY_REQUESTS)
    )


def _fetch_with_retry(
    url: str,
    max_attempts: int = API_MAX_ATTEMPTS,
    initial_backoff: float = API_INITIAL_BACKOFF_SECONDS,
) -> Optional[dict[object, object]]:
    """GET a JSON document with exponential backoff and jitter.

    Retries transient failures (connection errors, timeouts, HTTP 408/429/5xx).
    Client errors (e.g. 404) and permanently malformed responses return None
    immediately. Returns None when all attempts are exhausted.
    """
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "Mozilla/5.0 (compatible; TaxScript/1.0)")

    backoff = initial_backoff
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        last_error = None
        try:
            with urllib.request.urlopen(request, timeout=API_REQUEST_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if not _is_retryable_http_error(e):
                logger.warning(f"Frankfurter API client error {e.code} for {url}: {e.reason}")
                return None
            last_error = e
        except (URLError, TimeoutError, OSError) as e:
            last_error = e
        except json.JSONDecodeError as e:
            # Malformed response bodies are often transient (truncated HTML
            # error pages from proxies), so they are retried as well.
            last_error = e

        if attempt < max_attempts:
            sleep_seconds = backoff + random.uniform(0, backoff / 2)
            logger.warning(
                f"Frankfurter API attempt {attempt}/{max_attempts} failed ({last_error}); "
                f"retrying in {sleep_seconds:.1f}s"
            )
            time.sleep(sleep_seconds)
            backoff *= API_BACKOFF_MULTIPLIER

    logger.warning(f"Frankfurter API failed after {max_attempts} attempts: {last_error}")
    return None


class DailyFXRateFetcher:
    """Fetches daily EUR exchange rates with caching and multi-tier fallback.

    Fallback chain: cached rate → Frankfurter daily API → hardcoded EZB approximate rates.
    """

    def __init__(self, cache_file: Optional[Path] = None) -> None:
        self.cache_file = cache_file or CACHE_FILE
        self._cache: dict[str, dict[str, float]] = {}
        self._offline = False
        raw = os.environ.get("SWISSQUOTE_TAX_OFFLINE", "")
        if raw.lower() in ("1", "true", "yes"):
            self._offline = True
        elif raw and raw.lower() not in ("0", "false", "no"):
            logger.warning(f"Invalid SWISSQUOTE_TAX_OFFLINE value '{raw}', treating as disabled")
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"Corrupted FX rate cache file '{self.cache_file}', starting fresh")
                self._cache = {}
            except OSError as e:
                logger.warning(f"Cannot read FX rate cache file '{self.cache_file}': {e}")
                self._cache = {}

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self.cache_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
            tmp_file.replace(self.cache_file)
        except OSError as e:
            logger.warning(f"Failed to save FX rate cache: {e}")

    def _fetch_daily_from_api(self, target_date: date, currencies: Sequence[str]) -> Optional[dict[str, float]]:
        date_str = target_date.isoformat()
        currency_param = ",".join(currencies)
        url = f"https://api.frankfurter.dev/v1/{date_str}?from=EUR&to={currency_param}"
        data = _fetch_with_retry(url)
        if data is None:
            return None

        rates = data.get("rates")
        if not isinstance(rates, dict):
            logger.warning(f"Frankfurter API response missing 'rates' key for {date_str}")
            return None

        day_rates = rates.get(date_str, rates)
        if not isinstance(day_rates, dict):
            logger.warning(f"Frankfurter API returned unexpected rate shape for {date_str}")
            return None
        result: dict[str, float] = {"EUR": 1.00}
        for curr in currencies:
            if curr in day_rates:
                result[curr] = round(day_rates[curr], 4)
        if len(result) == 1:
            logger.warning(
                f"Frankfurter API returned no requested currencies for {date_str} (found keys: {sorted(day_rates.keys())})",
            )
            return None
        return result

    def get_fallback_rates(self, year: int) -> dict[str, float]:
        if year not in FALLBACK_FX_RATES:
            raise KeyError(f"No fallback FX rates for year {year}")
        return FALLBACK_FX_RATES[year]

    def get_rate(self, target_date: date, currency: str) -> float:
        if currency == "EUR":
            return 1.0

        if self._offline:
            rate = self.get_fallback_rates(target_date.year).get(currency)
            if rate is None:
                logger.warning(
                    f"Unknown currency '{currency}' for {target_date} — no fallback rate, assuming 1:1",
                )
                return 1.0
            return rate

        date_str = target_date.isoformat()
        year = target_date.year

        if date_str in self._cache and currency in self._cache[date_str]:
            return self._cache[date_str][currency]

        daily_rates = self._fetch_daily_from_api(target_date, DEFAULT_CURRENCIES)
        if daily_rates:
            self._cache[date_str] = daily_rates
            self._save_cache()
            if currency in daily_rates:
                return daily_rates[currency]

        fallback = self.get_fallback_rates(year)
        if date_str not in self._cache:
            self._cache[date_str] = {}
        rate = fallback.get(currency)
        if rate is None:
            logger.warning(
                f"Unknown currency '{currency}' for {date_str} — no fallback rate, assuming 1:1",
            )
            return 1.0
        self._cache[date_str][currency] = rate
        self._save_cache()
        return rate

    def get_rates_for_date(self, target_date: date) -> dict[str, float]:
        result = {}
        for curr in DEFAULT_CURRENCIES:
            result[curr] = self.get_rate(target_date, curr)
        return result

    @staticmethod
    def clear_cache(cache_file: Optional[Path] = None) -> bool:
        """Delete the FX rate cache file. Returns True if deleted, False if it did not exist."""
        path = cache_file or CACHE_FILE
        if not path.exists():
            return False
        path.unlink()
        return True
