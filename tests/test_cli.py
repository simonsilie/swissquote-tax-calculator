from tests.cli_test_helpers import run_cli


def test_basic_functionality_annual_mode() -> None:
    """Annual mode reports dividend and interest totals."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
01-10-2025 16:58:38;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;33.82;0.00;0.00;33.82;748.30;USD
02-07-2025 17:50:13;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;69.47;0.00;0.00;69.47;714.48;USD
01-01-2025 12:15:04;00000000;Zinsen auf Einlagen;;;;1.0;0.88;0.00;0.00;0.88;1720.09;CHF
01-01-2025 08:44:32;00000000;Zinsen auf Einlagen;;;;1.0;0.73;0.00;0.00;0.73;607.85;USD
"""

    result = run_cli(
        csv_content,
        ["--fx-usd", "1.0", "--fx-chf", "1.0", "--fx-eur", "1.0", "--no-details", "--fx-mode", "annual"],
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "STEUERJAHR 2025" in result.stdout
    assert "Jahresdurchschnitt" in result.stdout
    assert "146.96 EUR" in result.stdout
    assert "1.61 EUR" in result.stdout


def test_basic_functionality_daily_mode() -> None:
    """Daily mode uses the configured conversion rate."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
15-06-2024 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;100.00;0.00;0.00;100.00;100.00;USD
"""

    result = run_cli(
        csv_content,
        ["--fx-usd", "1.0825", "--fx-chf", "0.9525", "--fx-eur", "1.0", "--no-details"],
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "STEUERJAHR 2024" in result.stdout
    assert "Tageskurse" in result.stdout
    assert "92.38 EUR" in result.stdout
    assert "Keine Eintragung für Aktienverkäufe" in result.stdout


def test_environment_variables_configure_the_cli() -> None:
    """Environment variables provide the same settings as command-line options."""
    csv_content = """Datum;Transaktionen;Name;Nettobetrag;Währung
31-12-2025 15:57:09;Dividende;US ETF;100.00;USD
"""

    result = run_cli(
        csv_content,
        ["--no-details"],
        environment={
            "SWISSQUOTE_TAX_FX_MODE": "annual",
            "SWISSQUOTE_TAX_FX_USD": "1.0",
            "SWISSQUOTE_TAX_FX_CHF": "1.0",
            "SWISSQUOTE_TAX_FX_EUR": "1.0",
        },
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Jahresdurchschnitt" in result.stdout
    assert "100.00 EUR" in result.stdout


def test_multiple_years_require_an_explicit_tax_year() -> None:
    """A historical CSV needs --tax-year to identify the requested report."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
31-12-2024 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
"""

    result = run_cli(csv_content, ["--fx-usd", "1.0", "--fx-chf", "1.0", "--fx-eur", "1.0", "--no-details"])

    assert result.returncode != 0
    assert "Fehler: Transaktionen aus mehreren Jahren gefunden" in result.stderr


def test_missing_required_column_is_reported() -> None:
    """The CLI reports a missing required CSV column."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97
"""

    result = run_cli(csv_content, ["--fx-usd", "1.0", "--fx-chf", "1.0", "--fx-eur", "1.0", "--no-details"])

    assert result.returncode != 0
    assert "Fehler: Fehlende Spalten in CSV" in result.stderr
    assert "Währung" in result.stderr


def test_annual_fx_mode_uses_configured_rate() -> None:
    """Annual mode applies a manual EUR/USD rate."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;100.00;0.00;0.00;100.00;100.00;USD
"""

    result = run_cli(
        csv_content,
        ["--fx-usd", "1.10", "--fx-chf", "0.95", "--fx-eur", "1.0", "--no-details", "--fx-mode", "annual"],
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Jahresdurchschnitt" in result.stdout
    assert "90.91 EUR" in result.stdout


def test_withholding_tax_is_converted_and_reported() -> None:
    """The Swissquote Kosten column is converted and reported as withholding tax."""
    csv_content = """Datum;Transaktionen;Name;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;US ETF;85.00;-15.00;USD
01-01-2025 12:15:04;Zinsen auf Einlagen;CHF Konto;6.50;-3.50;CHF
"""

    result = run_cli(
        csv_content,
        ["--fx-usd", "1.0", "--fx-chf", "1.0", "--fx-eur", "1.0", "--no-details", "--fx-mode", "annual"],
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "3. Anlage KAP (Zeile 41 - Anrechenbare ausländische Steuern): 18.50 EUR" in result.stdout
    assert "Davon Quellensteuer auf Dividenden: 15.00 EUR" in result.stdout
    assert "Davon Quellensteuer auf Zinsen: 3.50 EUR" in result.stdout


def test_separate_withholding_tax_transaction_is_reported() -> None:
    """Separate withholding-tax bookings are converted and included in KAP line 41."""
    csv_content = """Datum;Transaktionen;Name;Nettobetrag;Währung
31-12-2025 15:57:09;Dividende;US ETF;85.00;USD
31-12-2025 15:57:09;Withholding Tax;US ETF;-15.00;USD
"""

    result = run_cli(
        csv_content,
        ["--fx-usd", "1.0", "--fx-chf", "1.0", "--fx-eur", "1.0", "--no-details", "--fx-mode", "annual"],
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "3. Anlage KAP (Zeile 41 - Anrechenbare ausländische Steuern): 15.00 EUR" in result.stdout
    assert "Davon separate Quellensteuer-Buchungen: 15.00 EUR" in result.stdout
