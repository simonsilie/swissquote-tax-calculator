from pathlib import Path

from taxes.service import TaxConfig
from tests.fakes import FakeFXRateFetcher


def test_rate_source_is_optional_until_calculation() -> None:
    # Arrange
    csv_file = Path("transactions.csv")
    fetcher = FakeFXRateFetcher({"USD": 2.0})

    # Act
    default_config = TaxConfig(csv_file=csv_file)
    injected_config = TaxConfig(csv_file=csv_file, fx_fetcher=fetcher)

    # Assert
    assert default_config.fx_fetcher is None
    assert injected_config.fx_fetcher is fetcher
