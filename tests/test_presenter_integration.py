from pathlib import Path

import pytest

from taxes import fx_rates
from taxes.presenter import calculate, export_summary
from tests.fakes import write_fake_pdf
from tests.result_helpers import sample_result


def test_calculate_passes_the_app_options_to_the_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: exercise the app wrapper with a real CSV and an isolated cache path.
    csv_file = tmp_path / "transactions.csv"
    csv_file.write_text(
        "Datum;Transaktionen;Name;ISIN;Nettobetrag;Währung\n"
        "31-12-2025 15:57:09;Dividende;DE Aktie;DE0000000001;100.00;EUR\n",
        encoding="latin1",
    )
    monkeypatch.setattr(fx_rates, "CACHE_FILE", tmp_path / "fx_rates.json")

    # Act
    result = calculate(csv_file, tax_year=2025, round_amount=True)

    # Assert
    assert result.tax_year == 2025
    assert result.config.round_amount is True
    assert result.dividends.total_domestic_shares == pytest.approx(100.0)


def test_export_summary_writes_the_elster_markdown(tmp_path: Path) -> None:
    # Arrange
    result = sample_result()
    output_dir = tmp_path / "output"

    # Act
    md_path = export_summary(result, output_dir, pdf_renderer=write_fake_pdf)

    # Assert
    assert md_path == output_dir / "tax_summary_elster.md"
    content = md_path.read_text(encoding="utf-8")
    assert "Steuerjahr 2025" in content
    assert "7.50 EUR" in content
    assert md_path.with_suffix(".pdf").read_bytes().startswith(b"%PDF-FAKE\n")
