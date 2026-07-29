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


def apply_fx_rates_annual(
    dataframe: pl.DataFrame,
    fetcher: DailyFXRateFetcher,
    tax_year: int,
    currency_col: str,
    amount_col: str,
    eur_col: str,
) -> pl.DataFrame:
    """Apply annual-average exchange rates to convert amounts to EUR."""

    annual_rates = fetcher.fetch_annual_rates(tax_year)
    if annual_rates is None:
        annual_rates = fetcher.get_fallback_rates(tax_year)

    print(
        f"  Wechselkurse (Jahresdurchschnitt {tax_year}): "
        f"EUR/USD={annual_rates['USD']:.4f}, EUR/CHF={annual_rates['CHF']:.4f}"
    )

    return dataframe.with_columns(
        pl.when(pl.col(currency_col) == "USD")
        .then(pl.col(amount_col) / annual_rates["USD"])
        .when(pl.col(currency_col) == "CHF")
        .then(pl.col(amount_col) / annual_rates["CHF"])
        .when(pl.col(currency_col) == "EUR")
        .then(pl.col(amount_col) / annual_rates["EUR"])
        .otherwise(pl.col(amount_col))
        .alias(eur_col)
    )
