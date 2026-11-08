from taxes.presenter import Metric, build_details_view, build_results_view
from tests.result_helpers import sample_result


def test_results_view_formats_the_summary_sections() -> None:
    # Arrange
    result = sample_result()

    # Act
    view = build_results_view(result)

    # Assert
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


def test_results_view_formats_the_withholding_tax_sections() -> None:
    # Arrange
    result = sample_result()

    # Act
    withholding = build_results_view(result).withholding_tax

    # Assert
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


def test_results_view_omits_the_withholding_section_without_tax_data() -> None:
    """No tax column and no standalone bookings means sections 3 and 4 stay hidden."""
    # Arrange
    result = sample_result(with_tax=False)

    # Act
    view = build_results_view(result)

    # Assert
    assert view.withholding_tax is None
    assert view.dividend_metrics[0].value == "100.00 EUR"


def test_results_view_notes_swiss_refund_and_excess() -> None:
    """CH tax beyond the 15% DBA cap becomes excess plus a Swiss refund note."""
    # Arrange
    result = sample_result(swiss=True)

    # Act
    withholding = build_results_view(result).withholding_tax

    # Assert
    assert withholding is not None
    assert withholding.excess_note == "Nicht anrechenbarer Steuerüberhang: 20.00 EUR"
    assert withholding.swiss_refund_note == "Schweizer Verrechnungssteuer (separat rückforderbar): 20.00 EUR"
    assert withholding.country_breakdown == (("CH", "15.00 EUR"),)


def test_details_view_slices_columns_and_formats_totals() -> None:
    # Arrange
    result = sample_result()

    # Act
    view = build_details_view(result)

    # Assert
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


def test_metric_is_a_plain_value_object() -> None:
    # Arrange
    label, value = "Zeile 19", "10.00 EUR"

    # Act
    metric = Metric(label, value)

    # Assert
    assert metric.label == "Zeile 19"
    assert metric.value == "10.00 EUR"
