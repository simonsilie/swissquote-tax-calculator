import subprocess
import tempfile
from pathlib import Path

import streamlit as st

from taxes.elster_export import export_elster_mapping
from taxes.reporting import format_amount
from taxes.result import Result
from taxes.service import TaxConfig, calculate_taxes


def _display_results(result: Result) -> None:
    rt = result
    wts = rt.withholding_tax_summary

    st.subheader("1. Dividenden (Bruttoerträge vor Quellensteuer):")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric(
            "Anlage KAP Zeile 18 - Inländisch",
            format_amount(rt.dividends.total_domestic_shares, rt.config.round_amount),
        )
    with col_b:
        st.metric(
            "Anlage KAP Zeile 19 - Ausländisch",
            format_amount(rt.dividends.total_foreign_shares, rt.config.round_amount),
        )
    with col_c:
        st.metric(
            "Anlage KAP-INV Zeile 4 - Fonds/ETFs", format_amount(rt.dividends.total_funds, rt.config.round_amount)
        )

    st.subheader("2. Anlage KAP - Ausländische Zinsen")
    st.metric("Zeile 19", format_amount(rt.interest.total, rt.config.round_amount))

    if rt.config.col_withholding_tax_eur in rt.df.columns or not rt.withholding_tax_transactions.is_empty():
        st.subheader("3. Anlage KAP - Anrechenbare ausländische Quellensteuer")
        st.metric("Zeile 41", format_amount(wts.foreign_creditable, rt.config.round_amount))
        if wts.foreign_creditable_by_country:
            country_data = [
                {"Land": c, "Betrag": format_amount(a, rt.config.round_amount)}
                for c, a in wts.foreign_creditable_by_country
            ]
            st.dataframe(country_data, width="stretch")
        col_d, col_z = st.columns(2)
        with col_d:
            st.metric(
                "Davon Dividenden", format_amount(rt.dividends.tax_summary.foreign_creditable, rt.config.round_amount)
            )
        with col_z:
            st.metric("Davon Zinsen", format_amount(rt.interest.tax_summary.foreign_creditable, rt.config.round_amount))
        if wts.foreign_excess:
            st.info(f"Nicht anrechenbarer Steuerüberhang: {format_amount(wts.foreign_excess, rt.config.round_amount)}")
        if wts.swiss_refundable:
            st.info(
                f"Schweizer Verrechnungssteuer (separat rückforderbar): {format_amount(wts.swiss_refundable, rt.config.round_amount)}"
            )

        st.subheader("4. Anlage KAP - Steueranrechnung")
        col_37, col_38, col_sum = st.columns(3)
        with col_37:
            st.metric(
                "Zeile 37 - Kapitalertragsteuer", format_amount(wts.domestic_capital_gains_tax, rt.config.round_amount)
            )
        with col_38:
            st.metric("Zeile 38 - Soli", format_amount(wts.domestic_solidarity_surcharge, rt.config.round_amount))
        with col_sum:
            st.metric("Summe dt. KapSt + Soli", format_amount(wts.domestic, rt.config.round_amount))
        if wts.unclassified:
            st.warning(f"Nicht klassifizierte Steuer: {format_amount(wts.unclassified, rt.config.round_amount)}")

    st.subheader("5. Realisierte Gewinne/Verluste aus Aktienverkäufen (FIFO)")
    col_gain, col_loss, col_net = st.columns(3)
    with col_gain:
        st.metric("Aktiengewinne", format_amount(rt.stock_sales.gains, rt.config.round_amount))
    with col_loss:
        st.metric("Aktienverluste", format_amount(rt.stock_sales.losses, rt.config.round_amount))
    with col_net:
        st.metric("Summe", format_amount(rt.stock_sales.total, rt.config.round_amount))


def _display_details(result: Result) -> None:
    rt = result
    detail_cols: list[str] = [
        rt.config.col_date,
        rt.config.col_name,
        rt.config.col_amount,
        rt.config.col_currency,
        rt.config.col_eur,
        rt.config.col_gross_eur,
        rt.config.col_withholding_tax,
        rt.config.col_withholding_tax_eur,
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
        rt.config.col_date,
        rt.config.col_isin,
        rt.config.col_quantity,
        "Verkaufserloes_EUR",
        "Anschaffungskosten_EUR",
        "Gewinn_Verlust_EUR",
    ]

    tab1, tab2, tab3, tab4 = st.tabs(["Dividenden", "Zinsen", "Quellensteuer-Buchungen", "Aktienverkäufe"])
    with tab1:
        if rt.dividends.transactions.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in detail_cols if c in rt.dividends.transactions.columns]
            st.dataframe(rt.dividends.transactions.select(existing), width="stretch")
            st.caption(
                f"Summe: {format_amount(float(rt.dividends.transactions[rt.config.col_gross_eur].sum()), rt.config.round_amount)}"
            )
    with tab2:
        if rt.interest.transactions.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in detail_cols if c in rt.interest.transactions.columns]
            st.dataframe(rt.interest.transactions.select(existing), width="stretch")
            st.caption(
                f"Summe: {format_amount(float(rt.interest.transactions[rt.config.col_gross_eur].sum()), rt.config.round_amount)}"
            )
    with tab3:
        if rt.withholding_tax_transactions.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in detail_cols if c in rt.withholding_tax_transactions.columns]
            st.dataframe(rt.withholding_tax_transactions.select(existing), width="stretch")
            st.caption(
                f"Summe: {format_amount(float(rt.withholding_tax_transactions[rt.config.col_eur].sum()), rt.config.round_amount)}"
            )
    with tab4:
        if rt.stock_sales.transactions.is_empty():
            st.info("Keine Einträge")
        else:
            existing = [c for c in sale_cols if c in rt.stock_sales.transactions.columns]
            st.dataframe(rt.stock_sales.transactions.select(existing), width="stretch")


def _show_downloads(result: Result) -> None:
    output_dir = Path("./output")
    md_path = export_elster_mapping(
        output_dir=output_dir,
        tax_year=result.tax_year,
        total_domestic_share_dividends=result.dividends.total_domestic_shares,
        total_foreign_share_dividends=result.dividends.total_foreign_shares,
        total_interest=result.interest.total,
        total_fund_dividends=result.dividends.total_funds,
        withholding_tax_summary=result.withholding_tax_summary,
        stock_gains=result.stock_sales.gains,
        stock_losses=result.stock_sales.losses,
        fund_dividends=result.dividends.funds,
        round_amount=result.config.round_amount,
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
                    config = TaxConfig(
                        csv_file=tmp_path,
                        tax_year=tax_year_input if tax_year_input > 0 else None,
                        round_amount=round_amounts,
                    )
                    st.session_state.result = calculate_taxes(config)
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