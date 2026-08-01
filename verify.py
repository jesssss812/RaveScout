"""Step 4: prove the data can answer the demo question. If anything here looks
wrong, STOP — do not create the agent on top of broken data.

Usage: python3 verify.py [artist] [home_city]
  e.g. python3 verify.py "John Summit" Chicago
  With no artist arg it runs checks 1-4 and prints the top artists so you can
  PICK the demo artist from who's actually well-represented.
"""
import sys

from common import env, es_headers, http

INDEX = "events"
artist = sys.argv[1] if len(sys.argv) > 1 else None
home_city = sys.argv[2] if len(sys.argv) > 2 else "Chicago"


def esql(query):
    es = env("ES_URL").rstrip("/")
    status, resp = http("POST", f"{es}/_query", headers=es_headers(),
                        body={"query": query})
    cols = [c["name"] for c in resp["columns"]]
    return cols, resp["values"]


def show(cols, rows):
    print("  " + " | ".join(f"{c:>14s}" for c in cols))
    for r in rows:
        print("  " + " | ".join(f"{str(v):>14s}" for v in r))


es = env("ES_URL").rstrip("/")

# 1. doc count matches the ndjson
with open("data/events.ndjson") as f:
    expected = sum(1 for l in f if l.strip())
status, resp = http("GET", f"{es}/{INDEX}/_count", headers=es_headers())
count = resp["count"]
flag = "OK" if count == expected else "MISMATCH — bulk load lost docs, check index.py output"
print(f"[1] doc count: {count} indexed vs {expected} in ndjson  -> {flag}")

# 2. mapping types
status, resp = http("GET", f"{es}/{INDEX}/_mapping", headers=es_headers())
props = resp[INDEX]["mappings"]["properties"]
pt, dt = props["ticket_price"]["type"], props["event_date"]["type"]
ok = pt == "double" and dt == "date"
print(f"[2] mapping: ticket_price={pt}, event_date={dt}  -> {'OK' if ok else 'WRONG — re-run index.py, do NOT proceed'}")

# 3. price distribution by city — the core aggregation
print("\n[3] price distribution by city (this IS city_price_context):")
cols, rows = esql(f"""
FROM {INDEX}
| WHERE ticket_price IS NOT NULL
| STATS p25 = PERCENTILE(ticket_price, 25),
        median = MEDIAN(ticket_price),
        p75 = PERCENTILE(ticket_price, 75),
        n = COUNT(*)
        BY city
| SORT n DESC
""")
show(cols, rows)

# 4. top artists overall vs in the home city — the scarcity signal
print(f"\n[4a] top 20 artists by total appearances:")
cols, rows = esql(f"""
FROM {INDEX}
| MV_EXPAND artists
| STATS shows = COUNT(*) BY artists
| SORT shows DESC
| LIMIT 20
""")
show(cols, rows)
print(f"\n[4b] top 20 artists by appearances in {home_city}:")
cols, rows = esql(f"""
FROM {INDEX}
| WHERE city == "{home_city}"
| MV_EXPAND artists
| STATS shows = COUNT(*) BY artists
| SORT shows DESC
| LIMIT 20
""")
show(cols, rows)
if rows and all(r[0] <= 1 for r in rows):
    print(f"  WARNING: every artist plays {home_city} at most once — scarcity won't "
          "discriminate. Consider widening the date range for the home city scrape.")

# 5. the go/no-go: one artist's shows across cities
if artist:
    print(f"\n[5] all shows for '{artist}' (GO/NO-GO check):")
    cols, rows = esql(f"""
FROM {INDEX}
| MV_EXPAND artists
| WHERE artists == "{artist}"
| KEEP city, event_date, venue, ticket_price, url
| SORT event_date ASC
| LIMIT 50
""")
    if not rows:
        print(f"  NONE FOUND. Pick a different artist from the [4a] list — the "
              "artist is a parameter, not a commitment.")
    else:
        show(cols, rows)
        n_cities = len({r[0] for r in rows})
        print(f"\n  {len(rows)} shows across {n_cities} cities -> "
              + ("VIABLE — proceed to create_tools.py" if n_cities > 1 else
                 "single city only — pick an artist that tours"))
else:
    print("\n[5] skipped — re-run as: python3 verify.py \"<Artist From 4a>\" <HomeCity>")
