import tempfile
import os
import subprocess
from pathlib import Path

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def test_basic_functionality() -> None:
    # Create a temporary CSV file with known data
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
01-10-2025 16:58:38;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;33.82;0.00;0.00;33.82;748.30;USD
02-07-2025 17:50:13;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;69.47;0.00;0.00;69.47;714.48;USD
01-01-2025 12:15:04;00000000;Zinsen auf Einlagen;;;;1.0;0.88;0.00;0.00;0.88;1720.09;CHF
01-01-2025 08:44:32;00000000;Zinsen auf Einlagen;;;;1.0;0.73;0.00;0.00;0.73;607.85;USD
"""
    # Write to a temporary file in latin1 encoding
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as f:
        f.write(csv_content)
        csv_file_path = f.name

    try:
        # Run the script with fixed FX rates (1.0 for simplicity) and no details
        # We use uv run to ensure we use the virtual environment
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

        # Check that the script ran successfully
        assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"

        # Parse the output
        output = result.stdout

        # We expect the year to be detected as 2025
        assert "STEUERJAHR 2025" in output

        # With FX rates 1.0, the EUR amounts equal the Nettobetrag
        # Dividends: 43.67 + 33.82 + 69.47 = 146.96
        # Zinsen: 0.88 (CHF) + 0.73 (USD) = 1.61
        # Since we set FX rates to 1.0, we treat CHF and USD as 1:1 to EUR
        # So expected sums:
        expected_dividends = 146.96
        expected_zinsen = 1.61

        # Check that the output contains these values (formatted to two decimals)
        # The script prints: "1. Anlage KAP-INV (Zeile 4 - ETF-Ausschüttungen): 146.96 EUR"
        # and "2. Anlage KAP (Zeile 19 - Ausländische Zinsen):   1.61 EUR"
        assert f"{expected_dividends:.2f} EUR" in output
        assert f"{expected_zinsen:.2f} EUR" in output

        # Also check that the lines are present
        assert f"1. Anlage KAP-INV (Zeile 4 - ETF-Ausschüttungen): {expected_dividends:.2f} EUR" in output
        assert f"2. Anlage KAP (Zeile 19 - Ausländische Zinsen):   {expected_zinsen:.2f} EUR" in output

    finally:
        # Clean up the temporary file
        os.unlink(csv_file_path)


def test_year_detection_multiple_years_error() -> None:
    # Create a CSV with two different years
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

        # Should exit with error due to multiple years
        assert result.returncode != 0
        assert "Fehler: Transaktionen aus mehreren Jahren gefunden" in result.stderr
    finally:
        os.unlink(csv_file_path)


def test_missing_column_error() -> None:
    # Create a CSV missing a required column
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

        # Should exit with error due to missing Währung column
        assert result.returncode != 0
        assert "Fehler: Fehlende Spalten in CSV" in result.stderr
        assert "Währung" in result.stderr
    finally:
        os.unlink(csv_file_path)


if __name__ == "__main__":
    # Allow running the test directly with python
    test_basic_functionality()
    test_year_detection_multiple_years_error()
    test_missing_column_error()
    print("All tests passed!")
