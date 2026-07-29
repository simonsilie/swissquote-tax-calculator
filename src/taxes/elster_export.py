import shutil
from pathlib import Path

import markdown
import polars as pl
import weasyprint
from loguru import logger

from taxes.withholding_tax import TEILFREISTELLUNG_RATES, WithholdingTaxSummary

FUND_TYPE_LABELS: dict[str, str] = {
    "equity": "Aktienfonds (\u226551% Aktien)",
    "mixed": "Mischfonds (\u226525% Aktien)",
    "real_estate": "Immobilienfonds (\u226551% Immobilien)",
    "other": "Sonstige Fonds",
}
FUND_TYPE_MARKDOWN_LABELS: dict[str, str] = {
    "equity": "Aktienfonds (≥51% Aktien)",
    "mixed": "Mischfonds (≥25% Aktien)",
    "real_estate": "Immobilienfonds (≥51% Immobilien)",
    "other": "Sonstige Fonds",
}


def _fmt(value: float, round_amount: bool) -> str:
    if round_amount:
        return f"{round(value)} EUR"
    return f"{value:.2f} EUR"


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _generate_markdown(
    output_dir: Path,
    tax_year: int,
    total_domestic_share_dividends: float,
    total_foreign_share_dividends: float,
    total_interest: float,
    total_fund_dividends: float,
    withholding_tax_summary: WithholdingTaxSummary,
    stock_gains: float,
    stock_losses: float,
    fund_dividends: pl.DataFrame,
    round_amount: bool,
) -> Path:
    lines: list[str] = [
        f"# ELSTER Tax Mapping Guide — Steuerjahr {tax_year}",
        "",
        "> **Anleitung:** Die folgenden Beträge exakt wie angegeben in die ELSTER-Formulare übertragen.",
        "",
        "---",
        "",
        "## 1. Anlage KAP — Allgemeine Kapitalerträge",
        "",
    ]

    foreign_capital_income = total_foreign_share_dividends + total_interest

    lines.extend(
        [
            "### Zeile 18 — Inländische Kapitalerträge (deutsche Aktien)",
            "",
            f"> **Übertragen Sie `{_fmt(total_domestic_share_dividends, round_amount)}` in Anlage KAP → Zeile 18**",
            "",
            "### Zeile 19 — Ausländische Kapitalerträge",
            "",
            f"> **Übertragen Sie `{_fmt(foreign_capital_income, round_amount)}` in Anlage KAP → Zeile 19**",
            "",
            f"> = Ausländische Dividenden {_fmt(total_foreign_share_dividends, round_amount)}"
            f" + Ausländische Zinsen {_fmt(total_interest, round_amount)}",
            "",
        ]
    )

    if (
        withholding_tax_summary.domestic_capital_gains_tax > 0
        or withholding_tax_summary.domestic_solidarity_surcharge > 0
    ):
        lines.extend(
            [
                "### Zeile 37 — Kapitalertragsteuer (deutsche ISINs)",
                "",
                f"> **Übertragen Sie `{_fmt(withholding_tax_summary.domestic_capital_gains_tax, round_amount)}`"
                " in Anlage KAP → Zeile 37**",
                "",
                "### Zeile 38 — Solidaritätszuschlag (deutsche ISINs)",
                "",
                f"> **Übertragen Sie `{_fmt(withholding_tax_summary.domestic_solidarity_surcharge, round_amount)}`"
                " in Anlage KAP → Zeile 38**",
                "",
                "**Summe deutsche Kapitalertragsteuer einschließlich Soli:**"
                f" {_fmt(withholding_tax_summary.domestic, round_amount)}",
                "",
            ]
        )

    lines.extend(
        [
            "### Zeile 41 — Anrechenbare ausländische Quellensteuer",
            "",
            f"> **Übertragen Sie `{_fmt(withholding_tax_summary.foreign_creditable, round_amount)}`"
            " in Anlage KAP → Zeile 41**",
            "",
            "Aufteilung nach Ländern (DBA-Höchstsatz max. 15% je Land):",
            "",
        ]
    )

    if withholding_tax_summary.foreign_creditable_by_country:
        lines.append("| Land | Anrechenbare Quellensteuer |")
        lines.append("|------|---------------------------|")
        for country, amount in withholding_tax_summary.foreign_creditable_by_country:
            lines.append(f"| {country} | {_fmt(amount, round_amount)} |")
        lines.append("")
    else:
        lines.append("Keine anrechenbaren ausländischen Quellensteuern vorhanden.")
        lines.append("")

    if withholding_tax_summary.foreign_excess > 0:
        lines.append(
            f"**Nicht anrechenbarer Steuerüberhang:** {_fmt(withholding_tax_summary.foreign_excess, round_amount)}"
        )
        lines.append("")

    if stock_gains != 0 or stock_losses != 0:
        lines.extend(
            [
                "### Zeile 20 / 23 — Aktienveräußerungen",
                "",
                "In den Kapitalerträgen ohne inländischen Steuerabzug, Aktien-Unterzeilen laut Formular:",
                "",
            ]
        )
        if stock_gains > 0:
            lines.append(f"> **Aktiengewinne (Zeile 20): `{_fmt(stock_gains, round_amount)}`**")
        if stock_losses < 0:
            lines.append(f"> **Aktienverluste (Zeile 23): `{_fmt(stock_losses, round_amount)}`**")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## 2. Anlage KAP-INV — Investmentfonds / ETFs",
            "",
            "### Zeile 4 — Ausschüttungen",
            "",
            f"> **Übertragen Sie `{_fmt(total_fund_dividends, round_amount)}`**"
            " **in Anlage KAP-INV → Zeile 4 (Bruttoausschüttung)**",
            "",
        ]
    )

    fund_dividends_data = fund_dividends.filter(pl.col("Formular") == "Anlage KAP-INV")
    if not fund_dividends_data.is_empty():
        lines.append("### Aufteilung nach Fondsart (Teilfreistellung)")
        lines.append("")

        fund_totals: dict[str, float] = {}
        for row in fund_dividends_data.iter_rows(named=True):
            ft = row.get("Fundart")
            key = str(ft) if ft is not None else "other"
            gross = float(row.get("Bruttobetrag_EUR") or 0.0)
            fund_totals[key] = fund_totals.get(key, 0.0) + gross

        if fund_totals:
            lines.append("| Fondsart | Teilfreistellung | Bruttoausschüttung | Steuerpflichtig |")
            lines.append("|----------|-----------------|------------------------|-----------------|")
            for ft, total in sorted(fund_totals.items()):
                rate = TEILFREISTELLUNG_RATES.get(ft, 0.0)
                taxable = total * (1.0 - rate)
                label = FUND_TYPE_MARKDOWN_LABELS.get(ft, f"Fonds (Typ: {ft})")
                lines.append(
                    f"| {label} | {_pct(rate)} | {_fmt(total, round_amount)} | {_fmt(taxable, round_amount)} |"
                )
            lines.append("")

            lines.append(
                "**Hinweis:** Die Teilfreistellung wird in Zeile 12 der Anlage KAP-INV eingetragen."
                " Obige steuerpflichtige Summe dient als Kontrollwert."
            )
            lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## 3. Rückforderung Schweizer Verrechnungssteuer (Nicht-ELSTER)",
            "",
        ]
    )

    if withholding_tax_summary.swiss_refundable > 0:
        lines.extend(
            [
                f"> **Rückforderbarer Betrag: `{_fmt(withholding_tax_summary.swiss_refundable, round_amount)}`**",
                "",
                "Die Schweizer Verrechnungssteuer wird bei Schweizer Titeln (CH-ISIN) mit 35% auf"
                " Ausschüttungen erhoben. Davon sind gemäß DBA Schweiz-Deutschland"
                " maximal 15% in Zeile 41 der Anlage KAP anrechenbar. Die verbleibenden 20%"
                " müssen **separat** über das Formular eF85 direkt bei der"
                " **Eidgenössischen Steuerverwaltung (ESTV)** zurückgefordert werden.",
                "",
                "**Vorgehen:**",
                "1. Formular eF85 online ausfüllen: [www.estv.admin.ch](https://www.estv.admin.ch)",
                "2. Belege der Schweizer Depotbank (Swissquote) über einbehaltene Verrechnungssteuer beifügen",
                "3. Ansässigkeitsbescheinigung des deutschen Finanzamts (Formular S1/RZ-430) einreichen",
                "4. Antragsfrist: 3 Jahre nach Ablauf des Kalenderjahres der Fälligkeit",
                "",
            ]
        )
    else:
        lines.append("Keine Schweizer Verrechnungssteuer über die 15%-DBA-Grenze hinaus angefallen.")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## 4. Zusammenfassung — Alle ELSTER-Werte auf einen Blick",
            "",
            "| Formular | Zeile | Bezeichnung | Betrag |",
            "|----------|-------|-------------|--------|",
            f"| Anlage KAP | 18 | Inländische Kapitalerträge | {_fmt(total_domestic_share_dividends, round_amount)} |",
            f"| Anlage KAP | 19 | Ausländische Kapitalerträge | {_fmt(foreign_capital_income, round_amount)} |",
            f"| Anlage KAP | 37 | Kapitalertragsteuer | {_fmt(withholding_tax_summary.domestic_capital_gains_tax, round_amount)} |",
            f"| Anlage KAP | 38 | Solidaritätszuschlag | {_fmt(withholding_tax_summary.domestic_solidarity_surcharge, round_amount)} |",
            f"| Anlage KAP | 41 | Anrechenbare ausl. Quellensteuer | {_fmt(withholding_tax_summary.foreign_creditable, round_amount)} |",
            f"| Anlage KAP | 20 | Aktiengewinne | {_fmt(stock_gains, round_amount)} |",
            f"| Anlage KAP | 23 | Aktienverluste | {_fmt(stock_losses, round_amount)} |",
            f"| Anlage KAP-INV | 4 | Investmentfonds-Ausschüttungen | {_fmt(total_fund_dividends, round_amount)} |",
        ]
    )

    if withholding_tax_summary.swiss_refundable > 0:
        lines.append(
            f"| eF85 (ESTV) | — | CH-Verrechnungssteuer Rückforderung |"
            f" {_fmt(withholding_tax_summary.swiss_refundable, round_amount)} |"
        )

    lines.extend(
        [
            "",
            f"*Generiert am: Steuerjahr {tax_year}. Zeilennummern beziehen sich auf die Anlage KAP von ELSTER.*",
            "*Vor Abgabe am ELSTER-Formular prüfen.*",
            "",
        ]
    )

    md_path = output_dir / "tax_summary_elster.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"ELSTER mapping exported to {md_path}")
    return md_path


def _generate_pdf(md_path: Path) -> Path | None:
    html_content = _md_to_html(md_path.read_text(encoding="utf-8"))
    pdf_path = md_path.with_suffix(".pdf")
    try:
        weasyprint.HTML(string=html_content).write_pdf(pdf_path)
        logger.info(f"ELSTER mapping PDF exported to {pdf_path}")
        return pdf_path
    except Exception as exc:
        logger.warning(f"PDF generation failed: {exc}")
        return None


def _md_to_html(markdown_text: str) -> str:
    md = markdown.Markdown(extensions=["tables"])
    body = md.convert(markdown_text)
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>ELSTER Tax Mapping Guide</title>
<style>
    body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #1a1a1a; }}
    h1 {{ border-bottom: 3px solid #005aa0; padding-bottom: 10px; }}
    h2 {{ border-bottom: 1px solid #ccc; padding-bottom: 5px; margin-top: 30px; }}
    h3 {{ margin-top: 20px; }}
    blockquote {{ background: #f5f8ff; border-left: 4px solid #005aa0; padding: 10px 15px; margin: 10px 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #005aa0; color: white; }}
    tr:nth-child(even) {{ background: #f9f9f9; }}
    code {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px; }}
    hr {{ border: none; border-top: 1px solid #ccc; margin: 30px 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export_elster_mapping(
    output_dir: Path,
    tax_year: int,
    total_domestic_share_dividends: float,
    total_foreign_share_dividends: float,
    total_interest: float,
    total_fund_dividends: float,
    withholding_tax_summary: WithholdingTaxSummary,
    stock_gains: float,
    stock_losses: float,
    fund_dividends: pl.DataFrame,
    round_amount: bool,
) -> Path:
    """Generate an ELSTER form mapping guide as Markdown and optionally PDF.

    The output file ``tax_summary_elster.md`` maps each computed amount to its
    exact form and row number in Anlage KAP, Anlage KAP-INV, and Swiss eF85 refund.
    """
    md_path = _generate_markdown(
        output_dir=output_dir,
        tax_year=tax_year,
        total_domestic_share_dividends=total_domestic_share_dividends,
        total_foreign_share_dividends=total_foreign_share_dividends,
        total_interest=total_interest,
        total_fund_dividends=total_fund_dividends,
        withholding_tax_summary=withholding_tax_summary,
        stock_gains=stock_gains,
        stock_losses=stock_losses,
        fund_dividends=fund_dividends,
        round_amount=round_amount,
    )

    if shutil.which("weasyprint") is not None or _has_import("weasyprint"):
        _generate_pdf(md_path)

    return md_path


def _has_import(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return False
    return True
