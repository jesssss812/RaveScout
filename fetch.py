"""Step 1: pull scraped items from one or more Apify datasets -> data/raw.json

Accepts multiple IDs because per-city actor runs each produce their own dataset.

Usage: python3 fetch.py <DATASET_ID> [DATASET_ID ...]
"""
import json
import sys

from common import env, http

if len(sys.argv) < 2:
    sys.exit("Usage: python3 fetch.py <DATASET_ID> [DATASET_ID ...]")

token = env("APIFY_TOKEN")

items = []
for dataset_id in sys.argv[1:]:
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?format=json&clean=true"
    status, batch = http("GET", url, headers={"Authorization": f"Bearer {token}"})
    if not isinstance(batch, list):
        sys.exit(f"FATAL: expected a JSON array for {dataset_id}, got {type(batch).__name__}")
    print(f"  {dataset_id}: {len(batch)} records")
    items.extend(batch)

if not items:
    sys.exit("FATAL: all datasets empty — check the runs finished and the IDs are right")

with open("data/raw.json", "w") as f:
    json.dump(items, f, indent=1)

print(f"{len(items)} records -> data/raw.json\n")
print("=== FIRST RECORD (edit FIELD candidates in transform.py to match these keys) ===")
for k, v in items[0].items():
    s = json.dumps(v, ensure_ascii=False)
    print(f"  {k:24s} = {s[:120]}")
