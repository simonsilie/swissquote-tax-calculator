from tests.cli_test_helpers import run_cli


def test_realized_stock_sales_use_fifo_cost_basis() -> None:
    """Stock sales use their net proceeds and the matching FIFO purchase cost."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
01-01-2025 09:00:00;1;Kauf;ABC;"ABC AG";DE0000000001;2.0;100.00;0.00;0.00;-200.00;800.00;EUR
01-02-2025 09:00:00;2;Kauf;ABC;"ABC AG";DE0000000001;2.0;150.00;0.00;0.00;-300.00;500.00;EUR
01-03-2025 09:00:00;3;Verkauf;ABC;"ABC AG";DE0000000001;3.0;200.00;0.00;0.00;600.00;1100.00;EUR
"""

    result = run_cli(csv_content, ["--fx-usd", "1.0", "--fx-chf", "1.0", "--fx-eur", "1.0"])

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Realisierte Gewinne/Verluste aus Aktienverkäufen: 250.00 EUR" in result.stdout


def test_stock_sales_can_use_historical_purchase_lots() -> None:
    """A selected tax year can sell a security purchased in a prior year."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
01-01-2024 09:00:00;1;Kauf;ABC;"ABC AG";DE0000000001;1.0;100.00;0.00;0.00;-100.00;900.00;EUR
01-03-2025 09:00:00;2;Verkauf;ABC;"ABC AG";DE0000000001;1.0;150.00;0.00;0.00;150.00;1050.00;EUR
"""

    result = run_cli(
        csv_content,
        ["--tax-year", "2025", "--fx-usd", "1.0", "--fx-chf", "1.0", "--fx-eur", "1.0"],
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Realisierte Gewinne/Verluste aus Aktienverkäufen: 50.00 EUR" in result.stdout
