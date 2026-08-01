# RaveScout

**An agent that tells you which show to travel for — and shows its work.**

Ask it: *"I want to see John Summit in the next 5 months. When and where should I go?"*

It answers with a denominator ("9 shows across 3 cities"), a home-city callout if you don't need to travel at all, and exactly three ranked options — each with a price **percentile for that city's market** and a GO / HOLD / SKIP verdict.

## The idea worth defending

Every travel recommendation is a claim about a *distribution* — "cheap," "rare," "worth flying for" are properties of a population, not of a listing. So RaveScout doesn't read event pages. It scrapes **wide** (all EDM events across the candidate cities), then filters to one artist at query time and ranks against the full corpus:

- **Worthiness = scarcity, not quality.** You don't fly for a good set — you can get those at home. You fly for a show that isn't otherwise available to you. Scarcity is objective and computable: `COUNT(*)` of the artist's home-city appearances.
- **Price is a percentile, never a dollar amount.** "$95" is unevaluable; "the 68th percentile for Denver" is a decision.

## Why these two technologies

- **Apify** — event data changes daily and has no API worth using. A store actor scrapes listings across cities; this repo never parses HTML.
- **Elasticsearch** — the real question ("is this expensive *for Denver*? is this artist rare *for me*?") is a percentile/count aggregation over a corpus. That needs an aggregation engine, not a bigger prompt. The agent never sees the listings — it sees three tools and reads back exact numbers, which is why it scales past any context window.

## Architecture

One index, `events`, one doc per show (explicit mapping — `ticket_price: double`, `event_date: date`, `artists: keyword`). Three Agent Builder tools on top:

| tool | what it answers |
|---|---|
| `artist_shows` | every show for a named artist, across all scraped cities |
| `city_price_context` | p25 / median / p75 ticket price for one city — the yardstick |
| `artist_scarcity` | how often the artist plays the user's home city — the travel reason |

The agent (Elastic Agent Builder, exposed over MCP) ranks scarcity first, price second, and reports them as separate facts.

## Pipeline

```
export APIFY_TOKEN=... ES_URL=... ES_API_KEY=... KIBANA_URL=...

python3 fetch.py <APIFY_DATASET_ID>   # raw scrape -> data/raw.json, dumps field names
python3 transform.py                  # -> data/events.ndjson + data-quality report
python3 index.py                      # explicit mapping, bulk load (idempotent)
python3 verify.py "Artist Name" Chicago   # go/no-go checks incl. the core aggregations
python3 create_tools.py               # 3 tools + agent via Kibana Agent Builder API
```

Then chat with the agent in Kibana, or point Claude Desktop at `{KIBANA_URL}/api/agent_builder/mcp`.

## Cut on purpose

Lodging cost. It's the obvious extension — a second source landing in a second index the agent joins — but the cost axis here is ticket price, and 100 minutes is 100 minutes. You only see shows in cities that were scraped; that's the product ("among cities I'd actually travel to"), not a bug.
