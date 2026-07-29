"""Classify withholding taxes using explicit ISIN-based tax rules."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

import polars as pl

CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER = 1.055

FUND_FORM = "Anlage KAP-INV"
DOMESTIC_SHARE_FORM = "Anlage KAP inländisch"
FOREIGN_SHARE_FORM = "Anlage KAP ausländisch"


@dataclass(frozen=True)
class SecurityTaxRule:
    """Tax treatment for dividends from one security."""

    source_country: str
    tax_treatment: str
    max_creditable_rate: float
    instrument: str = "share"


class SecurityTaxRules(dict[str, SecurityTaxRule]):
    """Tax rules with exact ISIN rules taking precedence over ISIN prefixes."""

    def __init__(
        self,
        rules: dict[str, SecurityTaxRule] | None = None,
        country_rules: dict[str, SecurityTaxRule] | None = None,
    ) -> None:
        super().__init__(rules or {})
        self.country_rules = country_rules if country_rules is not None else {}

    def get(self, isin: str, default: SecurityTaxRule | None = None) -> SecurityTaxRule | None:
        return super().get(isin, self.country_rules.get(isin[:2], default))


@dataclass(frozen=True)
class WithholdingTaxSummary:
    """Amounts split by their German tax treatment."""

    foreign_creditable: float = 0.0
    foreign_excess: float = 0.0
    domestic: float = 0.0
    domestic_capital_gains_tax: float = 0.0
    domestic_solidarity_surcharge: float = 0.0
    unclassified: float = 0.0

    def __add__(self, other: "WithholdingTaxSummary") -> "WithholdingTaxSummary":
        """Combine summaries from distinct transaction categories."""
        return WithholdingTaxSummary(
            foreign_creditable=self.foreign_creditable + other.foreign_creditable,
            foreign_excess=self.foreign_excess + other.foreign_excess,
            domestic=self.domestic + other.domestic,
            domestic_capital_gains_tax=self.domestic_capital_gains_tax + other.domestic_capital_gains_tax,
            domestic_solidarity_surcharge=self.domestic_solidarity_surcharge + other.domestic_solidarity_surcharge,
            unclassified=self.unclassified + other.unclassified,
        )


def _load_tax_rule(entry: dict[str, object], identifier: str) -> SecurityTaxRule:
    try:
        source_country = str(entry["source_country"]).upper()
        tax_treatment = str(entry["tax_treatment"])
        raw_max_creditable_rate = entry["max_creditable_rate"]
        if isinstance(raw_max_creditable_rate, bool) or not isinstance(raw_max_creditable_rate, (int, float, str)):
            raise TypeError
        max_creditable_rate = float(raw_max_creditable_rate)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"Jede Regel für {identifier} benötigt source_country, tax_treatment und max_creditable_rate"
        ) from error

    if tax_treatment not in {"domestic", "foreign"}:
        raise ValueError(f"Ungültige tax_treatment für {identifier}: {tax_treatment!r}")
    if not 0 <= max_creditable_rate <= 1:
        raise ValueError(f"max_creditable_rate für {identifier} muss zwischen 0 und 1 liegen")
    if tax_treatment == "domestic" and max_creditable_rate != 0:
        raise ValueError(f"Eine domestic-Regel für {identifier} muss max_creditable_rate = 0 setzen")

    instrument = str(entry.get("instrument", "share")).lower()
    if instrument not in {"fund", "share"}:
        raise ValueError(f"Ungültige instrument-Angabe für {identifier}: {instrument!r} (erlaubt: fund, share)")

    return SecurityTaxRule(source_country, tax_treatment, max_creditable_rate, instrument)


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
    for entry in config.get("country", []):
        try:
            isin_prefix = str(entry["isin_prefix"]).upper()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Jede [[country]]-Regel benötigt isin_prefix") from error

        if len(isin_prefix) != 2 or not isin_prefix.isalpha():
            raise ValueError(f"isin_prefix muss aus genau zwei Buchstaben bestehen: {isin_prefix!r}")
        if isin_prefix in country_rules:
            raise ValueError(f"ISIN-Präfix {isin_prefix} ist mehrfach in der Regeldatei definiert")

        country_rules[isin_prefix] = _load_tax_rule(entry, f"ISIN-Präfix {isin_prefix}")

    for entry in config.get("security", []):
        try:
            isin = str(entry["isin"]).upper()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Jede [[security]]-Regel benötigt isin") from error
        if isin in rules:
            raise ValueError(f"ISIN {isin} ist mehrfach in der Regeldatei definiert")

        rules[isin] = _load_tax_rule(entry, f"ISIN {isin}")

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
    """
    forms: list[str] = []
    for row in dataframe.iter_rows(named=True):
        isin = str(row.get(isin_col) or "").upper()
        rule = rules.get(isin)
        if rule and rule.instrument == "fund":
            forms.append(FUND_FORM)
            continue
        source_country = rule.source_country if rule else isin[:2]
        forms.append(DOMESTIC_SHARE_FORM if source_country == "DE" else FOREIGN_SHARE_FORM)
    return dataframe.with_columns(pl.Series("Formular", forms, dtype=pl.String))


def classify_embedded_withholding_taxes(
    dataframe: pl.DataFrame,
    rules: SecurityTaxRules,
    isin_col: str,
    income_eur_col: str,
    withholding_tax_eur_col: str,
) -> tuple[pl.DataFrame, WithholdingTaxSummary]:
    """Classify tax embedded in an income row and cap foreign credit by gross income."""
    if withholding_tax_eur_col not in dataframe.columns:
        return dataframe, WithholdingTaxSummary()

    source_countries: list[str | None] = []
    treatments: list[str] = []
    creditable_amounts: list[float] = []
    excess_amounts: list[float] = []
    domestic_amounts: list[float] = []
    domestic_capital_gains_tax_amounts: list[float] = []
    domestic_solidarity_surcharge_amounts: list[float] = []
    unclassified_amounts: list[float] = []

    for row in dataframe.iter_rows(named=True):
        raw_tax = abs(float(row[withholding_tax_eur_col] or 0.0))
        isin = str(row.get(isin_col) or "").upper()
        rule = rules.get(isin)
        source_countries.append(rule.source_country if rule else None)

        creditable = 0.0
        excess = 0.0
        domestic = 0.0
        domestic_capital_gains_tax = 0.0
        domestic_solidarity_surcharge = 0.0
        unclassified = 0.0
        if raw_tax == 0:
            treatment = "none"
        elif rule is None:
            treatment = "unclassified"
            unclassified = raw_tax
        elif rule.tax_treatment == "domestic":
            treatment = "domestic"
            domestic = raw_tax
            domestic_capital_gains_tax = domestic / CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER
            domestic_solidarity_surcharge = domestic - domestic_capital_gains_tax
        else:
            treatment = "foreign"
            gross_income = abs(float(row[income_eur_col] or 0.0)) + raw_tax
            creditable = min(raw_tax, gross_income * rule.max_creditable_rate)
            excess = raw_tax - creditable

        treatments.append(treatment)
        creditable_amounts.append(creditable)
        excess_amounts.append(excess)
        domestic_amounts.append(domestic)
        domestic_capital_gains_tax_amounts.append(domestic_capital_gains_tax)
        domestic_solidarity_surcharge_amounts.append(domestic_solidarity_surcharge)
        unclassified_amounts.append(unclassified)

    classified = dataframe.with_columns(
        pl.Series("Quellenstaat", source_countries, dtype=pl.String),
        pl.Series("Steuerbehandlung", treatments),
        pl.Series("Anrechenbare_Quellensteuer_EUR", creditable_amounts),
        pl.Series("Nicht_anrechenbare_Quellensteuer_EUR", excess_amounts),
        pl.Series("Inlaendische_Kapitalertragsteuer_EUR", domestic_capital_gains_tax_amounts),
        pl.Series("Solidaritaetszuschlag_EUR", domestic_solidarity_surcharge_amounts),
        pl.Series("Nicht_klassifizierte_Steuer_EUR", unclassified_amounts),
    )
    return classified, WithholdingTaxSummary(
        foreign_creditable=sum(creditable_amounts),
        foreign_excess=sum(excess_amounts),
        domestic=sum(domestic_amounts),
        domestic_capital_gains_tax=sum(domestic_capital_gains_tax_amounts),
        domestic_solidarity_surcharge=sum(domestic_solidarity_surcharge_amounts),
        unclassified=sum(unclassified_amounts),
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
    """
    if tax_eur_col not in dataframe.columns:
        return dataframe, WithholdingTaxSummary()

    source_countries: list[str | None] = []
    treatments: list[str] = []
    domestic_amounts: list[float] = []
    domestic_capital_gains_tax_amounts: list[float] = []
    domestic_solidarity_surcharge_amounts: list[float] = []
    unclassified_amounts: list[float] = []
    for row in dataframe.iter_rows(named=True):
        raw_tax = abs(float(row[tax_eur_col] or 0.0))
        isin = str(row.get(isin_col) or "").upper()
        rule = rules.get(isin)
        source_countries.append(rule.source_country if rule else None)

        domestic = 0.0
        domestic_capital_gains_tax = 0.0
        domestic_solidarity_surcharge = 0.0
        unclassified = 0.0
        if raw_tax == 0:
            treatment = "none"
        elif rule and rule.tax_treatment == "domestic":
            treatment = "domestic"
            domestic = raw_tax
            domestic_capital_gains_tax = domestic / CAPITAL_GAINS_TAX_WITH_SOLIDARITY_MULTIPLIER
            domestic_solidarity_surcharge = domestic - domestic_capital_gains_tax
        elif rule and rule.tax_treatment == "foreign":
            treatment = "foreign_without_gross_income"
            unclassified = raw_tax
        else:
            treatment = "unclassified"
            unclassified = raw_tax

        treatments.append(treatment)
        domestic_amounts.append(domestic)
        domestic_capital_gains_tax_amounts.append(domestic_capital_gains_tax)
        domestic_solidarity_surcharge_amounts.append(domestic_solidarity_surcharge)
        unclassified_amounts.append(unclassified)

    classified = dataframe.with_columns(
        pl.Series("Quellenstaat", source_countries, dtype=pl.String),
        pl.Series("Steuerbehandlung", treatments),
        pl.lit(0.0).alias("Anrechenbare_Quellensteuer_EUR"),
        pl.lit(0.0).alias("Nicht_anrechenbare_Quellensteuer_EUR"),
        pl.Series("Inlaendische_Kapitalertragsteuer_EUR", domestic_capital_gains_tax_amounts),
        pl.Series("Solidaritaetszuschlag_EUR", domestic_solidarity_surcharge_amounts),
        pl.Series("Nicht_klassifizierte_Steuer_EUR", unclassified_amounts),
    )
    return classified, WithholdingTaxSummary(
        domestic=sum(domestic_amounts),
        domestic_capital_gains_tax=sum(domestic_capital_gains_tax_amounts),
        domestic_solidarity_surcharge=sum(domestic_solidarity_surcharge_amounts),
        unclassified=sum(unclassified_amounts),
    )
