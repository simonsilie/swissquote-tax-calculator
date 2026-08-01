import subprocess
import tempfile
from pathlib import Path

import streamlit as st

from taxes.elster_export import export_elster_mapping
from taxes.reporting import format_amount
from taxes.service import TaxCalculationResult, calculate_taxes


def _display_results(result: TaxCalculationResult) -> None:
    rt = result
    wts = rt.withholding_tax_summary

    st.subheader("1. Dividenden (Bruttoerträge vor Quellensteuer):")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Anlage KAP Zeile 18 - Inländisch", format_amount(rt.total_domestic_share_dividends, rt.round))
    with col_b:
        st.metric("Anlage KAP Zeile 19 - Ausländisch", format_amount(rt.total_foreign_share_dividends, rt.round))
    with col_c:
        st.metric("Anlage KAP-INV Zeile 4 - Fonds/ETFs", format_amount(rt.total_fund_dividends, rt.round))

    st.subheader("2. Anlage KAP - Ausländische Zinsen")
    st.metric("Zeile 19", format_amount(rt.total_interest, rt.round))

    if rt.col_withholding_tax_eur in rt.df.columns or not rt.withholding_tax_transactions.is_empty():
        st.subheader("3. Anlage KAP - Anrechenbare ausländische Quellensteuer")
        st.metric("Zeile 41", format_amount(wts.foreign_creditable, rt.round))
        if wts.foreign_creditable_by_country:
            country_data = [
                {"Land": c, "Betrag": format_amount(a, rt.round)} for c, a in wts.foreign_creditable_by_country
            ]
            st.dataframe(country_data, width="stretch")
        col_d, col_z = st.columns(2)
        with col_d:
            st.metric("Davon Dividenden", format_amount(rt.dividend_tax_summary.foreign_creditable, rt.round))
        with col_z:
            st.metric("Davon Zinsen", format_amount(rt.interest_tax_summary.foreign_creditable, rt.round))
        if wts.foreign_excess:
            st.info(f"Nicht anrechenbarer Steuerüberhang: {format_amount(wts.foreign_excess, rt.round)}")
        if wts.swiss_refundable:
            st.info(
                f"Schweizer Verrechnungssteuer (separat rückforderbar): {format_amount(wts.swiss_refundable, rt.round)}"
            )

        st.subheader("4. Anlage KAP - Steueranrechnung")
        col_37, col_38, col_sum = st.columns(3)
        with col_37:
            st.metric("Zeile 37 - Kapitalertragsteuer", format_amount(wts.domestic_capital_gains_tax, rt.round))
        with col_38:
            st.metric("Zeile 38 - Soli", format_amount(wts.domestic_solidarity_surcharge, rt.round))
        with col_sum:
            st.metric("Summe dt. KapSt + Soli", format_amount(wts.domestic, rt.round))
        if wts.unclassified:
            st.warning(f"Nicht klassifizierte Steuer: {format_amount(wts.unclassified, rt.round)}")

    st.subheader("5. Realisierte Gewinne/Verluste aus Aktienverkäufen (FIFO)")
    col_gain, col_loss, col_net = st.columns(3)
    with col_gain:
        st.metric("Aktiengewinne", format_amount(rt.stock_gains, rt.round))
    with col_loss:
        st.metric("Aktienverluste", format_amount(rt.stock_losses, rt.round))
    with col_net:
        st.metric("Summe", format_amount(rt.total_stock_sales, rt.round))


def _display_details(result: TaxCalculationResult) -> None:
    rt = result
    detail_cols: list[str] = [
        rt.col_date,
        rt.col_name,
        rt.col_amount,
        rt.col_currency,
        rt.col_eur,
        rt.col_gross_eur,
        rt.col_withholding_tax,
        rt.col_withholding_tax_eur,
        "Formular",
        "Quellenstaat",
        "Steuerbehandlung",
        "Anrechenbare_Quellensteuer_EUR",
        "Nicht_anrechenbare_Quellensteuer_EUR",
        "Inlaendische_Kapitalertragsteuer_EUR",
        "Solidaritaetszuschlag_EUR",
        "Nicht_klassifizierte_Steuer_EUR",
    ]
    sale_cols = [
        rt.col_date,
        rt.col_isin,
        rt.col_quantity,
        "Verkaufserloes_EUR",
        "Anschaffungskosten_EUR",
        "Gewinn_Verlust_EUR",
    ]

    tab1, tab2, tab3, tab4 = st.tabs(["Dividenden", "Zinsen", "Quellensteuer-Buchungen", "Aktienverkäufe"])
    with tab1:
        if rt.dividends.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in detail_cols if c in rt.dividends.columns]
            st.dataframe(rt.dividends.select(existing), width="stretch")
            st.caption(f"Summe: {format_amount(float(rt.dividends[rt.col_gross_eur].sum()), rt.round)}")
    with tab2:
        if rt.interest.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in detail_cols if c in rt.interest.columns]
            st.dataframe(rt.interest.select(existing), width="stretch")
            st.caption(f"Summe: {format_amount(float(rt.interest[rt.col_gross_eur].sum()), rt.round)}")
    with tab3:
        if rt.withholding_tax_transactions.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in detail_cols if c in rt.withholding_tax_transactions.columns]
            st.dataframe(rt.withholding_tax_transactions.select(existing), width="stretch")
            st.caption(
                f"Summe: {format_amount(float(rt.withholding_tax_transactions[rt.col_eur].sum()), rt.round)}"
            )
    with tab4:
        if rt.stock_sales.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in sale_cols if c in rt.stock_sales.columns]
            st.dataframe(rt.stock_sales.select(existing), width="stretch")


def _show_downloads(result: TaxCalculationResult) -> None:
    output_dir = Path("./output")
    md_path = export_elster_mapping(
        output_dir=output_dir,
        tax_year=result.tax_year,
        total_domestic_share_dividends=result.total_domestic_share_dividends,
        total_foreign_share_dividends=result.total_foreign_share_dividends,
        total_interest=result.total_interest,
        total_fund_dividends=result.total_fund_dividends,
        withholding_tax_summary=result.withholding_tax_summary,
        stock_gains=result.stock_gains,
        stock_losses=result.stock_losses,
        fund_dividends=result.fund_dividends,
        round_amount=result.round,
    )
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
    tax_year_input = st.sidebar.number_input("Steuerjahr (optional, 0 = automatisch)", min_value=0, max_value=2030, value=0)
    round_amounts = st.sidebar.checkbox("Auf ganze Euro runden", value=True)
    export_summary = st.sidebar.checkbox("ELSTER-Mapping-Datei exportieren", value=True)

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
                    st.session_state.result = calculate_taxes(
                        csv_file=tmp_path,
                        tax_year=tax_year_input if tax_year_input > 0 else None,
                        round_amount=round_amounts,
                    )
                except ValueError as error:
                    st.error(str(error))
                    st.stop()

    if st.session_state.result is not None:
        result = st.session_state.result
        st.success(f"Ergebnisse für Steuerjahr {result.tax_year}")

        _display_results(result)

        with st.expander("Transaktionsdetails anzeigen", expanded=False):
            _display_details(result)

        if export_summary:
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