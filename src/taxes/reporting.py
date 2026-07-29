import polars as pl


def format_amount(value: float, round_amount: bool) -> str:
    """Format a Euro amount for display, optionally rounding to whole Euros."""
    if round_amount:
        return f"{round(value)} EUR"
    return f"{value:.2f} EUR"


def print_section(title: str, dataframe: pl.DataFrame, columns: list[str], amount_col: str, round_amount: bool) -> None:
    """Print transaction details and their total in a titled section."""
    print(f"\n--- {title} ---")
    if dataframe.is_empty():
        print("Keine Einträge")
        return
    display_columns = [column for column in columns if column in dataframe.columns]
    with pl.Config(
        tbl_rows=-1,
        tbl_cols=-1,
        fmt_str_lengths=100,
        tbl_hide_column_data_types=True,
        tbl_hide_dtype_separator=True,
        tbl_hide_dataframe_shape=True,
    ):
        print(dataframe.select(display_columns))
    total = float(dataframe[amount_col].sum())
    print(f"Summe: {format_amount(total, round_amount)}")


def print_stock_sale_tax_note(stock_sales: pl.DataFrame, result_col: str, round_amount: bool) -> None:
    """Print Anlage KAP guidance for realized stock sales."""
    if stock_sales.is_empty():
        print("   Anlage KAP: Keine Eintragung für Aktienverkäufe (keine Verkaufstransaktionen).")
        return

    gains = float(stock_sales.filter(pl.col(result_col) > 0)[result_col].sum())
    losses = float(stock_sales.filter(pl.col(result_col) < 0)[result_col].sum())
    print("   Anlage KAP: In Kapitalerträgen ohne inländischen Steuerabzug berücksichtigen.")
    if gains:
        print(f"   Davon Aktiengewinne (separates Formularfeld): {format_amount(gains, round_amount)}")
    if losses:
        print(f"   Davon Aktienverluste (separates Formularfeld): {format_amount(losses, round_amount)}")


def print_form_summary(
    domestic_share_dividends: float,
    foreign_share_dividends: float,
    fund_dividends: float,
    interest: float,
    foreign_creditable: float,
    domestic_capital_gains_tax: float,
    domestic_solidarity_surcharge: float,
    stock_gains: float,
    stock_losses: float,
    round_amount: bool,
) -> None:
    """Print a form-oriented summary mapping each amount to its Anlage KAP line."""
    foreign_capital_income = foreign_share_dividends + interest
    print("\n=== ZUSAMMENFASSUNG: WELCHER BETRAG IN WELCHE ZEILE (Anlage KAP 2025) ===")
    print("Anlage KAP")
    print(
        f"  Zeile 18  Inländische Kapitalerträge (deutsche Aktien): {format_amount(domestic_share_dividends, round_amount)}"
    )
    print(f"  Zeile 19  Ausländische Kapitalerträge: {format_amount(foreign_capital_income, round_amount)}")
    print(
        f"            = ausländische Dividenden {format_amount(foreign_share_dividends, round_amount)}"
        f" + ausländische Zinsen {format_amount(interest, round_amount)}"
    )
    print(f"  Zeile 41  Anrechenbare ausländische Steuern: {format_amount(foreign_creditable, round_amount)}")
    print(f"  Zeile 43  Anrechenbare Kapitalertragsteuer: {format_amount(domestic_capital_gains_tax, round_amount)}")
    print(
        f"  Zeile 44  Anrechenbarer Solidaritätszuschlag: {format_amount(domestic_solidarity_surcharge, round_amount)}"
    )
    if stock_gains or stock_losses:
        print(
            "  Aktienveräußerungen (in den Kapitalerträgen ohne inländischen Steuerabzug, "
            "Aktien-Unterzeilen laut Formular):"
        )
        print(f"            Aktiengewinne: {format_amount(stock_gains, round_amount)}")
        print(f"            Aktienverluste: {format_amount(stock_losses, round_amount)}")
    print("Anlage KAP-INV")
    print(f"  Zeile 4   Investmentfonds-/ETF-Ausschüttungen: {format_amount(fund_dividends, round_amount)}")
    print("Zeilennummern beziehen sich auf die Anlage KAP 2025 – vor Abgabe am ELSTER-Formular prüfen.")


def export_details(
    dividends: pl.DataFrame,
    interest: pl.DataFrame,
    stock_sales: pl.DataFrame,
    path: str,
    separator: str,
) -> None:
    """Export all reported tax details to a CSV file."""
    output_dataframe = pl.concat(
        [
            dividends.with_columns(pl.lit("Dividende").alias("Kategorie")),
            interest.with_columns(pl.lit("Zinsen").alias("Kategorie")),
            stock_sales.with_columns(pl.lit("Aktienverkauf").alias("Kategorie")),
        ],
        how="diagonal",
    )
    output_dataframe.write_csv(path, separator=separator)
