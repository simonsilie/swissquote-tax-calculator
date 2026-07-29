from tests.cli_test_helpers import run_cli


OFFLINE = {"SWISSQUOTE_TAX_OFFLINE": "true"}


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
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "STEUERJAHR 2025" in result.stdout
    assert "Jahresdurchschnitt" in result.stdout
    assert "139.96 EUR" in result.stdout
    assert "1.64 EUR" in result.stdout


def test_basic_functionality_daily_mode() -> None:
    """Daily mode uses fallback rates when offline."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
15-06-2024 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;100.00;0.00;0.00;100.00;100.00;USD
"""

    result = run_cli(
        csv_content,
        ["--no-details"],
        environment=OFFLINE,
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
            "SWISSQUOTE_TAX_OFFLINE": "true",
        },
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Jahresdurchschnitt" in result.stdout
    assert "95.24 EUR" in result.stdout


def test_multiple_years_require_an_explicit_tax_year() -> None:
    """A historical CSV needs --tax-year to identify the requested report."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
31-12-2024 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97;USD
"""

    result = run_cli(csv_content, ["--no-details"], environment=OFFLINE)

    assert result.returncode != 0
    assert "Fehler: Transaktionen aus mehreren Jahren gefunden" in result.stderr


def test_missing_required_column_is_reported() -> None:
    """The CLI reports a missing required CSV column."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;43.67;0.00;0.00;43.67;43.97
"""

    result = run_cli(csv_content, ["--no-details"], environment=OFFLINE)

    assert result.returncode != 0
    assert "Fehler: Fehlende Spalten in CSV" in result.stderr
    assert "Währung" in result.stderr


def test_annual_fx_mode_uses_fallback_rates() -> None:
    """Annual mode uses fallback rates when offline."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
31-12-2025 15:57:09;00000000;Dividende;ETF001;"ETF_NAME_1";IE0000000001;1.0;100.00;0.00;0.00;100.00;100.00;USD
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Jahresdurchschnitt" in result.stdout
    assert "95.24 EUR" in result.stdout


def test_withholding_tax_is_converted_and_reported() -> None:
    """A configured foreign ISIN credits Kosten up to its treaty rate."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;US ETF;US0000000001;85.00;-15.00;USD
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "US0000000001"
source_country = "US"
tax_treatment = "foreign"
max_creditable_rate = 0.15
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "3. Anlage KAP (Zeile 41 - Anrechenbare ausländische Steuern): 14.29 EUR" in result.stdout
    assert "Davon Quellensteuer auf Dividenden: 14.29 EUR" in result.stdout


def test_dividend_income_is_reported_gross_of_withholding_tax() -> None:
    """Declared dividend income adds back withheld tax to report the gross amount."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;US ETF;US0000000001;85.00;-15.00;USD
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "US0000000001"
source_country = "US"
tax_treatment = "foreign"
max_creditable_rate = 0.15
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Anlage KAP (Zeile 19 - Ausländische Kapitalerträge, ausländische Aktien): 95.24 EUR" in result.stdout


def test_domestic_dividend_income_is_reported_gross_of_german_tax() -> None:
    """A German dividend is declared with its gross amount before the 26.375% deduction."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;SAP;DE0007164600;73.625;-26.375;EUR
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "DE0007164600"
source_country = "DE"
tax_treatment = "domestic"
max_creditable_rate = 0.0
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Anlage KAP (Zeile 18 - Inländische Kapitalerträge, deutsche Aktien): 100.00 EUR" in result.stdout


def test_fund_distribution_is_reported_in_anlage_kap_inv() -> None:
    """A security flagged as a fund is reported on the Anlage KAP-INV line."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;World ETF;IE00B3RBWM25;100.00;0.00;EUR
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "IE00B3RBWM25"
source_country = "IE"
tax_treatment = "foreign"
max_creditable_rate = 0.0
instrument = "fund"
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Anlage KAP-INV (Zeile 4 - Investmentfonds-/ETF-Ausschüttungen): 100.00 EUR" in result.stdout
    assert "Anlage KAP (Zeile 19 - Ausländische Kapitalerträge, ausländische Aktien): 0.00 EUR" in result.stdout


def test_summary_combines_foreign_dividends_and_interest_in_line_19() -> None:
    """The closing summary sums foreign dividends and interest into a single Zeile 19."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;Nestle;CH0038863350;40.00;0.00;EUR
30-06-2025 15:57:09;Zinsen auf Einlagen;;;10.00;0.00;EUR
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "CH0038863350"
source_country = "CH"
tax_treatment = "foreign"
max_creditable_rate = 0.15
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "ZUSAMMENFASSUNG" in result.stdout
    assert "Zeile 19  Ausländische Kapitalerträge: 50.00 EUR" in result.stdout
    assert "= ausländische Dividenden 40.00 EUR + ausländische Zinsen 10.00 EUR" in result.stdout


def test_domestic_tax_position_is_reported_even_when_empty() -> None:
    """The report retains its numbering when no domestic tax was withheld."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;US ETF;US0000000001;85.00;-15.00;USD
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "US0000000001"
source_country = "US"
tax_treatment = "foreign"
max_creditable_rate = 0.15
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Zeile 43 - Anrechenbare Kapitalertragsteuer: 0.00 EUR" in result.stdout
    assert "Zeile 44 - Anrechenbarer Solidaritätszuschlag: 0.00 EUR" in result.stdout


def test_domestic_capital_gains_tax_including_soli_is_reported() -> None:
    """A domestic SAP rule reports German capital gains tax separately from foreign tax."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;SAP;DE0007164600;73.625;-26.375;EUR
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "DE0007164600"
source_country = "DE"
tax_treatment = "domestic"
max_creditable_rate = 0.0
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Zeile 43 - Anrechenbare Kapitalertragsteuer: 25.00 EUR" in result.stdout
    assert "Zeile 44 - Anrechenbarer Solidaritätszuschlag: 1.38 EUR" in result.stdout
    assert "Anrechenbare ausländische Steuern): 0.00 EUR" in result.stdout


def test_separate_withholding_tax_transaction_is_reported() -> None:
    """Separate tax bookings need their associated gross income before crediting."""
    csv_content = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Währung
31-12-2025 15:57:09;Dividende;US ETF;US0000000001;85.00;USD
31-12-2025 15:57:09;Withholding Tax;US ETF;US0000000001;-15.00;USD
"""

    result = run_cli(
        csv_content,
        ["--no-details", "--fx-mode", "annual"],
        environment=OFFLINE,
        withholding_tax_rules="""[[security]]
isin = "US0000000001"
source_country = "US"
tax_treatment = "foreign"
max_creditable_rate = 0.15
""",
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "3. Anlage KAP (Zeile 41 - Anrechenbare ausländische Steuern): 0.00 EUR" in result.stdout
    assert "Nicht in Zeile 41 (fehlende ISIN-Regel oder Bruttobetrag): 14.29 EUR" in result.stdout
