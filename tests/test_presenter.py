from datetime import date
from pathlib import Path

import pytest

from taxes.presenter import Metric, build_details_view, build_results_view, calculate, export_summary
from taxes.result import Result
from taxes.service import TaxConfig, calculate_taxes


class FakeFXRateFetcher:
    """Deterministic rate source for tests — no network, no cache."""

    def __init__(self, rates: dict[str, float]) -> None:
        self.rates = rates
        self.requested: list[tuple[date, str]] = []

    def get_rate(self, target_date: date, currency: str) -> float:
        self.requested.append((target_date, currency))
        if currency == "EUR":
            return 1.0
        return self.rates[currency]


CSV_CONTENT = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;US ETF;US0000000001;85.00;-15.00;USD
"""

SWISS_CSV_CONTENT = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Kosten;Währung
31-12-2025 15:57:09;Dividende;CH Aktie;CH0000000002;65.00;-35.00;CHF
"""

CSV_WITHOUT_TAX_CONTENT = """Datum;Transaktionen;Name;ISIN;Nettobetrag;Währung
31-12-2025 15:57:09;Dividende;DE Aktie;DE0000000001;100.00;EUR
"""


def write_csv(tmp_path: Path, content: str = CSV_CONTENT) -> Path:
    csv_file = tmp_path / "transactions.csv"
    csv_file.write_text(content, encoding="latin1")
    return csv_file


def calculate_result(tmp_path: Path, content: str = CSV_CONTENT) -> Result:
    """Run the pipeline with an injected rate source — presenter tests stay offline."""
    fetcher = FakeFXRateFetcher({"USD": 2.0, "CHF": 1.0})
    return calculate_taxes(TaxConfig(csv_file=write_csv(tmp_path, content), tax_year=2025, fx_fetcher=fetcher))


def test_calculate_passes_the_app_options_to_the_service(tmp_path: Path) -> None:
    """EUR-only input needs no rate lookup, so the thin wrapper stays offline."""
    csv_file = write_csv(tmp_path, CSV_WITHOUT_TAX_CONTENT)

    result = calculate(csv_file, tax_year=2025, round_amount=True)

    assert result.tax_year == 2025
    assert result.config.round_amount is True
    assert result.dividends.total_domestic_shares == pytest.approx(100.0)


def test_results_view_formats_the_summary_sections(tmp_path: Path) -> None:
    result = calculate_result(tmp_path)

    view = build_results_view(result)

    assert view.tax_year == 2025
    assert [(metric.label, metric.value) for metric in view.dividend_metrics] == [
        ("Anlage KAP Zeile 18 - Inländisch", "0.00 EUR"),
        ("Anlage KAP Zeile 19 - Ausländisch", "50.00 EUR"),
        ("Anlage KAP-INV Zeile 4 - Fonds/ETFs", "0.00 EUR"),
    ]
    assert (view.interest_metric.label, view.interest_metric.value) == ("Zeile 19", "0.00 EUR")
    assert [(metric.label, metric.value) for metric in view.stock_metrics] == [
        ("Aktiengewinne", "0.00 EUR"),
        ("Aktienverluste", "0.00 EUR"),
        ("Summe", "0.00 EUR"),
    ]


def test_results_view_formats_the_withholding_tax_sections(tmp_path: Path) -> None:
    withholding = build_results_view(calculate_result(tmp_path)).withholding_tax

    assert withholding is not None
    assert (withholding.creditable_metric.label, withholding.creditable_metric.value) == ("Zeile 41", "7.50 EUR")
    assert withholding.country_breakdown == (("US", "7.50 EUR"),)
    assert [(metric.label, metric.value) for metric in withholding.split_metrics] == [
        ("Davon Dividenden", "7.50 EUR"),
        ("Davon Zinsen", "0.00 EUR"),
    ]
    assert [(metric.label, metric.value) for metric in withholding.credit_metrics] == [
        ("Zeile 37 - Kapitalertragsteuer", "0.00 EUR"),
        ("Zeile 38 - Soli", "0.00 EUR"),
        ("Summe dt. KapSt + Soli", "0.00 EUR"),
    ]
    assert withholding.excess_note is None
    assert withholding.swiss_refund_note is None
    assert withholding.unclassified_note is None


def test_results_view_omits_the_withholding_section_without_tax_data(tmp_path: Path) -> None:
    """No tax column and no standalone bookings means sections 3 and 4 stay hidden."""
    result = calculate_result(tmp_path, CSV_WITHOUT_TAX_CONTENT)

    view = build_results_view(result)

    assert view.withholding_tax is None
    assert view.dividend_metrics[0].value == "100.00 EUR"


def test_results_view_notes_swiss_refund_and_excess(tmp_path: Path) -> None:
    """CH tax beyond the 15% DBA cap becomes excess plus a Swiss refund note."""
    withholding = build_results_view(calculate_result(tmp_path, SWISS_CSV_CONTENT)).withholding_tax

    assert withholding is not None
    assert withholding.excess_note == "Nicht anrechenbarer Steuerüberhang: 20.00 EUR"
    assert withholding.swiss_refund_note == "Schweizer Verrechnungssteuer (separat rückforderbar): 20.00 EUR"
    assert withholding.country_breakdown == (("CH", "15.00 EUR"),)


def test_details_view_slices_columns_and_formats_totals(tmp_path: Path) -> None:
    view = build_details_view(calculate_result(tmp_path))

    assert [tab.title for tab in view.tabs] == ["Dividenden", "Zinsen", "Quellensteuer-Buchungen", "Aktienverkäufe"]
    dividends, interest, standalone, sales = view.tabs

    assert dividends.total == "Summe: 50.00 EUR"
    assert "Formular" in dividends.transactions.columns
    assert "Transaktionen" not in dividends.transactions.columns
    assert list(dividends.transactions.columns) == [
        "Datum",
        "Name",
        "Nettobetrag",
        "Währung",
        "Nettobetrag_EUR",
        "Bruttobetrag_EUR",
        "Kosten",
        "Quellensteuer_EUR",
        "Formular",
        "Quellenstaat",
        "Steuerbehandlung",
        "Anrechenbare_Quellensteuer_EUR",
        "Nicht_anrechenbare_Quellensteuer_EUR",
        "Inlaendische_Kapitalertragsteuer_EUR",
        "Solidaritaetszuschlag_EUR",
        "Nicht_klassifizierte_Steuer_EUR",
    ]

    assert interest.transactions.is_empty()
    assert interest.total is None
    assert standalone.transactions.is_empty()
    assert standalone.total is None

    assert sales.transactions.is_empty()
    assert sales.total is None
    assert list(sales.transactions.columns) == [
        "Datum",
        "ISIN",
        "Anzahl",
        "Verkaufserloes_EUR",
        "Anschaffungskosten_EUR",
        "Gewinn_Verlust_EUR",
    ]


def test_export_summary_writes_the_elster_markdown(tmp_path: Path) -> None:
    result = calculate_result(tmp_path)
    output_dir = tmp_path / "output"

    md_path = export_summary(result, output_dir)

    assert md_path == output_dir / "tax_summary_elster.md"
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "Steuerjahr 2025" in content
    assert "7.50 EUR" in content


def test_metric_is_a_plain_value_object() -> None:
    metric = Metric("Zeile 19", "10.00 EUR")

    assert metric.label == "Zeile 19"
    assert metric.value == "10.00 EUR"
