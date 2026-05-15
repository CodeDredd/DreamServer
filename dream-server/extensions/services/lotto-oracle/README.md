# Lotto Oracle (Tip Engine)

FastAPI-Service, der Ziehungsarchive deutscher staatlicher Lotterien
(`Lotto 6 aus 49`, `Eurojackpot`, `Spiel 77`, `Super 6`) sammelt,
in einer SQLite-Datenbank vorhält und auf Basis mehrerer Strategien
Tipps generiert.

> **Wichtig**: Der Service generiert **Vorschläge**.
> Eine reale, automatisierte Tippabgabe über eine offizielle API ist in
> Deutschland nicht möglich — siehe [§ Reale Abgabe](#reale-abgabe).

## Spielarten

| ID                | Spiel              | Pool                                | Ziehungstage |
|-------------------|--------------------|-------------------------------------|--------------|
| `lotto-6aus49`    | Lotto 6 aus 49     | 6 von 49 + Superzahl 0–9            | Mi, Sa       |
| `eurojackpot`     | Eurojackpot        | 5 von 50 + 2 von 12 (seit 03/2022)  | Di, Fr       |
| `spiel77`         | Spiel 77           | 7-stellige Losnummer                | Mi, Sa       |
| `super6`          | Super 6            | 6-stellige Spielscheinnummer        | Mi, Sa       |

## Strategien

### Kombinatorische Spiele (6aus49 / Eurojackpot)

| Strategie         | Idee                                                               |
|-------------------|--------------------------------------------------------------------|
| `recency_exclude` | **Hauptforderung des Operators** — schließt jede Zahl der letzten Ziehung aus. Tipps ändern sich nach jeder Ziehung garantiert. |
| `frequency_hot`   | Häufiger gezogene Zahlen werden bevorzugt.                          |
| `frequency_cold`  | Selten gezogene Zahlen werden bevorzugt (Gegenstrategie).           |
| `gap_due`         | Zahlen mit dem aktuell längsten "Streak" ohne Ziehung.              |
| `balanced`        | Zufallsauswahl unter Constraints (even/odd-Mix, Summe im IQR der Historie, ≥1 Zahl > 31, keine 3er-Folge, ohne letzte Ziehung). |
| `anti_pattern`    | Vermeidet, was viele Spieler tippen (reine Datums-Tipps, arithm. Folgen, einzelne Schein-Reihen). |
| `random_uniform`  | Echte Gleichverteilung — als Vergleichsbaseline.                    |

### Ziffernspiele (Spiel 77 / Super 6)

Da jede Ziffer offiziell unabhängig und uniform 0–9 gezogen wird, sind
strukturelle Strategien limitiert. Wir liefern:

| Strategie         | Idee                                                                |
|-------------------|---------------------------------------------------------------------|
| `recency_exclude` | Pro Ziffernposition eine andere Ziffer als die letzte Ziehung.       |
| `frequency_hot`   | Häufigste Ziffer pro Position (gewichtet).                          |
| `frequency_cold`  | Seltenste Ziffer pro Position.                                       |
| `random_uniform`  | Reine Gleichverteilung — Baseline.                                  |

### Warum keine "Zahlen 1/2/3 ausschließen"-Option?

Weil die Lotterie ein gedächtnisloser Bernoulli-Prozess ist: jede
gültige Zahl hat dieselbe Wahrscheinlichkeit. **Die einzige rationale
Optimierung ist nicht der erwartete Gewinn, sondern die erwartete
Quote** — und die wird nur niedriger, wenn man Tipps abgibt, die viele
andere Spieler ebenfalls abgeben (typische Datums- und 1-2-3-4-5-6-
Muster). Genau dafür ist `anti_pattern` gedacht. Niedrige Zahlen
explizit auszuschließen würde gegen ein zentrales Statistik-Prinzip
verstoßen, deshalb tut der `random_uniform`-Baseline-Tipp das nicht.

## Datenquellen

> **Reality-Check (Stand 05/2026)**: alle deutschen Lotterie-Anbieter
> (`lotto.de`, `eurojackpot.de`, `westlotto.de`, `lottozahlen.de`,
> `dielottozahlen.de`, `lotto-bayern.de` …) liefern ihre Lottozahlen-
> Archive heute als JS-gerenderte SPAs aus. Ein server-seitiger HTTP-
> Request bekommt nur die HTML-Hülle ohne Ziehungsdaten zurück.
> Der zuvor genutzte Mirror `lottozahlenonline.de` ist offline.

Der Fetcher arbeitet daher in Schichten:

1. **`CsvSeedParser`** — `seed_data/<game>.csv` (im Container unter
   `/seed`) bootstrappt die DB beim Cold-Start. Das Repo enthält je
   einen verifizierten Eintrag, damit das UI vom ersten Tag an etwas
   anzeigen kann.
2. **`LottoReportLatestParser`** — scrapet die jeweils **letzte**
   Ziehung von `lotto-6aus49` und `eurojackpot` aus
   `https://www.lottoreport.de/dyn-vorw-lo.htm` (die einzige
   verifiziert server-seitig gerenderte deutsche Lotterie-Seite).
   Wächst die DB pro Cron-Lauf um 1–2 Ziehungen.
3. **Operator-CSV via `POST /admin/import`** — der einzige Pfad für
   den vollständigen 30-Jahres-Backfill von `spiel77` und `super6`
   (es gibt schlicht keinen öffentlichen Mirror, der diese Spiele
   server-seitig ausliefert). Wer die Daten besitzt (eigener Scraper,
   PDF-Auszüge, frühere Datensätze), legt sie als CSV ab und ruft den
   Endpoint einmalig auf.

### Backfill-Strategie in der Praxis

```bash
TOKEN=$(grep ^LOTTO_ORACLE_TOKEN= ~/dream-server/.env | cut -d= -f2-)

# Schritt 1: was offiziell geht (nimmt aktuelle Ziehung mit)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8100/refresh

# Schritt 2: vollständige Historie aus eigener CSV einspielen
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  -F game=lotto-6aus49 \
  -F file=@/path/to/lotto-6aus49-1995-2026.csv \
  http://127.0.0.1:8100/admin/import
```

CSV-Schema siehe `seed_data/README.md`.

## Auto-Update (Cron)

Standardplan: `30 3 * * 1,4` in `Europe/Berlin` —
**Montag und Donnerstag um 03:30**.

* Mo 03:30 → erfasst die Sa-Ziehungen (6aus49, Spiel77, Super6) und die
  Fr-Ziehung (Eurojackpot).
* Do 03:30 → erfasst die Mi-Ziehungen (6aus49, Spiel77, Super6) und die
  Di-Ziehung (Eurojackpot).

Override über `.env`:

```env
LOTTO_ORACLE_FETCH_CRON=0 4 * * *      # täglich um 04:00
```

Nach jedem Fetch generiert der Service automatisch frische Tipps für
alle Spiele (`LOTTO_ORACLE_AUTO_GENERATE=1`, default an).
Das ist genau die vom Operator gewünschte "Tipps ändern sich nach jeder
Ziehung"-Garantie.

## Endpoints

| Methode | Pfad                              | Auth | Zweck                                       |
|---------|-----------------------------------|------|---------------------------------------------|
| GET     | `/health`                         | —    | Liveness + Submission-API-Hinweis           |
| GET     | `/games`                          | —    | Spielarten + History-Extent                 |
| GET     | `/games/{id}/strategies`          | —    | Strategie-Beschreibungen für UI             |
| GET     | `/draws?game=…`                   | —    | Paginiertes Ziehungsarchiv                  |
| GET     | `/stats?game=…`                   | —    | Frequenz / Gap-Analyse                      |
| GET     | `/tips?game=…`                    | —    | Letzte generierte Tipps                     |
| POST    | `/refresh`                        | ✅    | Inkrementeller Fetch                        |
| POST    | `/refresh/full`                   | ✅    | Komplett-Backfill                           |
| POST    | `/tips/generate`                  | ✅    | Neue Tipps erzeugen                         |
| POST    | `/admin/import`                   | ✅    | Operator-CSV importieren                    |

Auth = `Authorization: Bearer $LOTTO_ORACLE_TOKEN` (wenn gesetzt).

## Reale Abgabe

> **Es gibt keine offizielle, öffentliche REST-API zur Tippabgabe in DE.**

* `lotto.de`, `lotto-bw.de`, `westlotto.de`, `eurojackpot.de` etc.
  bieten ausschließlich Webformulare hinter Login + Bezahlmittel.
* Drittanbieter (`lotto24.de`, `tipp24.de`) verlangen ebenfalls
  Account + SEPA/Kreditkarte und stellen API-Zugänge nur kommerziellen
  B2B-Partnern unter Lizenz bereit.
* Web-Scraping eines authentifizierten Tippscheins verstößt gegen die
  AGB der Anbieter (und je nach Lesart gegen das Glücksspielstaats-
  vertrags-Reglement).

Konsequenz: Der Service liefert die Tipps in maschinenlesbarer Form
(`/tips`) **und** als kopierbare Klartext-Liste über das Dashboard.
Der Operator überträgt sie manuell in den jeweiligen Anbieter — pro
Tipp dauert das wenige Sekunden.

Wer das automatisieren will, hat realistisch zwei Optionen:

1. **Offizieller Affiliate-Vertrag** mit Lotto24/Tipp24 (kommerziell,
   Lizenzpflicht, KYC) — dann kann der Service hier optional einen
   konkreten Adapter bekommen.
2. **Keine Automatisierung**. Empfohlen, solange du nicht im
   Glücksspiel-Affiliate-Geschäft bist.

## Build & Deploy

Lokal gebautes Image (kein Pin in `installers/phases/08-images.sh`).
Standard-Workflow:

```bash
# Auf Halo Strix
ssh sky-net@192.168.178.110 'dream sync --pull --auto-restart'
```

`dream sync` baut den Container neu, persistente SQLite unter
`~/dream-server/data/lotto-oracle/lotto.sqlite` bleibt erhalten.

## Operator-Setup (.env)

```env
# Pflicht für die Write-Endpoints
LOTTO_ORACLE_TOKEN=$(openssl rand -hex 32)

# Optional: Cron / Retention overrides
# LOTTO_ORACLE_FETCH_CRON=30 3 * * 1,4
# LOTTO_RETENTION_YEARS=30
# LOTTO_ORACLE_AUTO_GENERATE=1
```

Damit n8n-Workflows den Service triggern können, ist
`LOTTO_ORACLE_TOKEN` zusätzlich in `extensions/services/n8n/compose.yaml`
unter `environment:` gebridged.

## Diagnose

```bash
ssh sky-net@192.168.178.110 'dream logs lotto-oracle | tail -80'
ssh sky-net@192.168.178.110 'curl -fsS http://127.0.0.1:8100/state | jq'
```

