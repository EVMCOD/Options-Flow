#!/usr/bin/env python3
"""
Seed symbol events from a JSON file.

Usage:
    python scripts/seed_events.py                          # uses default data/earnings_seed.json
    python scripts/seed_events.py path/to/custom.json
    python scripts/seed_events.py --api-url http://host:8000

Calls POST /api/v1/events/bulk — idempotent (skips exact duplicates).
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    import urllib.request, urllib.error  # fallback

DEFAULT_FILE = Path(__file__).parent.parent / "data" / "earnings_seed.json"
DEFAULT_URL = "http://localhost:8000"


def seed(seed_file: Path, api_url: str) -> None:
    events = json.loads(seed_file.read_text())
    url = f"{api_url.rstrip('/')}/api/v1/events/bulk"
    payload = json.dumps(events).encode()

    print(f"Loading {len(events)} events from {seed_file}")
    print(f"  → {url}")

    try:
        import httpx
        resp = httpx.post(url, content=payload, headers={"Content-Type": "application/json"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except ImportError:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
            sys.exit(1)

    result = data.get("data", {})
    print(f"  created: {result.get('created', '?')}  skipped: {result.get('skipped', '?')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed events from JSON")
    parser.add_argument("file", nargs="?", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--api-url", default=DEFAULT_URL)
    args = parser.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    seed(args.file, args.api_url)
