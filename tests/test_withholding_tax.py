from pathlib import Path

import polars as pl
import pytest

from taxes.withholding_tax import load_security_tax_rules
from taxes.withholding_tax import SecurityTaxRule, SecurityTaxRules, classify_embedded_withholding_taxes
from taxes.withholding_tax import DOMESTIC_SHARE_FORM, FOREIGN_SHARE_FORM, FUND_FORM, tag_dividend_forms


def test_load_security_tax_rules_reads_foreign_and_domestic_rules(tmp_path: Path) -> None:
    """TOML rules retain each security's country, treatment, and credit limit."""
    rules_file = tmp_path / "withholding-tax-rules.toml"
    rules_file.write_text(
        """[[security]]
isin = "DE0007164600"
source_country = "DE"
tax_treatment = "domestic"
max_creditable_rate = 0.0

[[security]]
isin = "CH0012032048"
source_country = "CH"
tax_treatment = "foreign"
max_creditable_rate = 0.15
""",
        encoding="utf-8",
    )

    rules = load_security_tax_rules(rules_file)

    assert rules["DE0007164600"].tax_treatment == "domestic"
    assert rules["CH0012032048"].source_country == "CH"
    assert rules["CH0012032048"].max_creditable_rate == 0.15


def test_load_security_tax_rules_rejects_domestic_credit(tmp_path: Path) -> None:
    """Domestic tax rules cannot designate a foreign-tax credit."""
    rules_file = tmp_path / "withholding-tax-rules.toml"
    rules_file.write_text(
        """[[security]]
isin = "DE0007164600"
source_country = "DE"
tax_treatment = "domestic"
max_creditable_rate = 0.15
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_creditable_rate = 0"):
        load_security_tax_rules(rules_file)


def test_load_security_tax_rules_uses_country_rule_and_allows_isin_override(tmp_path: Path) -> None:
    """Exact ISIN rules override the fallback derived from an ISIN prefix."""
    rules_file = tmp_path / "withholding-tax-rules.toml"
    rules_file.write_text(
        """[[country]]
isin_prefix = "CH"
source_country = "CH"
tax_treatment = "foreign"
max_creditable_rate = 0.15

[[security]]
isin = "CH0012032048"
source_country = "US"
tax_treatment = "foreign"
max_creditable_rate = 0.10
""",
        encoding="utf-8",
    )

    rules = load_security_tax_rules(rules_file)

    assert rules.get("CH0000000000") == SecurityTaxRule("CH", "foreign", 0.15)
    assert rules.get("CH0012032048") == SecurityTaxRule("US", "foreign", 0.10)


def test_load_security_tax_rules_rejects_invalid_country_prefix(tmp_path: Path) -> None:
    """Country defaults must use a two-letter ISIN prefix."""
    rules_file = tmp_path / "withholding-tax-rules.toml"
    rules_file.write_text(
        """[[country]]
isin_prefix = "CHE"
source_country = "CH"
tax_treatment = "foreign"
max_creditable_rate = 0.15
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="genau zwei Buchstaben"):
        load_security_tax_rules(rules_file)


def test_classify_embedded_withholding_taxes_applies_the_credit_limit() -> None:
    """Foreign tax is capped while domestic and unmapped taxes remain separate."""
    dataframe = pl.DataFrame(
        {
            "ISIN": ["CH0012032048", "DE0007164600", "UNMAPPED"],
            "Nettobetrag_EUR": [65.0, 73.625, 85.0],
            "Kosten_EUR": [-35.0, -26.375, -15.0],
        }
    )
    rules = SecurityTaxRules({
        "CH0012032048": SecurityTaxRule("CH", "foreign", 0.15),
        "DE0007164600": SecurityTaxRule("DE", "domestic", 0.0),
    })

    classified, summary = classify_embedded_withholding_taxes(
        dataframe,
        rules,
        "ISIN",
        "Nettobetrag_EUR",
        "Kosten_EUR",
    )

    assert summary.foreign_creditable == 15.0
    assert summary.foreign_excess == 20.0
    assert summary.domestic == 26.375
    assert summary.domestic_capital_gains_tax == 25.0
    assert summary.domestic_solidarity_surcharge == 1.375
    assert summary.unclassified == 15.0
    assert classified["Quellenstaat"].to_list() == ["CH", "DE", None]


def test_load_security_tax_rules_reads_the_instrument_flag(tmp_path: Path) -> None:
    """The optional instrument flag distinguishes funds from ordinary shares."""
    rules_file = tmp_path / "withholding-tax-rules.toml"
    rules_file.write_text(
        """[[security]]
isin = "IE00B3RBWM25"
source_country = "IE"
tax_treatment = "foreign"
max_creditable_rate = 0.0
instrument = "fund"

[[security]]
isin = "DE0007164600"
source_country = "DE"
tax_treatment = "domestic"
max_creditable_rate = 0.0
""",
        encoding="utf-8",
    )

    rules = load_security_tax_rules(rules_file)

    assert rules["IE00B3RBWM25"].instrument == "fund"
    assert rules["DE0007164600"].instrument == "share"


def test_load_security_tax_rules_rejects_unknown_instrument(tmp_path: Path) -> None:
    """Only fund and share are valid instrument values."""
    rules_file = tmp_path / "withholding-tax-rules.toml"
    rules_file.write_text(
        """[[security]]
isin = "IE00B3RBWM25"
source_country = "IE"
tax_treatment = "foreign"
max_creditable_rate = 0.0
instrument = "bond"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="instrument"):
        load_security_tax_rules(rules_file)


def test_tag_dividend_forms_splits_funds_domestic_and_foreign_shares() -> None:
    """Funds map to KAP-INV; shares split into German (domestic) and foreign shares."""
    dataframe = pl.DataFrame({"ISIN": ["IE00B3RBWM25", "DE0007164600", "CH0038863350", "FR0000121014"]})
    rules = SecurityTaxRules(
        {
            "IE00B3RBWM25": SecurityTaxRule("IE", "foreign", 0.0, "fund"),
            "DE0007164600": SecurityTaxRule("DE", "domestic", 0.0),
            "CH0038863350": SecurityTaxRule("CH", "foreign", 0.15),
        }
    )

    tagged = tag_dividend_forms(dataframe, rules, "ISIN")

    assert tagged["Formular"].to_list() == [
        FUND_FORM,
        DOMESTIC_SHARE_FORM,
        FOREIGN_SHARE_FORM,
        FOREIGN_SHARE_FORM,
    ]