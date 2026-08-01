"""Step 5: create the three Agent Builder tools + the RaveScout agent via the
Kibana API. Idempotent: deletes then recreates each, so re-running is safe.

API shape per Elastic docs (agent-builder-api-tutorial): POST /api/agent_builder/tools
with {id, type: "esql", description, configuration: {query, params}}, and
POST /api/agent_builder/agents with instructions under configuration.instructions.

All three tools are ES|QL (not index_search) on purpose: exact output columns,
case-insensitive artist matching, and the URL comes back for citation.

If any call here 4xxs and the fix isn't obvious in 5 minutes: STOP and create
these by hand in the Kibana Agent Builder UI — ten minutes, not worth a fight.

Usage: python3 create_tools.py
"""
import json
import sys
import urllib.error
import urllib.request

from common import env, http

KIBANA = env("KIBANA_URL").rstrip("/")
HEADERS = {
    "Authorization": f"ApiKey {env('ES_API_KEY')}",
    "Content-Type": "application/json",
    "kbn-xsrf": "true",
}

TOOLS = [
    {
        "id": "artist_shows",
        "type": "esql",
        "description": ("Finds every scheduled show for a named artist across all "
                        "cities in the index. Use whenever the user asks where or "
                        "when they can see a specific artist. Matching is "
                        "case-insensitive on the exact artist name."),
        "configuration": {
            "query": ("FROM events "
                      "| MV_EXPAND artists "
                      "| WHERE TO_LOWER(artists) == TO_LOWER(?artist) "
                      "| KEEP city, event_date, weekend_id, venue, title, ticket_price, url "
                      "| SORT event_date ASC "
                      "| LIMIT 100"),
            "params": {
                "artist": {"type": "string", "description": "Artist name, e.g. 'John Summit'"},
            },
        },
    },
    {
        "id": "city_price_context",
        "type": "esql",
        "description": ("Returns the ticket-price distribution — 25th percentile, "
                        "median, 75th percentile, and sample size — for a given "
                        "city. Use to judge whether a single ticket price is cheap "
                        "or expensive FOR THAT MARKET. Never state a price as good "
                        "or bad without calling this first."),
        "configuration": {
            "query": ("FROM events "
                      "| WHERE city == ?city AND ticket_price IS NOT NULL "
                      "| STATS p25 = PERCENTILE(ticket_price, 25), "
                      "median = MEDIAN(ticket_price), "
                      "p75 = PERCENTILE(ticket_price, 75), "
                      "n = COUNT(*) "
                      "BY city"),
            "params": {
                "city": {"type": "string", "description": "City name, title case, e.g. 'Denver'"},
            },
        },
    },
    {
        "id": "artist_scarcity",
        "type": "esql",
        "description": ("Returns how many times an artist plays the user's home "
                        "city within the indexed window. Zero or low means the "
                        "show is not otherwise available and is worth travelling "
                        "for; a high count means the user should wait rather than "
                        "travel."),
        "configuration": {
            "query": ("FROM events "
                      "| WHERE city == ?home_city "
                      "| MV_EXPAND artists "
                      "| WHERE TO_LOWER(artists) == TO_LOWER(?artist) "
                      "| STATS home_appearances = COUNT(*)"),
            "params": {
                "artist": {"type": "string", "description": "Artist name"},
                "home_city": {"type": "string", "description": "The user's home city, e.g. 'Chicago'"},
            },
        },
    },
]

# Verbatim from ravescout_spec.md — the denominator line, home-city callout, and
# exactly-three rule are load-bearing product behavior.
INSTRUCTIONS = """You help someone decide which electronic-music show to travel for. The user chooses — you supply the comparison they can't do in their head.

Always open with the denominator: state how many shows you found and across how many cities, before showing anything else.

If the artist plays the user's home city inside the window, surface that first, above everything, and recommend HOLD. It is the most useful thing you can tell them.

Then show exactly three options. Never more. Rank the full set internally, present the top three.

Never state a ticket price as cheap or expensive in absolute terms. Always call city_price_context and express it as a percentile within that city's own distribution, and say so explicitly.

Rank by scarcity first, price second. Quality is not the criterion — availability is. An artist who plays the user's home city often is not a reason to travel, however good they are.

Report scarcity and price as separate facts, never collapsed into one score. Give each option one verdict — GO, HOLD, or SKIP — and one sentence of reasoning. Cite event URLs.

If ticket prices are unavailable in the data, say so once, plainly, and rank on scarcity alone — do not guess prices, and do not keep retrying tools that return nothing. Call artist_shows first, exactly once, and treat its result as the complete set of the artist's shows."""

AGENT = {
    "id": "ravescout",
    "name": "RaveScout",
    "description": "Ranks the electronic-music shows worth travelling for: scarcity first, price second, three options max.",
    "configuration": {
        "instructions": INSTRUCTIONS,
        "tools": [{"tool_ids": ["artist_shows", "city_price_context", "artist_scarcity"]}],
    },
}


def delete_quiet(url):
    req = urllib.request.Request(url, method="DELETE", headers=HEADERS)
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except (urllib.error.HTTPError, urllib.error.URLError):
        return False  # 404 = didn't exist yet; fine


for tool in TOOLS:
    if delete_quiet(f"{KIBANA}/api/agent_builder/tools/{tool['id']}"):
        print(f"deleted existing tool {tool['id']}")
    http("POST", f"{KIBANA}/api/agent_builder/tools", headers=HEADERS, body=tool)
    print(f"created tool: {tool['id']}")

if delete_quiet(f"{KIBANA}/api/agent_builder/agents/{AGENT['id']}"):
    print("deleted existing agent ravescout")
http("POST", f"{KIBANA}/api/agent_builder/agents", headers=HEADERS, body=AGENT)
print("created agent: ravescout")

print("""
DONE. Next:
  1. Open Kibana -> Agent Builder -> chat with 'RaveScout'
  2. Ask: "I want to see <artist> in the next 5 months. When and where should I go?"
  3. MCP endpoint for Claude Desktop: {kibana}/api/agent_builder/mcp
     (confirm the exact URL in the Agent Builder Tools UI)""".format(kibana=KIBANA))
