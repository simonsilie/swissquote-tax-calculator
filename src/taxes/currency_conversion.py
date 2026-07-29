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
    return dataframe.with_columns(
        pl.struct([pl.col(date_col), pl.col(currency_col), pl.col(amount_col)])
        .map_elements(
            lambda row: (
                row[amount_col] / fetcher.get_rate(row[date_col].date(), row[currency_col])
                if row[currency_col] != "EUR"
                else row[amount_col]
            ),
            return_dtype=pl.Float64,
        )
        .alias(eur_col)
    )
