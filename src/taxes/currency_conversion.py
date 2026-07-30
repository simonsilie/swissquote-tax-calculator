import polars as pl

from taxes.fx_rates import DailyFXRateFetcher


def apply_fx_rates_daily(
    dataframe: pl.DataFrame,
    fetcher: DailyFXRateFetcher,
    date_col: str,
    currency_col: str,
    amount_col: str,
    eur_col: str,
) -> pl.DataFrame:
    """Apply per-transaction daily exchange rates to convert amounts to EUR."""
    unique_pairs = dataframe.select(pl.col(date_col), pl.col(currency_col)).unique()
    rates: dict[tuple[str, str], float] = {}
    for row in unique_pairs.iter_rows():
        dt, currency = row
        date_key = dt.date() if hasattr(dt, "date") else dt
        rates[(str(date_key), currency)] = fetcher.get_rate(date_key, currency)

    rate_rows = [{"_fx_date": k[0], "_fx_currency": k[1], "_fx_rate": v} for k, v in rates.items()]
    rate_df = pl.DataFrame(rate_rows)

    dataframe = dataframe.with_columns(
        pl.col(date_col).cast(pl.Date).cast(pl.String).alias("_fx_date"),
        pl.col(currency_col).alias("_fx_currency"),
    )
    dataframe = dataframe.join(rate_df, on=["_fx_date", "_fx_currency"], how="left")
    dataframe = dataframe.with_columns(
        (pl.col(amount_col) / pl.col("_fx_rate")).alias(eur_col),
    )
    return dataframe.drop("_fx_date", "_fx_currency", "_fx_rate")
