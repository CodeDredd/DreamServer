# Finance Vector Seeder

Befüllt eine Qdrant-Collection `finance_assets` mit den **Top 250 Aktien**
(nach Marktkapitalisierung, Quelle: Wikipedia S&P 500 / NASDAQ-100 / DAX +
Yahoo Finance via `yfinance`) und den **Top 250 Kryptowährungen**
(Quelle: CoinGecko `/coins/markets`).

Embeddings werden lokal über den TEI-Service (`dream-embeddings`,
Default-Modell `BAAI/bge-base-en-v1.5`, 768 dim) erzeugt — es verlässt
**nichts** den Server außer den lesenden HTTP-Requests an Wikipedia,
Yahoo Finance und CoinGecko.

## Schema

Eine Collection `finance_assets`. Ein Punkt = ein Asset.

Payload-Felder:

| Feld           | Typ      | Beispiel                       |
|----------------|----------|--------------------------------|
| `type`         | keyword  | `stock` \| `crypto`            |
| `symbol`       | keyword  | `AAPL`, `BTC`                  |
| `name`         | text     | `Apple Inc.`                   |
| `sector`       | keyword  | `Technology` / `Layer 1`       |
| `country`      | keyword  | `US`, `DE`, `-`                |
| `currency`     | keyword  | `USD`, `EUR`                   |
| `exchange`     | keyword  | `NASDAQ`, `XETRA`, `-`         |
| `market_cap`   | float    | Marktkapitalisierung in USD    |
| `price`        | float    | letzter Preis (USD)            |
| `description`  | text     | kurze Faktenbeschreibung       |
| `website`      | text     | Homepage / CoinGecko-Slug      |
| `last_updated` | datetime | ISO-8601 UTC                   |

Payload-Indexe für schnelles Filtern: `type`, `symbol`, `sector`, `country`.

Punkt-IDs sind **deterministisch** (`uuid5("finance:<type>:<symbol>")`),
wiederholte Läufe sind also idempotent (Upsert).

## Voraussetzungen

Container müssen laufen (Teil des DreamServer-Stacks):

```bash
make up SERVICES="qdrant embeddings"
```

Erreichbar unter (Default-Bind `127.0.0.1`):

* Qdrant       → `http://127.0.0.1:6333`
* Embeddings   → `http://127.0.0.1:8090`

## Ausführen

```bash
cd dream-server/scripts/finance-vector
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# optional, falls QDRANT_API_KEY gesetzt ist:
export QDRANT_API_KEY="$(grep ^QDRANT_API_KEY ../../.env | cut -d= -f2)"

python seed_finance_collection.py
```

Optionen:

```
--qdrant-url      Default: http://127.0.0.1:6333
--embeddings-url  Default: http://127.0.0.1:8090
--collection      Default: finance_assets
--top-stocks      Default: 250
--top-crypto      Default: 250
--recreate        Collection vorher löschen (sonst nur Upsert)
--dry-run         Daten holen + Texte bauen, kein Schreiben
```

## Tägliches Refresh (Cron)

```cron
# Preise/MarketCap täglich um 03:17 UTC aktualisieren (idempotenter Upsert)
17 3 * * * cd /opt/dream-server/scripts/finance-vector && \
  ./.venv/bin/python seed_finance_collection.py >> /var/log/finance-seed.log 2>&1
```

## Nutzung im RAG (Beispiel)

```python
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

q = QdrantClient(url="http://127.0.0.1:6333")
hits = q.search(
    collection_name="finance_assets",
    query_vector=embed("Wie ist Apple aufgestellt?"),
    query_filter=qm.Filter(must=[qm.FieldCondition(
        key="type", match=qm.MatchValue(value="stock"))]),
    limit=5,
)
for h in hits:
    print(h.payload["symbol"], h.payload["name"], h.score)
```

Im Prompt an Qwen 3.6 immer die Treffer als Kontext mitgeben **inklusive
`last_updated`** und das Modell anweisen, ohne Quelle nichts zu Zahlen
zu sagen — das ist der eigentliche Anti-Halluzinations-Hebel.

