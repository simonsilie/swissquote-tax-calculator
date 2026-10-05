import subprocess
import tempfile
from pathlib import Path

import streamlit as st

from taxes.presenter import (
    DetailsView,
    Metric,
    Result,
    ResultsView,
    WithholdingTaxView,
    build_details_view,
    build_results_view,
    calculate,
    export_summary,
)


def _metric_row(metrics: tuple[Metric, ...]) -> None:
    columns = st.columns(len(metrics))
    for column, metric in zip(columns, metrics, strict=True):
        with column:
            st.metric(metric.label, metric.value)


def _display_withholding_tax(view: WithholdingTaxView) -> None:
    st.subheader("3. Anlage KAP - Anrechenbare ausländische Quellensteuer")
    _metric_row((view.creditable_metric,))
    if view.country_breakdown:
        st.dataframe(
            [{"Land": country, "Betrag": amount} for country, amount in view.country_breakdown],
            width="stretch",
        )
    _metric_row(view.split_metrics)
    if view.excess_note:
        st.info(view.excess_note)
    if view.swiss_refund_note:
        st.info(view.swiss_refund_note)

    st.subheader("4. Anlage KAP - Steueranrechnung")
    _metric_row(view.credit_metrics)
    if view.unclassified_note:
        st.warning(view.unclassified_note)


def _display_results(view: ResultsView) -> None:
    st.subheader("1. Dividenden (Bruttoerträge vor Quellensteuer):")
    _metric_row(view.dividend_metrics)

    st.subheader("2. Anlage KAP - Ausländische Zinsen")
    _metric_row((view.interest_metric,))

    if view.withholding_tax is not None:
        _display_withholding_tax(view.withholding_tax)

    st.subheader("5. Realisierte Gewinne/Verluste aus Aktienverkäufen (FIFO)")
    _metric_row(view.stock_metrics)


def _display_details(view: DetailsView) -> None:
    tabs = st.tabs([tab.title for tab in view.tabs])
    for tab, detail in zip(tabs, view.tabs, strict=True):
        with tab:
            if detail.transactions.is_empty():
                st.info("Keine Einträge")
            else:
                st.dataframe(detail.transactions, width="stretch")
                if detail.total:
                    st.caption(detail.total)


def _show_downloads(result: Result) -> None:
    md_path = export_summary(result, Path("./output"))
    st.download_button(
        label="ELSTER Summary (Markdown) herunterladen",
        data=md_path.read_text(encoding="utf-8"),
        file_name="tax_summary_elster.md",
        mime="text/markdown",
    )
    pdf_path = md_path.with_suffix(".pdf")
    if pdf_path.exists():
        st.download_button(
            label="ELSTER Summary (PDF) herunterladen",
            data=pdf_path.read_bytes(),
            file_name="tax_summary_elster.pdf",
            mime="application/pdf",
        )


def main() -> None:
    st.set_page_config(page_title="Swissquote Tax Calculator", layout="wide")
    st.title("Swissquote ELSTER Steuer-Auswertung")

    st.sidebar.header("Konfiguration")
    tax_year_input = st.sidebar.number_input(
        "Steuerjahr (optional, 0 = automatisch)", min_value=0, max_value=2030, value=0
    )
    round_amounts = st.sidebar.checkbox("Auf ganze Euro runden", value=True)
    export_summary_checked = st.sidebar.checkbox("ELSTER-Mapping-Datei exportieren", value=True)

    if "result" not in st.session_state:
        st.session_state.result = None

    uploaded_file = st.file_uploader("Swissquote CSV-Datei hochladen", type=["csv"])

    if uploaded_file is not None:
        if st.button("Auswertung starten", type="primary"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = Path(tmp.name)

            with st.spinner("Verarbeite Transaktionen und rufe EZB-Kurse ab..."):
                try:
                    st.session_state.result = calculate(
                        tmp_path,
                        tax_year=tax_year_input if tax_year_input > 0 else None,
                        round_amount=round_amounts,
                    )
                except ValueError as error:
                    st.error(str(error))
                    st.stop()

    if st.session_state.result is not None:
        result = st.session_state.result
        summary = build_results_view(result)
        st.success(f"Ergebnisse für Steuerjahr {summary.tax_year}")

        _display_results(summary)

        with st.expander("Transaktionsdetails anzeigen", expanded=False):
            _display_details(build_details_view(result))

        if export_summary_checked:
            _show_downloads(result)


def run_app() -> None:
    process = subprocess.Popen(["streamlit", "run", __file__])
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()


if __name__ == "__main__":
    main()
