# RaveScout

**An agent that tells you which show to travel for, and shows its work.**

A scout covers ground you can't, and comes back with a shortlist and a reason. It doesn't decide for you — it reports. That's exactly the product.

---

## The demo question

> *"I want to see John Summit in the next 5 months. When and where should I go?"*

## The one-sentence pitch

Every travel recommendation is a claim about a distribution — "cheap," "rare," "worth flying for" are properties of a *population*, not of a listing you can read off a page. So RaveScout doesn't read event pages. It ranks them against their peers.

---

## Input

| Input | Example | Required |
|---|---|---|
| Artist | `"John Summit"` | yes — **parameterised, never hardcoded** |
| Time window | next 5 months | yes |
| Home city | `Chicago` | yes — this is the scarcity baseline |
| Candidate cities | the 2–3 others you scraped | implicit |
| Genre | fixed to EDM for now | stretch |

> **Parameterise the artist.** Hardcoding is a demo that dies if your scrape misses him. At T+25, look at who's actually well-represented in the data and pick your demo subject then.

## Output — top 3 only, with the denominator shown

**Surface three options, never a full table.** A shortlist is a decision; a table is homework. Three is the number a person can hold in their head and act on.

But — and this is the part that protects your score — **always state what you ranked them out of.**

```
9 shows found across 3 cities in your window.

⚠  He's playing CHICAGO on Nov 22 — you may not need to travel at all.

Top 3 worth travelling for:

1  DETROIT · Spot Lite · Oct 18 · $48
   p22 for Detroit — cheapest of the run, and a market you never hit
   → GO

2  DENVER · Mission · Nov 2 · $95
   p68 for Denver — you'd pay a premium for a room you can get cheaper elsewhere
   → SKIP

3  MILWAUKEE · The Rave · Dec 6 · $55
   p40 for Milwaukee — fair price, but close enough that it competes with waiting
   → HOLD
```

*(Illustrative — real numbers come from the scrape.)*

**Why the denominator line matters:** if you only ever show three rows, a judge can reasonably assume you only *had* three. "9 shows across 3 cities" is one line of output that proves you aggregated over a population and then filtered — which is the entire Understanding argument. Never drop it.

**The home-city callout jumps the queue.** If the artist plays the user's home city inside the window, surface that *above* the three, regardless of how it ranks. It's the most actionable output the system produces and the recommendation a naive tool would never make.

**Three verdicts:** **GO** (rare and underpriced relative to its market) · **HOLD** (he's coming to your home city, or a later date is cheaper) · **SKIP** (above the local price distribution for no scarcity reason).

## Why this is actionable

Three things a person can *do* on Friday:

1. **Buy this specific ticket** — one show, one date, one price, with a reason.
2. **Don't buy anything** — the HOLD. This is the recommendation a naive system never makes, and it's often the right one. The best answer to "where should I travel" is sometimes "nowhere, he's playing your city in November."
3. **Know what you're paying** — "$95 is the 68th percentile for Denver" turns a number you can't evaluate into a decision you can.

The user chooses. RaveScout supplies the comparison they can't do in their head — then throws away everything below rank 3, because a shortlist is a decision and a table is homework.

---

## Architecture

### One index. That's the whole cut.

`events` — one document per show. Ticket price is the cost axis (lodging is a stretch). **Scarcity and price both come from this single index**, which is why one scrape is enough.

| field | type | why |
|---|---|---|
| `city` | keyword | group by, filter |
| `event_date` | date | window filter |
| `weekend_id` | keyword | **precompute** (the Friday, e.g. `2026-10-16`) |
| `venue` | keyword | display, later scene signal |
| `artists` | keyword (array) | **the filter, and the scarcity key** |
| `title` | text | search |
| `description` | text | search (upgrade to `semantic_text` only as stretch) |
| `ticket_price` | **double** | ← the field that breaks your night if it lands as a string |
| `genre_tags` | keyword | stretch: taste filter |
| `url` | keyword | so the agent can cite |

> **The five minutes that decide everything:** verify `ticket_price` is numeric and `event_date` is a real date *before* bulk loading. Scraped prices arrive as `"$48.00"`. Changing a type later means a full reindex.

### The idea worth defending: the artist is the filter, the corpus is the yardstick

You scrape **wide** — all EDM events across 3 cities — and filter to one artist at query time.

Without the wide corpus you cannot say whether $95 is expensive, because you'd have nothing to compare it against. The full population is what converts *"the ticket costs $95"* into *"that's the 68th percentile for Denver, and his Detroit date is at the 22nd."* Filtering to one artist costs you nothing; scraping narrow would cost you the entire insight.

**Honest constraint, stated as product framing:** you only see shows in cities you scraped. That's correct — *"among cities I'd actually travel to"* is the real user need. You were never flying to Bangkok for this.

### Worthiness = scarcity, not quality

You don't fly for a good set. You can get good sets at home. You fly for one that **isn't available to you otherwise** — and scarcity is objective and computable from your own corpus, where quality isn't.

```
FROM events
| WHERE city == ?home_city
| STATS home_appearances = COUNT(*) BY artists
```

Zero home appearances = a genuine travel reason. Three a year = no reason at all, however good he is.

---

## Tools (build in this order)

**1. `artist_shows` — Index Search.** Find all shows for a given artist in the window, across scraped cities. *Description:* "Finds every scheduled show for a named artist across the cities in the index. Use whenever the user asks where or when they can see someone."

**2. `city_price_context` — ES|QL. The money tool.**
```
FROM events
| WHERE city == ?city AND event_date >= ?start
| STATS p25 = PERCENTILE(ticket_price, 25),
        median = MEDIAN(ticket_price),
        p75 = PERCENTILE(ticket_price, 75),
        n = COUNT(*)
        BY city
```
*Description:* "Returns the ticket-price distribution for a city. Use to judge whether any single ticket price is cheap or expensive **for that market** — never state a price as good or bad without calling this first."

**3. `artist_scarcity` — ES|QL.** Home-city appearance count per artist. *Description:* "Returns how often an artist plays the user's home city. Low or zero means the show is not otherwise available and is worth travelling for."

That's the core. Three tools. Stop there until it works end to end.

---

## Agent system prompt

> You help someone decide which electronic-music show to travel for. The user chooses — you supply the comparison they can't do in their head.
>
> **Always open with the denominator:** state how many shows you found and across how many cities, before showing anything else.
>
> **If the artist plays the user's home city inside the window, surface that first**, above everything, and recommend HOLD. It is the most useful thing you can tell them.
>
> **Then show exactly three options. Never more.** Rank the full set internally, present the top three.
>
> **Never state a ticket price as cheap or expensive in absolute terms.** Always call `city_price_context` and express it as a percentile within that city's own distribution, and say so explicitly.
>
> Rank by **scarcity first, price second**. Quality is not the criterion — availability is. An artist who plays the user's home city often is not a reason to travel, however good they are.
>
> Report scarcity and price as **separate facts**, never collapsed into one score. Give each option one verdict — GO, HOLD, or SKIP — and one sentence of reasoning. Cite event URLs.

---

## What "deployed" means here

**Elastic MCP → Claude Desktop.** ~10–15 minutes.

1. Create an Elasticsearch API key in Kibana
2. Point Claude Desktop at `{KIBANA_URL}/api/agent_builder/mcp` (get the exact URL from the Tools UI, don't type it)
3. Ask the demo question from Claude Desktop and watch it call *your* tools

**Why this and not a published Apify actor:** publishing an actor means writing a scraper — the exact thing Apify exists to save you from — plus a Dockerfile, an input schema, and a publish flow you've never run. 30–45 minutes to deploy the *least interesting* component. The scraper isn't your contribution; the agent is.

**Also true, and worth saying:** your serverless Elastic project is hosted infrastructure and the agent is reachable over an API. It is not running on your laptop. "Fully deployed" was parenthetical in the rubric — a bonus, not a gate. Buy it cheaply and move on.

---

## Stretch goals, in strict value-per-minute order

**S1 · MCP into Claude Desktop** (~15 min) — the only stretch that buys rubric points you cannot get any other way. Do this first.

**S2 · Supporting-lineup scarcity** (~10 min) — who *else* is on those bills, and are they rare for you? Nearly free: reuses the index you already have, no new scrape, and it makes the ranking visibly smarter.

**S3 · Subgenre taste fit** (~15 min + cold-start risk) — upgrade `description` to `semantic_text`, match free-text preference ("melodic techno and hard groove, not big-room"). Flashy, but the model deployment can silently eat ten minutes.

**S4 · Scheduled Workflow** (~10 min) — weekly refresh. Proves it keeps running without you.

**S5 · Lodging price** (~25 min) — second source, second index. **Left cut on purpose.** Say so in the demo: *"the cost axis is ticket price; lodging is the obvious extension and the architecture takes it as another index the agent joins."* Knowing what you cut and why scores better than a half-working integration.

---

## The clock, with abort conditions

**T+0 → T+20 · Apify.** One actor, 3 cities, events with prices, wide date range. Export CSV.
> **Abort:** no usable price field by T+20 → drop price entirely, rank on scarcity alone. The pitch survives.

**T+20 → T+40 · Elastic.** Project, upload, **fix the mappings**. Price numeric, date a date, artists keyword, weekend_id precomputed. Check who's well-represented and pick your demo artist.

**T+40 → T+50 · Hand-write the two ES|QL queries.**
> **Hard checkpoint:** do these numbers say something you'd act on? If not, do **not** scrape more — change the question to fit the data you have.

**T+50 → T+70 · Three tools + agent.** Test the demo question in Kibana.

**T+70 → T+85 · MCP into Claude Desktop.**
> **Abort:** anything broken at T+70 → skip deployment, fix the core instead.

**T+85 → T+100 · STOP BUILDING.** Screenshot the ranked table. Write the pitch. Say it out loud once.

That last block is not optional. Understanding is 10 points and it's your strongest category — at T+85, ninety seconds of rehearsal beats any tool you could add.

---

## Risk register

| Risk | Fallback |
|---|---|
| No price data in the scrape | Rank on scarcity alone — still a real insight |
| Chosen artist not in the data | Artist is a parameter; pick whoever *is* well-represented |
| Prices indexed as strings | Reindex with explicit mapping. Budget 10 min; this will happen at least once |
| Too few events | Widen the date range. Do **not** add a source |
| Credits burning | Cap every actor run at 25–50 items, per city |
| RA won't crawl cleanly | Fall back to Eventbrite or Ticketmaster — less scene cred, more reliable |

---

## The 60-second pitch

> **RaveScout** ranks the shows worth travelling for.
>
> The design decision I'd defend hardest: I don't score events by quality, I score them by **scarcity**. You don't fly somewhere for a good set — you fly for one you can't get at home. That turns a subjective judgement into an objective aggregation over my own corpus, and it's why the system will tell you Chicago has more events that weekend but Detroit is still the right trip — or that you shouldn't fly at all, because he's playing your city in November.
>
> **Apify** is here because event data changes daily and has no API worth using. **Elasticsearch** is here because the real question — is this ticket expensive *for Denver*, is this artist rare *for me* — is a percentile over a corpus. That needs an aggregation engine, not a bigger prompt.
>
> The agent never sees the listings. It sees three tools, picks one, and reads back a number. That's why it scales past any context window, and why the number is exact.
>
> I cut lodging on purpose — second source, second index, and I had a hundred minutes. The architecture takes it as another index the agent joins.
