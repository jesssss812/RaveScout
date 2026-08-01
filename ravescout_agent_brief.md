# RaveScout — coding agent brief

Hand this to Claude Code **together with `ravescout_spec.md`**. That file is the product spec; this file is the build contract. Read both before writing code.

---

## 0. Context you need to know

This is a **hackathon build with a hard deadline**. Judged on: does it work (10), is it creative (10), can the builder explain why Apify and Elasticsearch were used (10).

**Therefore:**
- **Working beats elegant.** No abstractions, no config framework, no class hierarchy. Flat scripts.
- **Fail fast and loud.** If something's wrong, crash with a clear message. Do not silently continue with bad data.
- **Do not expand scope.** No web UI. No extra data sources. No Docker. No test suite beyond the smoke checks below.
- **The human must be able to explain every design decision.** When you make a non-obvious call, print a one-line comment explaining *why* — she has to defend it in 60 seconds.

---

## 1. Secrets — read this first

All credentials come from **environment variables**. Never hardcode them, never write them into a file, never print them.

```
APIFY_TOKEN        # Apify API token
ES_URL             # Elasticsearch serverless endpoint
ES_API_KEY         # Elasticsearch API key (Authorization: ApiKey <key>)
KIBANA_URL         # Kibana base URL (for Agent Builder API)
```

Fail immediately with a clear message if any are missing. Do not create a `.env` that gets committed.

---

## 2. What the human does (not you)

Assume these are already done or will be done in parallel — do not attempt them:

- Apify account + choosing an actor from the Store
- Running the first scrape from the Apify console (or you may run it via API, see step 3)
- Elastic Cloud serverless project creation
- Generating the API keys
- Connecting Claude Desktop to the MCP endpoint at the end

---

## 3. Build these, in this order

### Step 1 — `fetch.py`: pull the scraped data

Fetch dataset items from Apify and write raw JSON to `data/raw.json`.

```
GET https://api.apify.com/v2/datasets/{DATASET_ID}/items?format=json&clean=true
Authorization: Bearer $APIFY_TOKEN
```

Accept `DATASET_ID` as a CLI arg. Print the record count and **dump the first record's keys and values** so the human can see what fields actually exist. Do not assume field names — the actor's output schema is unknown until this runs.

### Step 2 — `transform.py`: raw → canonical schema

This is the highest-value step. Read `data/raw.json`, write `data/events.ndjson`.

**Canonical schema — every output record must have exactly these fields:**

| field | type | notes |
|---|---|---|
| `city` | string | normalized, title case, trimmed |
| `event_date` | string | ISO `YYYY-MM-DD` |
| `weekend_id` | string | see below |
| `venue` | string | |
| `artists` | array of strings | split on `,` `/` `&` `b2b` `w/`; trim; drop empties |
| `title` | string | |
| `description` | string | may be empty |
| `ticket_price` | float or null | see below |
| `genre_tags` | array of strings | may be empty |
| `url` | string | |

**Price parsing.** Scraped prices arrive as `"$48.00"`, `"From $35"`, `"$25–$60"`, `"Free"`, `""`.
- Strip currency symbols, commas, whitespace
- On a range, take the **low end** (that's the buyable price)
- `"Free"` → `0.0`
- Unparseable or missing → `null`, and **count these**

**`weekend_id`.** Use the Friday of the ISO week containing the event date, so Thu/Fri/Sat/Sun of one weekend share a bucket:
```python
monday = d - timedelta(days=d.weekday())
weekend_id = (monday + timedelta(days=4)).isoformat()
```

**At the end, print a report:**
```
1,240 raw → 1,187 valid
  dropped 53: no date (41), no city (12)
  ticket_price: 894 parsed, 293 null
  cities: Chicago 512, Detroit 388, Denver 287
  date range: 2026-08-05 → 2027-01-18
  distinct artists: 1,431
```
This report is the human's data-quality checkpoint. Make it prominent.

### Step 3 — `index.py`: create the index with an EXPLICIT mapping and bulk load

**Do not let Elasticsearch infer the mapping.** This is the single most common failure in this build.

```json
{
  "mappings": {
    "properties": {
      "city":          { "type": "keyword" },
      "event_date":    { "type": "date", "format": "yyyy-MM-dd" },
      "weekend_id":    { "type": "keyword" },
      "venue":         { "type": "keyword" },
      "artists":       { "type": "keyword" },
      "title":         { "type": "text" },
      "description":   { "type": "text" },
      "ticket_price":  { "type": "double" },
      "genre_tags":    { "type": "keyword" },
      "url":           { "type": "keyword" }
    }
  }
}
```

Index name: `events`.

**Make it idempotent** — `DELETE /events` then `PUT /events` with the mapping, then `_bulk`. She will run this several times as the transform improves; a fast reset loop is worth more than data safety here.

Bulk in batches of 500. NDJSON format, one action line and one source line per doc. **Check the `errors` flag in the response** and print the first failure if any — do not report success on a partially failed bulk.

### Step 4 — `verify.py`: prove the data can answer the question

Run these and print results. **If any look wrong, stop and tell the human — do not proceed to step 5.**

1. Doc count matches what `transform.py` wrote
2. `GET /events/_mapping` — confirm `ticket_price` is `double` and `event_date` is `date`
3. Price distribution by city (this is the core aggregation — if it errors, the mapping is wrong):
```
FROM events
| STATS p25 = PERCENTILE(ticket_price, 25),
        median = MEDIAN(ticket_price),
        p75 = PERCENTILE(ticket_price, 75),
        n = COUNT(*)
        BY city
```
4. Top 20 artists by total appearances, and by appearances **in Chicago specifically** — this is the scarcity signal; if Chicago counts are all 0 or 1, scarcity won't discriminate and the human needs to know now
5. Given an artist name as a CLI arg, list all their shows with city, date, price

**Check 5 is the go/no-go.** If it returns a sensible multi-city list for a real artist, the build is viable.

### Step 5 — `create_tools.py`: Agent Builder tools + agent via the Kibana API

Create three tools and one agent. Look up the current Agent Builder API shape in the Elastic docs before writing this — do not guess the request bodies. Base URL is `$KIBANA_URL`, auth is `Authorization: ApiKey $ES_API_KEY`.

**Tool 1 — `artist_shows`** (index search over `events`)
> Finds every scheduled show for a named artist across all cities in the index. Use whenever the user asks where or when they can see a specific artist.

**Tool 2 — `city_price_context`** (ES|QL, param: `city`)
> Returns the ticket-price distribution — 25th percentile, median, 75th percentile, and sample size — for a given city. Use to judge whether a single ticket price is cheap or expensive FOR THAT MARKET. Never state a price as good or bad without calling this first.

**Tool 3 — `artist_scarcity`** (ES|QL, params: `artist`, `home_city`)
> Returns how many times an artist plays the user's home city within the indexed window. Zero or low means the show is not otherwise available and is worth travelling for; a high count means the user should wait rather than travel.

**Agent** — system prompt is in `ravescout_spec.md` under "Agent system prompt". Use it **verbatim**. The instructions about the denominator line, the home-city callout, and showing exactly three options are load-bearing product behavior, not filler.

If the API turns out to be awkward or undocumented, **stop and say so** — creating three tools by hand in the Kibana UI takes ten minutes and is not worth a long fight.

---

## 4. Definition of done

- [ ] `verify.py` check 5 returns a real artist's shows across multiple cities with prices
- [ ] `city_price_context` ES|QL returns non-null percentiles for every city
- [ ] The agent, asked *"I want to see {artist} in the next 5 months, when and where should I go?"*, replies with: a denominator line, a home-city callout if applicable, and exactly three ranked options each carrying a price percentile and a GO/HOLD/SKIP verdict

Stop there. Do not polish.

---

## 5. If you get stuck

| Problem | Do this |
|---|---|
| No usable price field in the scrape | Set all `ticket_price` to null, tell the human. Product falls back to scarcity-only ranking — the pitch survives |
| `ticket_price` won't parse for most records | Report the count and show 10 raw examples. Do not invent values |
| Bulk load partially fails | Print the first error verbatim. Usually a date-format or type mismatch |
| Agent Builder API unclear | Stop. Tell the human to create the tools in the Kibana UI |
| Too few events | Say so. **Do not add a data source** — that's a scope decision for the human |

**Never fabricate data.** Not a sample row, not a placeholder price, not a mock response. A demo built on invented data fails the only question that matters.

---

## 6. Time discipline

If any single step exceeds **15 minutes**, stop and report what's blocking. Do not keep grinding. The human has a hard submission deadline and would rather cut scope than discover a stall at the end.
