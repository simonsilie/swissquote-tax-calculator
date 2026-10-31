from pathlib import Path

import polars as pl
from taxes.elster_export import export_elster_mapping
from taxes.withholding_tax import WithholdingTaxSummary


def test_zeile_19_includes_stock_gains(tmp_path: Path) -> None:
    """Sale gains belong in the line 19 total, not only in the gains subfield."""
    fund_dividends = pl.DataFrame(schema={"Formular": pl.String, "Fundart": pl.String})

    md_path = export_elster_mapping(
        output_dir=tmp_path,
        tax_year=2025,
        total_domestic_share_dividends=0.0,
        total_foreign_share_dividends=200.0,
        total_interest=50.0,
        total_fund_dividends=0.0,
        withholding_tax_summary=WithholdingTaxSummary(),
        stock_gains=150.0,
        stock_losses=-30.0,
        fund_dividends=fund_dividends,
        round_amount=False,
    )

    content = md_path.read_text(encoding="utf-8")
    assert "> **Übertragen Sie `400.00 EUR` in Anlage KAP → Zeile 19**" in content
    assert "+ Ausländische Zinsen 50.00 EUR" in content
    assert "  + Aktiengewinne 150.00 EUR (Zeile 20)" in content
    assert "| Anlage KAP | 19 | Ausländische Kapitalerträge | 400.00 EUR |" in content


def test_export_elster_mapping_uses_utf8_characters(tmp_path: Path) -> None:
    summary = WithholdingTaxSummary(
        domestic_capital_gains_tax=10.0,
        domestic_solidarity_surcharge=0.55,
        foreign_creditable=15.0,
        foreign_excess=5.0,
        swiss_refundable=20.0,
        foreign_creditable_by_country=(("US", 15.0),),
    )

    fund_df = pl.DataFrame(
        {
            "Formular": ["Anlage KAP-INV"],
            "Fundart": ["equity"],
            "Bruttobetrag_EUR": [100.0],
        }
    )

    md_path = export_elster_mapping(
        output_dir=tmp_path,
        tax_year=2025,
        total_domestic_share_dividends=100.0,
        total_foreign_share_dividends=200.0,
        total_interest=50.0,
        total_fund_dividends=100.0,
        withholding_tax_summary=summary,
        stock_gains=150.0,
        stock_losses=-30.0,
        fund_dividends=fund_df,
        round_amount=True,
    )

    content = md_path.read_text(encoding="utf-8")

    # Verify real UTF-8 characters are present
    assert "—" in content
    assert "→" in content
    assert "übertragen" in content or "Übertragen" in content
    assert "Kapitalerträge" in content
    assert "Ausschüttungen" in content
    assert "| Anlage KAP | 20 | Aktiengewinne |" in content
    assert "| Anlage KAP | 23 | Aktienverluste |" in content

    # Verify no HTML entities remain
    assert "&mdash;" not in content
    assert "&uuml;" not in content
    assert "&auml;" not in content
    assert "&ouml;" not in content
    assert "&szlig;" not in content
    assert "&rarr;" not in content
    assert "&#220;" not in content
