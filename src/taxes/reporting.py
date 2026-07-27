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
