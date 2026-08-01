"""Step 2: data/raw.json -> data/events.ndjson (canonical schema).

The actor's output schema is unknown until fetch.py runs, so every canonical field
has a CANDIDATE PATH LIST below — first path that resolves wins. After running
fetch.py, compare its "FIRST RECORD" dump against these lists and edit the lists
if the actor uses names not covered. That edit is the whole adaptation step.

Usage: python3 transform.py
"""
import json
import re
import sys
from collections import Counter
from datetime import date, timedelta

# --- edit these to match the actor's actual field names (see fetch.py output) ---
CANDIDATES = {
    "city": ["city", "venue.city", "venue.address.city", "location.city",
             "address.city", "_embedded.venues.0.city.name", "cityName"],
    "event_date": ["event_date", "date", "start_date", "startDate", "startTime",
                   "start_time", "start.local", "dates.start.localDate", "datetime",
                   "startDateTime", "time"],
    "venue": ["venue.name", "venue_name", "venue", "_embedded.venues.0.name",
              "location.name", "location", "place"],
    "artists": ["artists", "lineup", "performers", "artist", "artistList"],
    "title": ["title", "name", "eventName", "event_name"],
    "description": ["description", "summary", "about", "details"],
    "ticket_price": ["ticket_price", "price", "minPrice", "min_price", "ticketPrice",
                     "priceRanges.0.min", "tickets.0.price", "price_min", "cost",
                     "priceRange", "price_range"],
    "genre_tags": ["genre_tags", "genres", "tags", "genre",
                   "classifications.0.genre.name"],
    "url": ["url", "link", "eventUrl", "event_url", "webUrl", "ticketUrl"],
}

REQUIRED = ["city", "event_date"]  # a record missing these can't be ranked; drop it

# The scrape runs broad (the actor's city filter is broken), so scoping to
# "cities I'd travel to" happens here instead. Empty set = keep every city —
# run once like that, read the city counts in the report, then set this.
TARGET_CITIES = set()  # e.g. {"Chicago", "Detroit", "Denver", "Milwaukee"}


def get_path(rec, path):
    cur = rec
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def resolve(rec, field):
    for path in CANDIDATES[field]:
        val = get_path(rec, path)
        if val not in (None, "", [], {}):
            return val
    return None


def parse_date(val):
    """Accept ISO strings/timestamps; return YYYY-MM-DD or None."""
    if isinstance(val, dict):  # some actors nest e.g. {"local": "..."}
        val = val.get("local") or val.get("date") or val.get("start")
    if not isinstance(val, str):
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", val)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", val)  # US format fallback
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def parse_price(val):
    """"$48.00" -> 48.0, "From $35" -> 35.0, "$25-$60" -> 25.0 (low end is the
    buyable price), "Free" -> 0.0, junk -> None. Never invent a number."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        for k in ("min", "low", "value", "amount"):
            if k in val:
                return parse_price(val[k])
        return None
    s = str(val).strip()
    if not s:
        return None
    if re.search(r"\bfree\b", s, re.I):
        return 0.0
    nums = re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))
    if not nums:
        return None
    return min(float(n) for n in nums)


ARTIST_SPLIT = re.compile(r",|/|&|\bb2b\b|\bw/|\bx\b|\bwith\b|\bft\.?\b|\bfeat\.?\b|\+", re.I)


def parse_artists(val, title):
    if isinstance(val, list):
        raw = []
        for a in val:
            raw.append(a.get("name", "") if isinstance(a, dict) else str(a))
    elif isinstance(val, str):
        raw = ARTIST_SPLIT.split(val)
    else:
        # no artist field at all: fall back to splitting the title — noisy but
        # gives the scarcity signal something to key on
        raw = ARTIST_SPLIT.split(re.split(r"[:|@]| at | presents ", title, flags=re.I)[0]) if title else []
    out = []
    for a in raw:
        a = re.sub(r"\s+", " ", a).strip(" -–—•\t")
        if a and len(a) < 60:
            out.append(a)
    return out


def norm_city(val):
    if isinstance(val, dict):
        val = val.get("name", "")
    # "Chicago, IL" and "chicago" must be one bucket — city is the GROUP BY key
    return str(val).split(",")[0].strip().title()


def weekend_id(iso):
    d = date.fromisoformat(iso)
    monday = d - timedelta(days=d.weekday())
    return (monday + timedelta(days=4)).isoformat()  # the Friday of that week


def main():
    try:
        with open("data/raw.json") as f:
            raw = json.load(f)
    except FileNotFoundError:
        sys.exit("FATAL: data/raw.json not found — run fetch.py first")

    events, drops, price_null = [], Counter(), 0
    cities, artists_all, dates = Counter(), set(), []

    for rec in raw:
        city = resolve(rec, "city")
        d = parse_date(resolve(rec, "event_date"))
        if not d:
            drops["no date"] += 1
            continue
        if not city:
            drops["no city"] += 1
            continue
        if TARGET_CITIES and norm_city(city) not in TARGET_CITIES:
            drops["city not in targets"] += 1
            continue
        title = str(resolve(rec, "title") or "").strip()
        price = parse_price(resolve(rec, "ticket_price"))
        if price is None:
            price_null += 1
        genres = resolve(rec, "genre_tags") or []
        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(",") if g.strip()]
        ev = {
            "city": norm_city(city),
            "event_date": d,
            "weekend_id": weekend_id(d),
            "venue": str(resolve(rec, "venue") or "").strip() if not isinstance(resolve(rec, "venue"), dict) else str(resolve(rec, "venue").get("name", "")).strip(),
            "artists": parse_artists(resolve(rec, "artists"), title),
            "title": title,
            "description": str(resolve(rec, "description") or "").strip(),
            "ticket_price": price,
            "genre_tags": [str(g) for g in genres],
            "url": str(resolve(rec, "url") or "").strip(),
        }
        events.append(ev)
        cities[ev["city"]] += 1
        artists_all.update(ev["artists"])
        dates.append(d)

    if not events:
        sys.exit("FATAL: 0 valid events after transform. The candidate paths in "
                 "CANDIDATES don't match this actor's fields — compare with "
                 "fetch.py's FIRST RECORD dump and edit them.")

    with open("data/events.ndjson", "w") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # --- data-quality report: the human's checkpoint, keep it loud ---
    print(f"\n{'='*60}")
    print(f"{len(raw):,} raw -> {len(events):,} valid  (data/events.ndjson)")
    if drops:
        detail = ", ".join(f"{k} ({v})" for k, v in drops.items())
        print(f"  dropped {sum(drops.values())}: {detail}")
    print(f"  ticket_price: {len(events)-price_null:,} parsed, {price_null:,} null")
    print("  cities: " + ", ".join(f"{c} {n}" for c, n in cities.most_common(10)))
    print(f"  date range: {min(dates)} -> {max(dates)}")
    print(f"  distinct artists: {len(artists_all):,}")
    print(f"{'='*60}")
    if price_null > len(events) * 0.7:
        print("WARNING: >70% of prices are null. If this doesn't improve, fall back "
              "to scarcity-only ranking (the pitch survives — see spec risk table).")


if __name__ == "__main__":
    main()
