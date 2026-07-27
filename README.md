# Steuerauswertung Swissquote

Python-Skript zur Auswertung von Swissquote-Transaktions-CSVs für die deutsche Steuererklärung (Anlage KAP / KAP-INV).

## Features

- **Automatische Jahreserkennung** aus den Transaktionsdaten
- **Tagesaktuelle Wechselkurse** (Standard) – lädt den Kurs für das exakte Transaktionsdatum
- **Jahresdurchschnitts-Kurse** (Legacy-Modus via `--fx-mode annual`)
- **Validierung** der CSV (fehlende Werte, unbekannte Währungen, Mehrjahres-Check)
- Wechselkurs-Umrechnung (EUR/USD, EUR/CHF, EUR/EUR)
- Ausgabe für Anlage KAP-INV (Dividenden) und Anlage KAP (Zinsen)
- CSV-Export der Details
- **Persistenter Cache** für Wechselkurse (`~/.cache/swissquote-tax/fx_rates.json`)

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
uv run steuer-auswertung transactions.csv [OPTIONEN]
```

### Pflichtargument

- `transactions.csv` — Export aus Swissquote (Semikolon-getrennt, Latin1)

### Wichtige Optionen

| Option | Standard | Beschreibung |
|--------|----------|--------------|
| `--fx-mode` | `daily` | Wechselkurs-Modus: `daily` (Tageskurse pro Transaktionsdatum) oder `annual` (Jahresdurchschnitt) |
| `--fx-usd` | Auto (Fallback) | EUR/USD-Kurs (im `annual`-Modus: Jahresdurchschnitt; im `daily`-Modus: Fallback wenn API fehlschlägt) |
| `--fx-chf` | Auto (Fallback) | EUR/CHF-Kurs (im `annual`-Modus: Jahresdurchschnitt; im `daily`-Modus: Fallback wenn API fehlschlägt) |
| `--fx-eur` | 1.0 | EUR/EUR-Kurs (normalerweise 1.0) |
| `--dividend-types` | `Dividende` | Transaktionstypen für Dividenden |
| `--interest-types` | `Zinsen auf Einlagen` | Transaktionstypen für Zinsen |
| `--round` | nein | Auf ganze Euro runden |
| `--no-details` | nein | Details nicht ausgeben |
| `--output file.csv` | nein | Ergebnisse als CSV exportieren |

### Wechselkurs-Modi

#### Tageskurse (`--fx-mode daily`, **Standard**)

Das Skript lädt für **jede Transaktion** den Wechselkurs des exakten Transaktionsdatums von der frankfurter.dev API.
- Vorteil: Korrekte steuerliche Bewertung pro Transaktion
- Caching: Kurse werden lokal in `~/.cache/swissquote-tax/fx_rates.json` gespeichert (keine doppelten API-Aufrufe)
- Fallback-Kette: Tageskurs API → Jahresdurchschnitt API → Hinterlegte Standardwerte

#### Jahresdurchschnitt (`--fx-mode annual`, Legacy)

Verhält sich wie die vorherige Version: Ein Kurs pro Währung für das gesamte Steuerjahr.
- Verwendet `--fx-usd`, `--fx-chf`, `--fx-eur` als Überschreibungen
- Nützlich für Reproduzierbarkeit oder wenn die API nicht verfügbar ist

### Beispiel

```bash
# Tageskurse (Standard) - nutzt Cache automatisch
uv run steuer-auswertung transactions-from-01012025-to-31122025.csv --no-details

# Jahresdurchschnitt mit manuellen Kursen
uv run steuer-auswertung transactions-from-01012025-to-31122025.csv \
  --fx-mode annual --fx-usd 1.08 --fx-chf 0.95 --round --output steuer_2025.csv
```

## Ausgabe

```text
=== AUSWERTUNG FÜR STEUERJAHR 2025 (Tageskurse) ===
  Wechselkurse (Tageskurs 2025-03-01): EUR/USD=1.0823, EUR/CHF=0.9534
  Wechselkurse (Tageskurs 2025-06-15): EUR/USD=1.0751, EUR/CHF=0.9498
1. Anlage KAP-INV (Zeile 4 - ETF-Ausschüttungen): 175 EUR
2. Anlage KAP (Zeile 19 - Ausländische Zinsen):   2 EUR

--- Details Dividenden ---
Datum       Name          Nettobetrag  Währung  Nettobetrag_EUR
01.03.2025  ETF XYZ       150.00       USD      138.89
...

--- Details Zinsen ---
Datum       Transaktionen     Nettobetrag  Währung  Nettobetrag_EUR
15.06.2025  Zinsen auf Einlagen  1.50       CHF      1.61
```

Im `annual`-Modus wird nur ein Kurs pro Währung ausgegeben.

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
| 2020 | 1.1421            | 1.0706            |

Kurse über `--fx-usd`, `--fx-chf`, `--fx-eur` überschreiben die automatischen Werte (im `annual`-Modus direkt, im `daily`-Modus als Fallback).

## Architektur

```
taxes/
├── steuer_auswertung.py   # Haupt-Skript, CLI, Datenverarbeitung
├── fx_rates.py            # DailyFXRateFetcher (Tageskurse, Cache, Fallback)
└── __init__.py

tests/
├── test_fx_rates.py       # Unit-Tests für fx_rates Modul
└── test_steuer_auswertung.py  # Integrationstests für CLI
```

Der neue `fx_rates`-Modul kapselt die gesamte Wechselkurs-Logik (API-Abruf, Caching, Fallback-Kette) und kann unabhängig vom Haupt-Skript getestet werden.