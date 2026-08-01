"""Step 3: create the `events` index with an EXPLICIT mapping and bulk load.

Idempotent on purpose: DELETE then PUT then _bulk. You'll re-run this every time
transform.py improves; a fast reset loop beats data safety here.

Usage: python3 index.py
"""
import json
import sys
import urllib.request

from common import env, es_headers, http

INDEX = "events"

# Explicit mapping — never let ES infer types. A price inferred as `text` kills
# every percentile aggregation and costs a full reindex to fix.
MAPPING = {
    "mappings": {
        "properties": {
            "city":         {"type": "keyword"},
            "event_date":   {"type": "date", "format": "yyyy-MM-dd"},
            "weekend_id":   {"type": "keyword"},
            "venue":        {"type": "keyword"},
            "artists":      {"type": "keyword"},
            "title":        {"type": "text"},
            "description":  {"type": "text"},
            "ticket_price": {"type": "double"},
            "genre_tags":   {"type": "keyword"},
            "url":          {"type": "keyword"},
        }
    }
}


def main():
    es = env("ES_URL").rstrip("/")
    try:
        with open("data/events.ndjson") as f:
            lines = [l for l in f if l.strip()]
    except FileNotFoundError:
        sys.exit("FATAL: data/events.ndjson not found — run transform.py first")

    # delete-if-exists (404 is fine, anything else is not)
    req = urllib.request.Request(f"{es}/{INDEX}", method="DELETE", headers=es_headers())
    try:
        urllib.request.urlopen(req, timeout=30)
        print(f"deleted existing /{INDEX}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            sys.exit(f"FATAL: DELETE /{INDEX} -> HTTP {e.code}: {e.read().decode()[:500]}")

    http("PUT", f"{es}/{INDEX}", headers=es_headers(), body=MAPPING)
    print(f"created /{INDEX} with explicit mapping")

    indexed = 0
    for i in range(0, len(lines), 500):
        batch = lines[i:i + 500]
        body = "".join('{"index":{}}\n' + line for line in batch)
        status, resp = http("POST", f"{es}/{INDEX}/_bulk", headers=es_headers(), body=body)
        if resp.get("errors"):
            first = next(it for it in resp["items"] if it["index"].get("error"))
            sys.exit("FATAL: bulk load had failures. First error:\n"
                     + json.dumps(first["index"]["error"], indent=2))
        indexed += len(batch)
        print(f"  indexed {indexed}/{len(lines)}")

    http("POST", f"{es}/{INDEX}/_refresh", headers=es_headers(), body={})
    print(f"done: {indexed:,} docs in /{INDEX}")


if __name__ == "__main__":
    main()
