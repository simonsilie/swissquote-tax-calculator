# Steuerauswertung Swissquote

Python-Skript zur Auswertung von Swissquote-Transaktions-CSVs für die deutsche Steuererklärung (Anlage KAP / KAP-INV).

## Features

- **Automatische Jahreserkennung** aus den Transaktionsdaten
- **Tagesaktuelle Wechselkurse** – lädt den Kurs für das exakte Transaktionsdatum
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
| -------- | ---------- | -------------- |
| `--dividend-types` | `Dividende` | Transaktionstypen für Dividenden |
| `--interest-types` | `Zinsen auf Einlagen` | Transaktionstypen für Zinsen |
| `--withholding-tax-types` | `Steuerrückbehalt Quellensteuer Withholding Tax` | Transaktionstypen für separate Quellensteuer-Buchungen |
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
`--tax-year` wird beispielsweise `SWISSQUOTE_TAX_TAX_YEAR`. Kommandozeilenargumente haben Vorrang vor
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
anrechenbare deutsche Kapitalertragsteuer (Anlage KAP 2025, Zeile 37) und anrechenbarer
Solidaritätszuschlag (Zeile 38) ausgewiesen; sie gehören nicht in Zeile 41. Die Aufteilung erfolgt
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
aufgenommen. Separate Quellensteuer-Buchungen (Steuerrückbehalt, Quellensteuer, Withholding Tax)
werden ebenfalls klassifiziert: Inländische Abzüge werden als Kapitalertragsteuer/Soli ausgewiesen,
ausländische Abzüge ohne zugehörigen Bruttobetrag erscheinen als nicht klassifiziert.

### Wechselkurse

#### Tageskurse

Das Skript lädt für **jede Transaktion** den Wechselkurs des exakten Transaktionsdatums von der frankfurter.dev API.

- Vorteil: Korrekte steuerliche Bewertung pro Transaktion
- Caching: Kurse werden lokal in `~/.cache/swissquote-tax/fx_rates.json` gespeichert (keine doppelten API-Aufrufe)
- Fallback-Kette: Tageskurs API → Jahresdurchschnitt API → Hinterlegte Standardwerte

### Beispiel

```bash
# Tageskurse - nutzt Cache automatisch
uv run steuer-auswertung transactions-from-01012025-to-31122025.csv --no-details

# Verkauf 2025 mit Anschaffungskosten aus Vorjahren
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

### Quellensteuer

Im Swissquote-Standardexport wird die einbehaltene Quellensteuer in der Spalte `Kosten` geführt; diese verwendet das Skript standardmäßig. Der Betrag wird mit demselben Tages- oder Jahreskurs wie der zugehörige Ertrag in EUR umgerechnet. Negative Abzüge im CSV-Export werden als positiver Betrag ausgewiesen. Die Anrechnung in Anlage KAP Zeile 41 erfolgt jedoch nur mit einer passenden ISIN-Regel aus `--withholding-tax-rules`.

Die ausgewiesenen Dividenden- und Zinserträge sind **Bruttobeträge** vor Quellensteuerabzug: Das Skript rechnet die einbehaltene Steuer aus `Kosten` wieder auf den Nettobetrag auf (`Bruttobetrag_EUR = Nettobetrag_EUR + Quellensteuer_EUR`), da für die deutsche Steuererklärung der Bruttoertrag anzugeben und die Steuer separat anzurechnen ist.

- Quellensteuer auf Dividenden und Zinsen zusammen für Anlage KAP Zeile 41

Bei einem abweichenden CSV-Export mit einer eigenen Spalte `Quellensteuer` wird diese beim Aufruf angegeben:

```bash
uv run steuer-auswertung \
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
| 2021 | 1.1829            | 1.0811            |
| 2020 | 1.1421            | 1.0706            |
