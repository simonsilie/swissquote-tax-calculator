from datetime import date

import polars as pl

from taxes.stock_sales import calculate_realized_stock_results
from tests.cli_test_helpers import run_cli


OFFLINE = {"SWISSQUOTE_TAX_OFFLINE": "true"}


def test_integration_realized_stock_sales_use_fifo_cost_basis() -> None:
    """Stock sales use their net proceeds and the matching FIFO purchase cost."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
01-01-2025 09:00:00;1;Kauf;ABC;"ABC AG";DE0000000001;2.0;100.00;0.00;0.00;-200.00;800.00;EUR
01-02-2025 09:00:00;2;Kauf;ABC;"ABC AG";DE0000000001;2.0;150.00;0.00;0.00;-300.00;500.00;EUR
01-03-2025 09:00:00;3;Verkauf;ABC;"ABC AG";DE0000000001;3.0;200.00;0.00;0.00;600.00;1100.00;EUR
"""

    result = run_cli(csv_content, [], environment=OFFLINE)

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Realisierte Gewinne/Verluste aus Aktienverkäufen: 250.00 EUR" in result.stdout
    assert "Aktiengewinne (separates Formularfeld): 250.00 EUR" in result.stdout


def test_integration_partial_sales_do_not_reuse_consumed_lot_costs() -> None:
    """Selling one lot in two tranches splits its cost across both sales."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
01-01-2025 09:00:00;1;Kauf;ABC;"ABC AG";DE0000000001;10.0;100.00;0.00;0.00;-1000.00;0.00;EUR
01-06-2025 09:00:00;2;Verkauf;ABC;"ABC AG";DE0000000001;5.0;150.00;0.00;0.00;750.00;750.00;EUR
01-07-2025 09:00:00;3;Verkauf;ABC;"ABC AG";DE0000000001;5.0;150.00;0.00;0.00;750.00;1450.00;EUR
"""

    result = run_cli(csv_content, ["--no-details"], environment=OFFLINE)

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    # Each sale carries 500.00 EUR of acquisition costs: 2 × 250.00 EUR gain.
    assert "Realisierte Gewinne/Verluste aus Aktienverkäufen: 500.00 EUR" in result.stdout


def test_partial_sale_costs_split_that_does_not_divide_evenly() -> None:
    """A lot cost that does not divide evenly is conserved across partial sales."""
    # Arrange
    dataframe = pl.DataFrame(
        {
            "Datum": [date(2025, 1, 1), date(2025, 6, 1), date(2025, 7, 1)],
            "Transaktionen": ["Kauf", "Verkauf", "Verkauf"],
            "ISIN": ["DE0000000001"] * 3,
            "Anzahl": [2.0, 1.0, 1.0],
            "Nettobetrag_EUR": [-1000.01, 750.0, 750.0],
        }
    )

    # Act
    results = calculate_realized_stock_results(
        dataframe,
        ["Kauf"],
        ["Verkauf"],
        "Datum",
        "Transaktionen",
        "ISIN",
        "Anzahl",
        "Nettobetrag_EUR",
    ).sort("Datum")

    # 1000.01 EUR splits to 500.01 + 500.00, not 500.01 + 500.01.
    # Assert
    assert results["Anschaffungskosten_EUR"].to_list() == [500.01, 500.0]
    assert results["Gewinn_Verlust_EUR"].to_list() == [249.99, 250.0]


def test_integration_stock_sales_can_use_historical_purchase_lots() -> None:
    """A selected tax year can sell a security purchased in a prior year."""
    csv_content = """Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
01-01-2024 09:00:00;1;Kauf;ABC;"ABC AG";DE0000000001;1.0;100.00;0.00;0.00;-100.00;900.00;EUR
01-03-2025 09:00:00;2;Verkauf;ABC;"ABC AG";DE0000000001;1.0;150.00;0.00;0.00;150.00;1050.00;EUR
"""

    result = run_cli(
        csv_content,
        ["--tax-year", "2025"],
        environment=OFFLINE,
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Realisierte Gewinne/Verluste aus Aktienverkäufen: 50.00 EUR" in result.stdout
