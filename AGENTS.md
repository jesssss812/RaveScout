# AGENTS.md — RaveScout

Apify scrapes events → Elasticsearch indexes them → an Agent Builder agent answers *"where and when should I see {artist}?"* with three ranked options.

**Read `ravescout_spec.md` (product) and `ravescout_agent_brief.md` (build plan) before writing code.** Schema, tools, and steps live there — not here.

## Rules

- **Secrets from env only**: `APIFY_TOKEN`, `ES_URL`, `ES_API_KEY`, `KIBANA_URL`. Never hardcode, print, or commit. Fail loudly if missing.
- **Never fabricate data.** No sample rows, placeholder prices, or mocked responses. If real data is missing, stop and say so.
- **Always PUT an explicit mapping** before loading. Inferred mappings turn prices into strings and silently break every aggregation. This is the most likely way the project fails.
- **Check the `errors` flag on `_bulk`.** Never report success on a partial failure.
- Flat procedural scripts. No classes, config frameworks, Docker, or tests beyond `verify.py`. Working beats elegant.
- Comment the *why* on non-obvious calls — the author defends every decision to a judge.

## Invariants — deliberate decisions, not gaps. Do not "improve" them.

- **One index.** Ticket price is the cost axis; scarcity and price both come from `events`. Lodging was cut on purpose.
- **Artist is the filter, corpus is the yardstick.** Scrape wide, filter at query time. Narrowing the scrape destroys the percentile insight.
- **Rank by scarcity, not quality.** No popularity scores, no external rating sources.
- **Exactly three options, always led by the denominator** ("9 shows across 3 cities"). Home-city callout jumps above the three.
- **The agent never sees raw listings.** No tool that dumps documents into context.

## Stop and report

Any step past 15 min · no usable price field (fall back to scarcity-only) · most prices unparseable (show 10 raw examples) · Agent Builder API unclear (build tools by hand in Kibana instead) · too few events — **do not add a data source**, that's the author's call.
