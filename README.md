# Steuerauswertung Swissquote

Python-Skript zur Auswertung von Swissquote-Transaktions-CSVs für die deutsche Steuererklärung (Anlage KAP / KAP-INV).

## Features

- **Automatische Jahreserkennung** aus den Transaktionsdaten
- **Tagesaktuelle Wechselkurse** (Standard) – lädt den Kurs für das exakte Transaktionsdatum
- **Jahresdurchschnitts-Kurse** (Legacy-Modus via `--fx-mode annual`)
- **Validierung** der CSV (fehlende Werte, unbekannte Währungen, Mehrjahres-Check)
- Wechselkurs-Umrechnung (EUR/USD, EUR/CHF, EUR/EUR)
- Ausgabe für Anlage KAP-INV (Dividenden) und Anlage KAP (Zinsen)
- Erfassung einbehaltener Quellensteuer mit Umrechnung in EUR für die Anrechnung in ELSTER
- **Realisierte Gewinne und Verluste aus Aktienverkäufen** mit FIFO-Anschaffungskosten
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
2. Navigieren Sie zu **Trading** → **Portfolio** → **Transaktionen**
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
| `--purchase-types` | `Kauf` | Transaktionstypen für Wertpapierkäufe |
| `--sale-types` | `Verkauf` | Transaktionstypen für Wertpapierverkäufe |
| `--tax-year` | Auto | Steuerjahr bei einer CSV mit Käufen aus Vorjahren |
| `--col-withholding-tax` | `Kosten` | Spalte mit einbehaltener Quellensteuer im Swissquote-Standardexport |
| `--col-withholding-tax-eur` | `Quellensteuer_EUR` | EUR-Spalte für Quellensteuer (Output) |
| `--withholding-tax-rules` | `withholding-tax-rules.toml`, falls vorhanden | TOML-Datei mit ISIN-/Präfixregeln für Quellensteuer |
| `--round` | nein | Auf ganze Euro runden |
| `--no-details` | nein | Details nicht ausgeben |
| `--output file.csv` | nein | Ergebnisse als CSV exportieren |

### Konfiguration per Umgebungsvariable oder Datei

Alle Optionen koennen auch als Umgebungsvariablen mit dem Praefix `SWISSQUOTE_TAX_` gesetzt werden. Aus
`--fx-mode` wird beispielsweise `SWISSQUOTE_TAX_FX_MODE`. Kommandozeilenargumente haben Vorrang vor
Umgebungsvariablen.

```bash
# Lokale Konfiguration aus der Vorlage erstellen und anpassen
cp template.env .env
# .env fuer diesen Shell-Prozess laden
source .env
uv run steuer-auswertung transactions.csv --no-details
```

Alternativ liest `--config` eine Datei mit Optionen im Format `option = wert`. Auch hier ueberschreiben
Kommandozeilenargumente die konfigurierten Werte.

```ini
# tax-calculator.conf
fx-mode = annual
fx-usd = 1.08
fx-chf = 0.95
round = true
```

```bash
uv run steuer-auswertung transactions.csv --config tax-calculator.conf
```

### Quellensteuer-Regeln nach ISIN

Die Spalte `Kosten` im Swissquote-Standardexport kann ausländische Quellensteuer, deutsche
Kapitalertragsteuer oder andere Kosten enthalten. Damit nur tatsächlich anrechenbare ausländische
Quellensteuer in Anlage KAP Zeile 41 erscheint, wird sie in einer lokalen TOML-Datei klassifiziert.

```bash
cp withholding-tax-rules.template.toml withholding-tax-rules.toml
# withholding-tax-rules.toml für die eigenen ISIN-Präfixe und Ausnahmen ergänzen
uv run steuer-auswertung transactions.csv
```

Eine `withholding-tax-rules.toml` im aktuellen Arbeitsverzeichnis wird automatisch geladen. Mit
`--withholding-tax-rules PFAD` kann eine abweichende Regeldatei verwendet werden.

`[[country]]`-Regeln gelten für die ersten zwei Zeichen der ISIN, beispielsweise `DE`, `CH` oder `FR`.
Eine `[[security]]`-Regel für eine konkrete ISIN überschreibt immer die Länderregel. Beide Regeltypen
enthalten den Quellenstaat, die Abzugsart und den maximal anrechenbaren Anteil der Bruttodividende.
`domestic` setzt den Höchstbetrag immer auf `0.0`; `foreign` begrenzt die Anrechnung auf
`Bruttodividende × max_creditable_rate`. Übersteigende ausländische Steuer sowie nicht klassifizierte
Beträge werden separat ausgegeben. Als `domestic` klassifizierte Abzüge werden separat als
anrechenbare deutsche Kapitalertragsteuer (Anlage KAP 2025, Zeile 43) und anrechenbarer
Solidaritätszuschlag (Zeile 44) ausgewiesen; sie gehören nicht in Zeile 41. Die Aufteilung erfolgt
im Verhältnis von Kapitalertragsteuer und Soli und setzt voraus, dass der Abzug keine Kirchensteuer
enthält. Die Regelwerte müssen gegen Steuerbescheinigung und aktuelles DBA geprüft werden.
Das ISIN-Präfix ist nur ein sinnvoller Standardwert: Bei ETFs, international vergebenen ISINs wie `XS...`
und abweichender Besteuerung ist eine konkrete `[[security]]`-Ausnahme erforderlich.

Mit dem optionalen Feld `instrument` wird zwischen Formularen unterschieden: `instrument = "fund"`
weist die Ausschüttung der **Anlage KAP-INV** zu (Investmentfonds/ETFs), der Standard `"share"`
ordnet die Dividende der **Anlage KAP** zu (Einzelaktien). Ohne passende Regel gilt `share`; ETFs
müssen daher per `[[security]]`-Regel mit `instrument = "fund"` markiert werden.

Einzelaktien werden zusätzlich nach Quellenstaat getrennt: deutsche Aktien (`source_country = "DE"`
bzw. ISIN-Präfix `DE`) erscheinen als inländische Kapitalerträge in **Anlage KAP Zeile 18**, alle
übrigen Aktien als ausländische Kapitalerträge in **Anlage KAP Zeile 19**. Die Zeilennummern beziehen
sich auf die Anlage KAP 2025 und sind vor Abgabe am ELSTER-Formular des Steuerjahres zu prüfen.

Ohne Regeldatei oder ohne passende ISIN-Regel wird kein Betrag aus `Kosten` automatisch in Zeile 41
aufgenommen. Separate Quellensteuer-Buchungen werden ebenfalls nicht angerechnet, weil der zugehörige
Bruttobetrag für die Höchstgrenze nicht zuverlässig ermittelt werden kann.

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

# Verkauf 2025 mit Anschaffungskosten aus Vorjahren (Tageskursmodus)
uv run steuer-auswertung transaktionshistorie.csv --tax-year 2025
```

### Aktienverkäufe

Für `Verkauf`-Transaktionen berechnet das Skript den realisierten Betrag mit dem FIFO-Verfahren:

$$\text{Gewinn/Verlust} = \text{Nettoverkaufserlös in EUR} - \text{anteilige Anschaffungskosten in EUR}$$

`Nettobetrag` berücksichtigt damit auch die im Swissquote-Export ausgewiesenen Kauf- und Verkaufskosten. Kauf- und Verkaufstransaktionen werden über die ISIN zugeordnet. Für einen Verkauf müssen alle zugehörigen Kauftranchen, auch aus Vorjahren, in der Eingabedatei enthalten sein. Bei einer mehrjährigen Historie ist `--tax-year` erforderlich; die Auswertung gibt dann nur Verkäufe, Dividenden und Zinsen des gewählten Jahres aus. Der mehrjährige Import wird nur im Tageskursmodus unterstützt.

Aktienverluste werden separat ausgewiesen, damit sie nicht versehentlich mit anderen Kapitalerträgen verrechnet werden. Die endgültige Zuordnung zu den Zeilen der jeweils aktuellen Anlage KAP sollte gegen das Formular des Steuerjahres geprüft werden.

### Anlage KAP

Bei einer Swissquote-Transaktion ohne deutschen Kapitalertragsteuerabzug gehören Aktienverkäufe in die **Anlage KAP**, nicht in die Anlage KAP-INV. Das Skript gibt deshalb zusätzlich zum Nettoergebnis getrennte Aktiengewinne und Aktienverluste aus:

- Enthält die CSV keine `Verkauf`-Transaktionen, ist für Aktienverkäufe keine Eintragung erforderlich.
- Das Nettoergebnis aus den Verkäufen ist bei den Kapitalerträgen ohne inländischen Steuerabzug zu berücksichtigen.
- Aktiengewinne und Aktienverluste werden separat ausgewiesen, da Aktienverluste nur mit Gewinnen aus Aktienveräußerungen verrechnet werden dürfen.

Für das Steuerjahr 2025 entsprechen die Formularfelder der Anlage KAP üblicherweise: Zeile 7 für Kapitalerträge ohne inländischen Steuerabzug, Zeile 8 für darin enthaltene Aktienveräußerungsgewinne und Zeile 12 für darin enthaltene Aktienveräußerungsverluste. Zeilennummern und Feldbezeichnungen können sich ändern; vor Abgabe ist das Formular des jeweiligen Steuerjahrs in ELSTER zu prüfen.

## Ausgabe

```text
=== AUSWERTUNG FÜR STEUERJAHR 2025 (Tageskurse) ===
  Wechselkurse (Tageskurs 2025-03-01): EUR/USD=1.0823, EUR/CHF=0.9534
  Wechselkurse (Tageskurs 2025-06-15): EUR/USD=1.0751, EUR/CHF=0.9498
1. Dividenden (Bruttoerträge vor Quellensteuer):
   Anlage KAP (Zeile 18 - Inländische Kapitalerträge, deutsche Aktien): 28 EUR
   Anlage KAP (Zeile 19 - Ausländische Kapitalerträge, ausländische Aktien): 214 EUR
   Anlage KAP-INV (Zeile 4 - Investmentfonds-/ETF-Ausschüttungen): 175 EUR
2. Anlage KAP (Zeile 19 - Ausländische Zinsen):   2 EUR
3. Anlage KAP (Zeile 41 - Anrechenbare ausländische Steuern): 23 EUR
   Davon Quellensteuer auf Dividenden: 22 EUR
   Davon Quellensteuer auf Zinsen: 1 EUR
4. Realisierte Gewinne/Verluste aus Aktienverkäufen: 250 EUR
  Anlage KAP: In Kapitalerträgen ohne inländischen Steuerabzug berücksichtigen.
  Davon Aktiengewinne (separates Formularfeld): 250 EUR

--- Details Dividenden ---
Datum       Name          Nettobetrag  Währung  Nettobetrag_EUR
01.03.2025  ETF XYZ       150.00       USD      138.89
...

--- Details Zinsen ---
Datum       Transaktionen     Nettobetrag  Währung  Nettobetrag_EUR
15.06.2025  Zinsen auf Einlagen  1.50       CHF      1.61
```

Im `annual`-Modus wird nur ein Kurs pro Währung ausgegeben.

### Quellensteuer

Im Swissquote-Standardexport wird die einbehaltene Quellensteuer in der Spalte `Kosten` geführt; diese verwendet das Skript standardmäßig. Der Betrag wird mit demselben Tages- oder Jahreskurs wie der zugehörige Ertrag in EUR umgerechnet. Negative Abzüge im CSV-Export werden als positiver Betrag ausgewiesen. Die Anrechnung in Anlage KAP Zeile 41 erfolgt jedoch nur mit einer passenden ISIN-Regel aus `--withholding-tax-rules`.

Die ausgewiesenen Dividenden- und Zinserträge sind **Bruttobeträge** vor Quellensteuerabzug: Das Skript rechnet die einbehaltene Steuer aus `Kosten` wieder auf den Nettobetrag auf (`Bruttobetrag_EUR = Nettobetrag_EUR + Quellensteuer_EUR`), da für die deutsche Steuererklärung der Bruttoertrag anzugeben und die Steuer separat anzurechnen ist.

- Quellensteuer auf Dividenden und Zinsen zusammen für Anlage KAP Zeile 41

Bei einem abweichenden CSV-Export mit einer eigenen Spalte `Quellensteuer` wird diese beim Aufruf angegeben:

```bash
uv run steuer-auswertung --fx-mode daily \
  --col-withholding-tax Quellensteuer \
  transactions.csv
```

Die endgültige Anrechenbarkeit und die Felder des aktuellen ELSTER-Formulars sind vor Abgabe zu prüfen.

## Validierungen

Das Skript prüft automatisch:

- Ohne `--tax-year` sind alle Datumsangaben im gleichen Jahr
- Für Verkäufe sind ISIN und Anzahl gesetzt; der FIFO-Bestand enthält ausreichend Stücke
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

```text
src/taxes/
├── cli.py                 # CLI und Ablaufsteuerung
├── transactions.py        # CSV-Import, Jahresauswahl und Validierung
├── currency_conversion.py # Umrechnung mit Tages- oder Jahreskursen
├── stock_sales.py         # FIFO-Berechnung für Aktienverkäufe
├── reporting.py           # Konsolenausgabe und CSV-Export
├── fx_rates.py            # DailyFXRateFetcher (Tageskurse, Cache, Fallback)
└── __init__.py

tests/
├── test_fx_rates.py       # Unit-Tests für fx_rates Modul
├── test_cli.py            # Integrationstests für die CLI
└── test_stock_sales.py    # Integrationstests für Aktienverkäufe
```

Die Fachlogik ist nach Verantwortung getrennt: `transactions` verarbeitet Swissquote-Exporte, `currency_conversion` bewertet Beträge in EUR, `stock_sales` ermittelt FIFO-Gewinne und `reporting` erzeugt die Auswertung. `fx_rates` kapselt weiterhin API-Abruf, Caching und Fallback-Kette und kann unabhängig vom Haupt-Skript getestet werden.
