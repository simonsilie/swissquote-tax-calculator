"""Classify withholding taxes using explicit ISIN-based tax rules."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

import polars as pl
from loguru import logger

from typing import overload

CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER = 1.055

FUND_FORM = "Anlage KAP-INV"
DOMESTIC_SHARE_FORM = "Anlage KAP inländisch"
FOREIGN_SHARE_FORM = "Anlage KAP ausländisch"

TEILFREISTELLUNG_RATES: dict[str, float] = {
    "equity": 0.30,
    "mixed": 0.15,
    "real_estate": 0.60,
    "other": 0.00,
}


@dataclass(frozen=True)
class SecurityTaxRule:
    """Tax treatment for dividends from one security."""

    source_country: str
    tax_treatment: str
    max_creditable_rate: float
    instrument: str = "share"
    fund_type: str | None = None


class SecurityTaxRules(dict[str, SecurityTaxRule]):
    """Tax rules with exact ISIN rules taking precedence over ISIN prefixes."""

    def __init__(
        self,
        rules: dict[str, SecurityTaxRule] | None = None,
        country_rules: dict[str, SecurityTaxRule] | None = None,
    ) -> None:
        super().__init__(rules or {})
        self.country_rules = country_rules if country_rules is not None else {}

    @overload
    def get(self, key: str, default: None = None, /) -> SecurityTaxRule | None: ...

    @overload
    def get(self, key: str, default: SecurityTaxRule, /) -> SecurityTaxRule: ...

    @overload
    def get[T](self, key: str, default: T, /) -> SecurityTaxRule | T: ...

    def get(self, key: str, default: object = None, /) -> object:
        if not key:
            return default
        rule = self._resolve_rule(key)
        if rule is not None:
            return rule
        logger.debug(f"ISIN {key} without explicit rule and no resolvable ISIN prefix")
        return default

    def _resolve_rule(self, isin: str) -> SecurityTaxRule | None:
        """Resolve the rule for a single ISIN.

        Lookup order: exact ISIN rule, two-letter ISIN prefix (country) rule,
        then built-in defaults (DE domestic, otherwise foreign with 15%
        creditable rate).
        """
        if not isin:
            return None
        isin_upper = isin.upper()
        rule = super().get(isin_upper, self.country_rules.get(isin_upper[:2]))
        if rule is not None:
            return rule
        prefix = isin_upper[:2]
        if len(prefix) == 2 and prefix.isalpha():
            if prefix == "DE":
                return SecurityTaxRule(source_country="DE", tax_treatment="domestic", max_creditable_rate=0.0)
            logger.debug(f"ISIN {isin} without explicit rule — classified as foreign {prefix} stock (15% creditable)")
            return SecurityTaxRule(source_country=prefix, tax_treatment="foreign", max_creditable_rate=0.15)
        return None

    def get_rules_for_isins(self, isins: pl.Series, isin_col_name: str = "isin") -> pl.DataFrame:
        """
        Vectorized rule lookup for a Polars Series of ISINs.

        Returns a DataFrame with columns:
        - {isin_col_name}: the original ISIN (same name as input column)
        - source_country: resolved source country (or None)
        - tax_treatment: "domestic", "foreign", or None
        - max_creditable_rate: float (or 0.0 if None)
        - instrument: "fund" or "share" (or "share" if None)
        - fund_type: fund type string or None
        """
        # Convert to list for processing (small overhead, but avoids complex Polars UDF)
        isin_list = isins.to_list()

        results = []
        for isin in isin_list:
            rule = self._resolve_rule(str(isin) if isin else "")
            if rule:
                results.append({
                    isin_col_name: isin,
                    "source_country": rule.source_country,
                    "tax_treatment": rule.tax_treatment,
                    "max_creditable_rate": rule.max_creditable_rate,
                    "instrument": rule.instrument,
                    "fund_type": rule.fund_type,
                })
            else:
                results.append({
                    isin_col_name: isin,
                    "source_country": None,
                    "tax_treatment": None,
                    "max_creditable_rate": 0.0,
                    "instrument": "share",
                    "fund_type": None,
                })

        if results:
            return pl.DataFrame(results)
        # Empty case: return DataFrame with correct schema but no rows
        return pl.DataFrame(schema={
            isin_col_name: pl.String,
            "source_country": pl.String,
            "tax_treatment": pl.String,
            "max_creditable_rate": pl.Float64,
            "instrument": pl.String,
            "fund_type": pl.String,
        })


@dataclass(frozen=True)
class WithholdingTaxSummary:
    """Amounts split by their German tax treatment."""

    foreign_creditable: float = 0.0
    foreign_excess: float = 0.0
    domestic: float = 0.0
    domestic_capital_gains_tax: float = 0.0
    domestic_solidarity_surcharge: float = 0.0
    unclassified: float = 0.0
    foreign_creditable_by_country: tuple[tuple[str, float], ...] = ()
    swiss_refundable: float = 0.0

    def __add__(self, other: "WithholdingTaxSummary") -> "WithholdingTaxSummary":
        """Combine summaries from distinct transaction categories."""
        return WithholdingTaxSummary(
            foreign_creditable=self.foreign_creditable + other.foreign_creditable,
            foreign_excess=self.foreign_excess + other.foreign_excess,
            domestic=self.domestic + other.domestic,
            domestic_capital_gains_tax=self.domestic_capital_gains_tax + other.domestic_capital_gains_tax,
            domestic_solidarity_surcharge=self.domestic_solidarity_surcharge + other.domestic_solidarity_surcharge,
            unclassified=self.unclassified + other.unclassified,
            foreign_creditable_by_country=tuple(
                sorted(
                    {
                        country: sum(
                            a
                            for c, a in self.foreign_creditable_by_country + other.foreign_creditable_by_country
                            if c == country
                        )
                        for country, _ in self.foreign_creditable_by_country + other.foreign_creditable_by_country
                    }.items()
                )
            ),
            swiss_refundable=self.swiss_refundable + other.swiss_refundable,
        )


def _load_tax_rule(entry: dict[str, object], identifier: str) -> SecurityTaxRule:
    try:
        source_country = str(entry["source_country"]).upper()
        tax_treatment = str(entry["tax_treatment"])
        raw_max_creditable_rate = entry["max_creditable_rate"]
        if isinstance(raw_max_creditable_rate, bool) or not isinstance(raw_max_creditable_rate, (int, float, str)):
            raise ValueError(
                f"max_creditable_rate für {identifier} hat ungültigen Typ: {type(raw_max_creditable_rate).__name__}"
            )
        max_creditable_rate = float(raw_max_creditable_rate)
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"Jede Regel für {identifier} benötigt source_country, tax_treatment und max_creditable_rate"
        ) from error

    if tax_treatment not in {"domestic", "foreign"}:
        raise ValueError(f"Ungültige tax_treatment für {identifier}: {tax_treatment!r}")
    if not 0 <= max_creditable_rate <= 1:
        raise ValueError(f"max_creditable_rate für {identifier} muss zwischen 0 und 1 liegen")
    if tax_treatment == "domestic" and max_creditable_rate != 0:
        raise ValueError(f"Eine domestic-Regel für {identifier} muss max_creditable_rate = 0 setzen")

    if "instrument" not in entry:
        logger.debug(f"Instrument not specified for {identifier}, defaulting to 'share'")
    instrument = str(entry.get("instrument", "share")).lower()
    if instrument not in {"fund", "share"}:
        raise ValueError(f"Ungültige instrument-Angabe für {identifier}: {instrument!r} (erlaubt: fund, share)")

    fund_type: str | None = None
    if "fund_type" in entry:
        raw_fund_type = str(entry["fund_type"]).lower()
        valid_fund_types = {"equity", "mixed", "real_estate", "other"}
        if raw_fund_type not in valid_fund_types:
            raise ValueError(
                f"Ungültige fund_type-Angabe für {identifier}: {raw_fund_type!r} "
                f"(erlaubt: {', '.join(sorted(valid_fund_types))})"
            )
        if instrument != "fund":
            raise ValueError(f"fund_type für {identifier} ist nur für instrument='fund' erlaubt")
        fund_type = raw_fund_type

    return SecurityTaxRule(source_country, tax_treatment, max_creditable_rate, instrument, fund_type)


def load_security_tax_rules(path: Path | None) -> SecurityTaxRules:
    """Load tax rules keyed by exact ISIN or a two-letter ISIN prefix."""
    if path is None:
        return SecurityTaxRules()

    try:
        with path.open("rb") as file:
            config = tomllib.load(file)
    except FileNotFoundError as error:
        raise ValueError(f"Regeldatei '{path}' nicht gefunden") from error
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"Ungültige TOML-Regeldatei '{path}': {error}") from error

    country_rules: dict[str, SecurityTaxRule] = {}
    rules = SecurityTaxRules(country_rules=country_rules)
    country_entries = config.get("country", [])
    for entry in country_entries:
        try:
            isin_prefix = str(entry["isin_prefix"]).upper()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Jede [[country]]-Regel benötigt isin_prefix") from error

        if len(isin_prefix) != 2 or not isin_prefix.isalpha():
            raise ValueError(f"isin_prefix muss aus genau zwei Buchstaben bestehen: {isin_prefix!r}")
        if isin_prefix in country_rules:
            raise ValueError(f"ISIN-Präfix {isin_prefix} ist mehrfach in der Regeldatei definiert")

        country_rules[isin_prefix] = _load_tax_rule(entry, f"ISIN-Präfix {isin_prefix}")

    security_entries = config.get("security", [])
    for entry in security_entries:
        try:
            isin = str(entry["isin"]).upper()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Jede [[security]]-Regel benötigt isin") from error
        if isin in rules:
            raise ValueError(f"ISIN {isin} ist mehrfach in der Regeldatei definiert")

        rules[isin] = _load_tax_rule(entry, f"ISIN {isin}")

    if not country_entries and not security_entries:
        logger.warning(f"No withholding tax rules loaded from '{path}'")

    return rules


def tag_dividend_forms(
    dataframe: pl.DataFrame,
    rules: SecurityTaxRules,
    isin_col: str,
) -> pl.DataFrame:
    """Label each dividend row with its German form.

    Securities flagged ``instrument = "fund"`` map to Anlage KAP-INV. Remaining
    holdings are ordinary shares in Anlage KAP, split by source country: German
    shares are domestic capital income, every other share is foreign. The source
    country comes from a matching rule, otherwise from the two-letter ISIN prefix.
    Fund rows also receive a ``Fundart`` label for Teilfreistellung grouping.
    """
    if dataframe.is_empty():
        return dataframe.with_columns(
            pl.Series("Formular", [], dtype=pl.String),
            pl.Series("Fundart", [], dtype=pl.String),
        )

    if isin_col in dataframe.columns:
        isin_series = dataframe[isin_col]
    else:
        isin_series = pl.Series([None] * dataframe.height, dtype=pl.String)
    rules_df = rules.get_rules_for_isins(isin_series, isin_col)
    rules_only = rules_df.drop(isin_col)
    instrument = pl.col("instrument").fill_null("share")
    return dataframe.with_columns(rules_only).with_columns(
        pl.when(instrument == "fund")
        .then(pl.lit(FUND_FORM))
        .otherwise(
            pl.when(pl.col("source_country").fill_null("").str.to_uppercase() == "DE")
            .then(pl.lit(DOMESTIC_SHARE_FORM))
            .otherwise(pl.lit(FOREIGN_SHARE_FORM))
        )
        .alias("Formular"),
        pl.when(instrument == "fund")
        .then(pl.col("fund_type"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias("Fundart"),
    )


def classify_embedded_withholding_taxes(
    dataframe: pl.DataFrame,
    rules: SecurityTaxRules,
    isin_col: str,
    income_eur_col: str,
    withholding_tax_eur_col: str,
) -> tuple[pl.DataFrame, WithholdingTaxSummary]:
    """Classify tax embedded in an income row and cap foreign credit by gross income.

    Vectorized implementation using Polars expressions for performance.
    """
    if withholding_tax_eur_col not in dataframe.columns:
        return dataframe, WithholdingTaxSummary()

    # Get rules for all ISINs in one vectorized call; a missing ISIN column
    # behaves like rows without an ISIN (everything unclassified).
    if isin_col in dataframe.columns:
        isin_series = dataframe[isin_col]
    else:
        isin_series = pl.Series([None] * dataframe.height, dtype=pl.String)
    rules_df = rules.get_rules_for_isins(isin_series, isin_col)

    # Join rules back to the dataframe. When the ISIN column exists in the
    # input, drop it from the rules to avoid a duplicate column; when it is
    # missing, keep the null-filled copy and drop it after the hstack to
    # keep the output schema identical to the input schema.
    if isin_col in dataframe.columns:
        df_with_rules = dataframe.hstack(rules_df.drop(isin_col))
    else:
        df_with_rules = dataframe.hstack(rules_df).drop(isin_col)

    # Compute raw tax (absolute value, null -> 0)
    df_with_rules = df_with_rules.with_columns(
        pl.col(withholding_tax_eur_col).abs().fill_null(0.0).alias("_raw_tax"),
        pl.col(income_eur_col).abs().fill_null(0.0).alias("_gross_income"),
    )

    # Compute gross income = net income + raw tax
    df_with_rules = df_with_rules.with_columns(
        (pl.col("_gross_income") + pl.col("_raw_tax")).alias("_total_gross"),
    )

    # Step 1: Create source country and treatment classification
    df_with_rules = df_with_rules.with_columns(
        # Source country
        pl.col("source_country").alias("Quellenstaat"),
        # Treatment classification
        pl.when(pl.col("_raw_tax") == 0)
        .then(pl.lit("none"))
        .when(pl.col("tax_treatment").is_null())
        .then(pl.lit("unclassified"))
        .when(pl.col("tax_treatment") == "domestic")
        .then(pl.lit("domestic"))
        .otherwise(pl.lit("foreign"))
        .alias("Steuerbehandlung"),
    )

    # Step 2a: Compute creditable foreign tax (capped by gross income * max_creditable_rate)
    df_with_rules = df_with_rules.with_columns(
        pl.when(
            (pl.col("Steuerbehandlung") == "foreign") & (pl.col("_raw_tax") > 0)
        )
        .then(
            pl.min_horizontal(
                pl.col("_raw_tax"),
                pl.col("_total_gross") * pl.col("max_creditable_rate")
            )
        )
        .otherwise(0.0)
        .alias("Anrechenbare_Quellensteuer_EUR"),
    )

    # Step 2b: Compute remaining tax amounts using creditable tax
    df_with_rules = df_with_rules.with_columns(
        # Excess foreign tax
        pl.when(pl.col("Steuerbehandlung") == "foreign")
        .then(pl.col("_raw_tax") - pl.col("Anrechenbare_Quellensteuer_EUR"))
        .otherwise(0.0)
        .alias("Nicht_anrechenbare_Quellensteuer_EUR"),
        # Domestic tax
        pl.when(pl.col("Steuerbehandlung") == "domestic")
        .then(pl.col("_raw_tax"))
        .otherwise(0.0)
        .alias("_domestic_tax"),
        # Unclassified tax
        pl.when(pl.col("Steuerbehandlung") == "unclassified")
        .then(pl.col("_raw_tax"))
        .otherwise(0.0)
        .alias("Nicht_klassifizierte_Steuer_EUR"),
    )

    # Step 3: Split domestic tax into capital gains tax and solidarity surcharge
    df_with_rules = df_with_rules.with_columns(
        (pl.col("_domestic_tax") / CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER).alias("Inlaendische_Kapitalertragsteuer_EUR"),
        (pl.col("_domestic_tax") - (pl.col("_domestic_tax") / CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER)).alias("Solidaritaetszuschlag_EUR"),
    )

    # Step 4: Compute Swiss refundable (excess for CH)
    df_with_rules = df_with_rules.with_columns(
        pl.when(
            (pl.col("Steuerbehandlung") == "foreign") & (pl.col("source_country") == "CH")
        )
        .then(pl.col("Nicht_anrechenbare_Quellensteuer_EUR"))
        .otherwise(0.0)
        .alias("_swiss_refundable"),
    )

    # Aggregate summary values
    foreign_creditable = float(df_with_rules["Anrechenbare_Quellensteuer_EUR"].sum())
    foreign_excess = float(df_with_rules["Nicht_anrechenbare_Quellensteuer_EUR"].sum())
    domestic = float(df_with_rules["_domestic_tax"].sum())
    domestic_capital_gains_tax = float(df_with_rules["Inlaendische_Kapitalertragsteuer_EUR"].sum())
    domestic_solidarity_surcharge = float(df_with_rules["Solidaritaetszuschlag_EUR"].sum())
    unclassified = float(df_with_rules["Nicht_klassifizierte_Steuer_EUR"].sum())
    swiss_refundable = float(df_with_rules["_swiss_refundable"].sum())

    # Country breakdown for creditable foreign tax
    foreign_by_country = (
        df_with_rules.filter(pl.col("Steuerbehandlung") == "foreign")
        .group_by("source_country")
        .agg(pl.col("Anrechenbare_Quellensteuer_EUR").sum())
        .sort("source_country")
    )
    foreign_creditable_by_country = tuple(
        (row["source_country"], float(row["Anrechenbare_Quellensteuer_EUR"]))
        for row in foreign_by_country.iter_rows(named=True)
        if row["source_country"] is not None
    )

    # Drop temporary columns
    temp_cols = [
        "_raw_tax", "_gross_income", "_total_gross",
        "source_country", "tax_treatment", "max_creditable_rate",
        "instrument", "fund_type", "_domestic_tax", "_swiss_refundable",
    ]
    classified = df_with_rules.drop([c for c in temp_cols if c in df_with_rules.columns])

    return classified, WithholdingTaxSummary(
        foreign_creditable=foreign_creditable,
        foreign_excess=foreign_excess,
        domestic=domestic,
        domestic_capital_gains_tax=domestic_capital_gains_tax,
        domestic_solidarity_surcharge=domestic_solidarity_surcharge,
        unclassified=unclassified,
        foreign_creditable_by_country=foreign_creditable_by_country,
        swiss_refundable=swiss_refundable,
    )


def classify_standalone_withholding_taxes(
    dataframe: pl.DataFrame,
    rules: SecurityTaxRules,
    isin_col: str,
    tax_eur_col: str,
) -> tuple[pl.DataFrame, WithholdingTaxSummary]:
    """Classify separate tax bookings without treating foreign tax as creditable.

    A credit limit needs the associated gross income. Such bookings therefore remain
    unclassified until their tax is included in the income transaction itself.

    Vectorized implementation using Polars expressions for performance.
    """
    if tax_eur_col not in dataframe.columns:
        return dataframe, WithholdingTaxSummary()

    # Get rules for all ISINs in one vectorized call; a missing ISIN column
    # behaves like rows without an ISIN (everything unclassified).
    if isin_col in dataframe.columns:
        isin_series = dataframe[isin_col]
    else:
        isin_series = pl.Series([None] * dataframe.height, dtype=pl.String)
    rules_df = rules.get_rules_for_isins(isin_series, isin_col)

    # Join rules back to the dataframe. When the ISIN column exists in the
    # input, drop it from the rules to avoid a duplicate column; when it is
    # missing, keep the null-filled copy and drop it after the hstack to
    # keep the output schema identical to the input schema.
    if isin_col in dataframe.columns:
        df_with_rules = dataframe.hstack(rules_df.drop(isin_col))
    else:
        df_with_rules = dataframe.hstack(rules_df).drop(isin_col)

    # Compute raw tax (absolute value, null -> 0)
    df_with_rules = df_with_rules.with_columns(
        pl.col(tax_eur_col).abs().fill_null(0.0).alias("_raw_tax"),
    )

    # Classify each row using Polars expressions
    # Step 1: Create source country and treatment classification
    df_with_rules = df_with_rules.with_columns(
        # Source country
        pl.col("source_country").alias("Quellenstaat"),
        # Treatment classification
        pl.when(pl.col("_raw_tax") == 0)
        .then(pl.lit("none"))
        .when(pl.col("tax_treatment").is_null())
        .then(pl.lit("unclassified"))
        .when(pl.col("tax_treatment") == "domestic")
        .then(pl.lit("domestic"))
        .when(pl.col("tax_treatment") == "foreign")
        .then(pl.lit("foreign_without_gross_income"))
        .otherwise(pl.lit("unclassified"))
        .alias("Steuerbehandlung"),
    )

    # Step 2: Compute tax amounts using the treatment classification
    df_with_rules = df_with_rules.with_columns(
        # Domestic tax
        pl.when(pl.col("Steuerbehandlung") == "domestic")
        .then(pl.col("_raw_tax"))
        .otherwise(0.0)
        .alias("_domestic_tax"),
        # Unclassified tax (foreign without gross income or no rule)
        pl.when(pl.col("Steuerbehandlung").is_in(["unclassified", "foreign_without_gross_income"]))
        .then(pl.col("_raw_tax"))
        .otherwise(0.0)
        .alias("Nicht_klassifizierte_Steuer_EUR"),
    )

    # Split domestic tax into capital gains tax and solidarity surcharge
    df_with_rules = df_with_rules.with_columns(
        (pl.col("_domestic_tax") / CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER).alias("Inlaendische_Kapitalertragsteuer_EUR"),
        (pl.col("_domestic_tax") - (pl.col("_domestic_tax") / CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER)).alias("Solidaritaetszuschlag_EUR"),
    )

    # Creditable foreign tax is always 0 for standalone bookings
    df_with_rules = df_with_rules.with_columns(
        pl.lit(0.0).alias("Anrechenbare_Quellensteuer_EUR"),
        pl.lit(0.0).alias("Nicht_anrechenbare_Quellensteuer_EUR"),
    )

    # Aggregate summary values
    domestic = float(df_with_rules["_domestic_tax"].sum())
    domestic_capital_gains_tax = float(df_with_rules["Inlaendische_Kapitalertragsteuer_EUR"].sum())
    domestic_solidarity_surcharge = float(df_with_rules["Solidaritaetszuschlag_EUR"].sum())
    unclassified = float(df_with_rules["Nicht_klassifizierte_Steuer_EUR"].sum())
    swiss_refundable = 0.0  # No Swiss refundable for standalone bookings without gross income

    # Country breakdown for foreign standalone taxes (creditable = 0, tracked
    # for reporting which countries were seen without a gross-income match).
    foreign_countries = (
        df_with_rules.filter(pl.col("Steuerbehandlung") == "foreign_without_gross_income")
        .get_column("source_country")
        .unique()
        .drop_nulls()
        .sort()
        .to_list()
    )
    foreign_creditable_by_country = tuple((country, 0.0) for country in foreign_countries)

    # Drop temporary columns
    temp_cols = [
        "_raw_tax",
        "source_country", "tax_treatment", "max_creditable_rate",
        "instrument", "fund_type", "_domestic_tax",
    ]
    classified = df_with_rules.drop([c for c in temp_cols if c in df_with_rules.columns])

    return classified, WithholdingTaxSummary(
        domestic=domestic,
        domestic_capital_gains_tax=domestic_capital_gains_tax,
        domestic_solidarity_surcharge=domestic_solidarity_surcharge,
        unclassified=unclassified,
        foreign_creditable_by_country=foreign_creditable_by_country,
        swiss_refundable=swiss_refundable,
    )
