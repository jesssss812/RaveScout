"""Shared helpers: env vars and HTTP. Stdlib only — no pip installs to fail at T+60."""
import json
import os
import sys
import urllib.error
import urllib.request


def env(name):
    val = os.environ.get(name)
    if not val:
        sys.exit(f"FATAL: environment variable {name} is not set. Export it and re-run.")
    return val


def http(method, url, headers=None, body=None, timeout=60):
    """Returns (status, parsed-json-or-text). Raises SystemExit with the response body on HTTP errors."""
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:2000]
        sys.exit(f"FATAL: {method} {url} -> HTTP {e.code}\n{detail}")
    except urllib.error.URLError as e:
        sys.exit(f"FATAL: {method} {url} -> {e.reason}")


def es_headers():
    return {
        "Authorization": f"ApiKey {env('ES_API_KEY')}",
        "Content-Type": "application/json",
    }
