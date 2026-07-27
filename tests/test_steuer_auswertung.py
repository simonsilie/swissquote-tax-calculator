import tempfile
import os
import subprocess
from pathlib import Path

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def test_basic_functionality_annual_mode() -> None:
    """Test basic functionality with annual mode (backward compatible)."""

    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
01-10-2025 16:58:38;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;33.82;0.00;0.00;33.82;748.30;USD
02-07-2025 17:50:13;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;69.47;0.00;0.00;69.47;714.48;USD
01-01-2025 12:15:04;00000000;Zinsen auf Einlagen;;;;1.0;0.88;0.00;0.00;0.88;1720.09;CHF
01-01-2025 08:44:32;00000000;Zinsen auf Einlagen;;;;1.0;0.73;0.00;0.00;0.73;607.85;USD
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as f:
        f.write(csv_content)
        csv_file_path = f.name

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "steuer-auswertung",
                csv_file_path,
                "--fx-usd",
                "1.0",
                "--fx-chf",
                "1.0",
                "--fx-eur",
                "1.0",
                "--no-details",
                "--fx-mode",
                "annual",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
        output = result.stdout

        assert "STEUERJAHR 2025" in output
        assert "Jahresdurchschnitt" in output

        expected_dividends = 146.96
        expected_zinsen = 1.61

        assert f"{expected_dividends:.2f} EUR" in output
        assert f"{expected_zinsen:.2f} EUR" in output

    finally:
        os.unlink(csv_file_path)


def test_basic_functionality_daily_mode() -> None:
    """Test basic functionality with daily mode (default)."""

    # Use a date where we can predict the fallback rate (2024-06-15)
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
15-06-2024 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;100.00;0.00;0.00;100.00;100.00;USD
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as f:
        f.write(csv_content)
        csv_file_path = f.name

    try:
        # Use daily mode with fallback rates (no API calls)
        result = subprocess.run(
            [
                "uv",
                "run",
                "steuer-auswertung",
                csv_file_path,
                "--fx-usd",
                "1.0825",  # 2024 fallback USD rate
                "--fx-chf",
                "0.9525",  # 2024 fallback CHF rate
                "--fx-eur",
                "1.0",
                "--no-details",
                # daily mode is default
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
        output = result.stdout

        assert "STEUERJAHR 2024" in output
        assert "Tageskurse" in output

        # 100 USD / 1.0825 = ~92.38 EUR
        expected_eur = round(100.0 / 1.0825, 2)
        assert f"{expected_eur:.2f} EUR" in output

    finally:
        os.unlink(csv_file_path)


def test_year_detection_multiple_years_error() -> None:
    """Test error when multiple years in CSV."""

    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
31-12-2024 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as f:
        f.write(csv_content)
        csv_file_path = f.name

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "steuer-auswertung",
                csv_file_path,
                "--fx-usd",
                "1.0",
                "--fx-chf",
                "1.0",
                "--fx-eur",
                "1.0",
                "--no-details",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        assert result.returncode != 0
        assert "Fehler: Transaktionen aus mehreren Jahren gefunden" in result.stderr
    finally:
        os.unlink(csv_file_path)


def test_missing_column_error() -> None:
    """Test error when required column is missing."""

    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as f:
        f.write(csv_content)
        csv_file_path = f.name

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "steuer-auswertung",
                csv_file_path,
                "--fx-usd",
                "1.0",
                "--fx-chf",
                "1.0",
                "--fx-eur",
                "1.0",
                "--no-details",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        assert result.returncode != 0
        assert "Fehler: Fehlende Spalten in CSV" in result.stderr
        assert "Währung" in result.stderr
    finally:
        os.unlink(csv_file_path)


def test_fx_mode_annual_flag() -> None:
    """Test that --fx-mode=annual works."""

    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;100.00;0.00;0.00;100.00;100.00;USD
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as f:
        f.write(csv_content)
        csv_file_path = f.name

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "steuer-auswertung",
                csv_file_path,
                "--fx-usd",
                "1.10",
                "--fx-chf",
                "0.95",
                "--fx-eur",
                "1.0",
                "--no-details",
                "--fx-mode",
                "annual",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
        output = result.stdout

        assert "Jahresdurchschnitt" in output
        # 100 USD / 1.10 = 90.91 EUR
        assert "90.91 EUR" in output

    finally:
        os.unlink(csv_file_path)


if __name__ == "__main__":
    # Allow running the test directly with python
    test_basic_functionality_annual_mode()
    test_basic_functionality_daily_mode()
    test_year_detection_multiple_years_error()
    test_missing_column_error()
    test_fx_mode_annual_flag()
    print("All tests passed!")
