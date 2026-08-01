"""Step 1: pull scraped items from an Apify dataset -> data/raw.json

Usage: python3 fetch.py <DATASET_ID>
"""
import json
import sys

from common import env, http

if len(sys.argv) != 2:
    sys.exit("Usage: python3 fetch.py <DATASET_ID>")

dataset_id = sys.argv[1]
token = env("APIFY_TOKEN")

url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?format=json&clean=true"
status, items = http("GET", url, headers={"Authorization": f"Bearer {token}"})

if not isinstance(items, list):
    sys.exit(f"FATAL: expected a JSON array from Apify, got {type(items).__name__}")
if not items:
    sys.exit("FATAL: dataset is empty — check the run finished and the DATASET_ID is right")

with open("data/raw.json", "w") as f:
    json.dump(items, f, indent=1)

print(f"{len(items)} records -> data/raw.json\n")
print("=== FIRST RECORD (edit FIELD candidates in transform.py to match these keys) ===")
for k, v in items[0].items():
    s = json.dumps(v, ensure_ascii=False)
    print(f"  {k:24s} = {s[:120]}")
