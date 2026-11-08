"""Small in-memory implementations of external FX boundaries."""

from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path

from taxes.fx_rates import API_REQUEST_TIMEOUT_SECONDS


class MemoryFXRateCache:
    def __init__(self, rates: dict[str, dict[str, float]] | None = None) -> None:
        self.rates = deepcopy(rates) if rates is not None else {}

    def load(self) -> dict[str, dict[str, float]]:
        return deepcopy(self.rates)

    def save(self, rates: dict[str, dict[str, float]]) -> None:
        self.rates = deepcopy(rates)


class FakeJsonAPI:
    def __init__(self, *responses: dict[object, object] | None) -> None:
        self.responses = list(responses)

    def __call__(self, url: str) -> dict[object, object] | None:
        if not url.startswith("https://api.frankfurter.dev/v1/"):
            raise AssertionError(f"Unexpected API URL: {url}")
        if not self.responses:
            raise AssertionError("Unexpected API request")
        return self.responses.pop(0)


class FakeUrlOpener:
    def __init__(self, *responses: bytes | Exception) -> None:
        self.responses = list(responses)

    def __call__(self, request: object, timeout: float) -> BytesIO:
        if timeout != API_REQUEST_TIMEOUT_SECONDS:
            raise AssertionError(f"Unexpected timeout: {timeout}")
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return BytesIO(response)


class FakeFXRateFetcher:
    def __init__(self, rates: dict[str, float]) -> None:
        self.rates = rates

    def get_rate(self, target_date: date, currency: str) -> float:
        return 1.0 if currency == "EUR" else self.rates[currency]


def write_fake_pdf(html_content: str, pdf_path: Path) -> None:
    """Stand in for the native renderer while exercising the export's file output."""
    pdf_path.write_bytes(b"%PDF-FAKE\n" + html_content.encode("utf-8"))
