# Steuerauswertung Swissquote

Python-Skript zur Auswertung von Swissquote-Transaktions-CSVs für die deutsche Steuererklärung (Anlage KAP / KAP-INV).

## Features

- **Automatische Jahreserkennung** aus den Transaktionsdaten
- **Automatische Wechselkurse** lädt aktuelle Jahresdurchschnittskurse für das erkannten Jahr
- **Validierung** der CSV (fehlende Werte, unbekannte Währungen, Mehrjahres-Check)
- Wechselkurs-Umrechnung (EUR/USD, EUR/CHF, EUR/EUR)
- Ausgabe für Anlage KAP-INV (Dividenden) und Anlage KAP (Zinsen)
- CSV-Export der Details

## Installation (uv empfohlen)

```bash
# uv installieren (falls nicht vorhanden)
brew install uv  # macOS
# oder: curl -LsSf https://astral.sh/uv/install.sh | sh

# Abhängigkeiten installieren
uv sync
```

## Transaktions-CSV exportieren

1. Melden Sie sich im [Swissquote-Webportal](https://trade.swissquote.ch) an
2. Navigieren Sie zu **Trading** → **Meine Konten** → **Transaktionen**
3. Wählen Sie den gewünschten Zeitraum (z.B. 01.01. bis 31.12.)
4. Klicken Sie auf **Exportieren** und wählen Sie **CSV**
5. Der Download liefert eine Semikolon-getrennte Datei im Latin1-Encoding

## Nutzung

```bash
uv run python steuer_auswertung.py transactions.csv [OPTIONEN]
```

### Pflichtargument

- `transactions.csv` — Export aus Swissquote (Semikolon-getrennt, Latin1)

### Wichtige Optionen

| Option | Standard | Beschreibung |
|--------|----------|--------------|
| `--fx-usd` | Jahresdurchschnitt für erkanntes Jahr | EUR/USD-Kurs (überschreibt automatischen Kurs) |
| `--fx-chf` | Jahresdurchschnitt für erkanntes Jahr | EUR/CHF-Kurs (überschreibt automatischen Kurs) |
| `--fx-eur` | 1.0 | EUR/EUR-Kurs (normalerweise 1.0) |
| `--dividend-types` | `Dividende` | Transaktionstypen für Dividenden |
| `--interest-types` | `Zinsen auf Einlagen` | Transaktionstypen für Zinsen |
| `--round` | nein | Auf ganze Euro runden |
| `--no-details` | nein | Details nicht ausgeben |
| `--output file.csv` | nein | Ergebnisse als CSV exportieren |

### Automatische Wechselkurse

Das Skript lädt automatisch die Jahresdurchschnittswechselkurse für das erkannten Steuerjahr von der frankfurter.dev API (falls verfügbar). Beispiele:

- 2024: EUR/USD ≈ 1.0825, EUR/CHF ≈ 0.9525
- 2023: EUR/USD ≈ 1.0812, EUR/CHF ≈ 0.9718
- 2022: EUR/USD ≈ 1.0534, EUR/CHF ≈ 1.0048

Falls die API nicht verfügbar ist oder kein Jahr erkannt werden kann, werden auf hinterlegte Durchschnittswerte zurückgegriffen.

### Beispiel

```bash
uv run python steuer_auswertung.py transactions-from-01012025-to-31122025.csv \
  --fx-usd 1.08 --fx-chf 0.95 --round --output steuer_2025.csv
```

## Ausgabe

```text
=== AUSWERTUNG FÜR STEUERJAHR 2025 ===
1. Anlage KAP-INV (Zeile 4 - ETF-Ausschüttungen): 175 EUR
2. Ausgabe für Anlage KAP (Zeile 19 - Ausländische Zinsen):   2 EUR

--- Details Dividenden ---
Datum       Name          Nettobetrag  Währung  Nettobetrag_EUR
01.03.2025  ETF XYZ       150.00       USD      138.89
...

--- Details Zinsen ---
Datum       Transaktionen     Nettobetrag  Währung  Nettobetrag_EUR
15.06.2025  Zinsen auf Einlagen  1.50       CHF      1.61
```

## Validierungen

Das Skript prüft automatisch:

- Alle Datumsangaben sind gültig und im gleichen Jahr
- Keine fehlenden Werte in Pflichtspalten (Typ, Währung, Betrag)
- Alle Währungen haben einen konfigurierten FX-Kurs
- Bei Fehlern bricht das Skript mit eindeutiger Fehlermeldung ab

## Standard-Wechselkurse (EZB ca.)

| Jahr | USD (1 EUR = ...) | CHF (1 EUR = ...) |
|------|-------------------|-------------------|
| 2025 | 1.05              | 0.93              |
| 2024 | 1.0825            | 0.9525            |
| 2023 | 1.0812            | 0.9718            |
| 2022 | 1.0534            | 1.0048            |
| 2021 | 1.0829            | 1.0811            |
| 2020 | 1.0421            | 1.0706            |

Kurse über `--fx-usd`, `--fx-chf`, `--fx-eur` überschreiben die automatischen Werte.