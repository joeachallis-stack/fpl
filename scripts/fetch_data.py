"""Fetch and cache official FPL API data to data/.

Usage:
    python scripts/fetch_data.py              # fetch everything for the configured team
    python scripts/fetch_data.py --gw 3        # also fetch picks for a specific gameweek
    python scripts/fetch_data.py --skip-slow   # bootstrap/fixtures/entry only
    python scripts/fetch_data.py --refresh-summaries   # re-pull every player summary
    python scripts/fetch_data.py --refresh-odds        # ignore the two-hour odds cache
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import fetch_news
import odds
import observations

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
BASE = "https://fantasy.premierleague.com/api"

# Leagues bigger than this are global/sponsor leagues — the standings are hundreds of
# pages of strangers. Only pull the ones with actual rivals in them.
LEAGUE_SIZE_LIMIT = 500

# Standings come 50 to a page; enough pages to cover LEAGUE_SIZE_LIMIT with headroom.
MAX_STANDINGS_PAGES = 12

# Courtesy delay between the ~650 back-to-back element-summary calls. The endpoint is
# undocumented and has no published rate limit, and the downside isn't a slow run — it's
# losing access to the API this whole project depends on. Only the first run pays the
# full cost; later runs skip anything already fresh.
SUMMARY_DELAY_S = 0.4

# element-summary history only gains a row when a match is played, so a day-old cache is
# not meaningfully stale. --refresh-summaries overrides this.
SUMMARY_MAX_AGE_H = 24


def load_config() -> dict:
    with open(ROOT / "config.json") as f:
        return json.load(f)


def fetch(url: str, retries: int = 4) -> dict:
    """GET with real backoff on 429 — retry after a delay, not just a pause between calls.

    Honours Retry-After when the server sends one, otherwise doubles its own wait. After
    the retries are exhausted it raises rather than continuing to hammer: the caller is
    expected to abort the bulk pull, not push on through a rate limit.
    """
    delay = 2.0
    for attempt in range(retries + 1):
        resp = requests.get(url, timeout=15)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After") or delay)
            if attempt == retries:
                raise RuntimeError(f"rate limited by {url} after {retries} retries")
            print(f"  429 rate limited, waiting {wait:.0f}s (retry {attempt + 1}/{retries})")
            time.sleep(wait)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"unreachable: {url}")


def save(name: str, payload: dict, quiet: bool = False) -> None:
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    if not quiet:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def save_snapshot(payload: dict) -> None:
    """Dated copy of bootstrap-static, kept alongside the overwritten live cache.

    Set-piece order (penalties_order, direct_freekicks_order, corners_and_
    indirect_freekicks_order) is the one input the API never backfills — it only ever
    shows the current state, and plain `save()` overwrites it every run. One snapshot a
    day is enough to catch a change; it does not need git history, just to survive being
    overwritten tomorrow.
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = SNAPSHOT_DIR / f"bootstrap_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def fetch_standings(league_id: int) -> dict:
    """Page through a classic league's standings and merge into one payload."""
    merged = fetch(f"{BASE}/leagues-classic/{league_id}/standings/?page_standings=1")
    truncated = bool(merged["standings"].get("has_next"))
    for page in range(2, MAX_STANDINGS_PAGES + 1):
        if not truncated:
            break
        chunk = fetch(f"{BASE}/leagues-classic/{league_id}/standings/?page_standings={page}")
        merged["standings"]["results"].extend(chunk["standings"]["results"])
        truncated = bool(chunk["standings"].get("has_next"))
    # The merged payload holds every page we pulled, so page one's has_next would lie
    # to anything reading the cache.
    merged["standings"]["has_next"] = truncated
    if truncated:
        print(f"  warning: league {league_id} exceeded {MAX_STANDINGS_PAGES} pages, truncated")
    return merged


def is_fresh(name: str, max_age_h: float) -> bool:
    path = DATA_DIR / name
    if not path.exists():
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return age_h < max_age_h


def fetch_element_summaries(
    bootstrap: dict, owned: list[int], refresh: bool = False
) -> None:
    """Per-gameweek history for the whole player pool, not just the owned squad.

    The minutes model needs a role signal for anyone who might start getting minutes,
    which a watchlist by definition can't cover — the player worth spotting is the one
    nobody is watching yet. That means ~650 sequential calls against an undocumented
    endpoint, so this backs off properly on a 429 and aborts the bulk pull rather than
    keeping on if the API pushes back.

    Owned players go first and always refresh: they're what check_team.py reads, and if
    the bulk pull dies partway the squad is still current.
    """
    owned_set = set(owned)
    ids = [e["id"] for e in bootstrap["elements"]]
    ordered = owned + [i for i in ids if i not in owned_set]

    fetched = skipped = 0
    print(f"element summaries: {len(ordered)} players")
    for n, pid in enumerate(ordered, 1):
        name = f"element_summary/{pid}.json"
        force = pid in owned_set or refresh
        if not force and is_fresh(name, SUMMARY_MAX_AGE_H):
            skipped += 1
            continue
        try:
            save(name, fetch(f"{BASE}/element-summary/{pid}/"), quiet=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  aborted at player {pid} after {fetched} fetched ({exc})")
            print("  re-run to resume — anything already written is kept")
            return
        fetched += 1
        if fetched % 50 == 0:
            print(f"  {n}/{len(ordered)} ({fetched} fetched, {skipped} already fresh)")
        time.sleep(SUMMARY_DELAY_S)
    print(f"  done: {fetched} fetched, {skipped} already fresh")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, default=None, help="Gameweek to fetch picks for")
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        help="Skip per-player summaries and league standings (many requests)",
    )
    parser.add_argument(
        "--refresh-summaries",
        action="store_true",
        help=f"Re-pull every player summary, ignoring the {SUMMARY_MAX_AGE_H}h freshness check",
    )
    parser.add_argument(
        "--refresh-odds",
        action="store_true",
        help="ignore the two-hour bookmaker-odds cache",
    )
    args = parser.parse_args()

    config = load_config()
    team_id = config["team_id"]

    bootstrap = fetch(f"{BASE}/bootstrap-static/")
    save("bootstrap.json", bootstrap)
    save_snapshot(bootstrap)
    fixtures = fetch(f"{BASE}/fixtures/")
    save("fixtures.json", fixtures)
    save("event_status.json", fetch(f"{BASE}/event-status/"))

    # Optional near-term bookmaker probabilities. A missing key or source failure must
    # never block the official FPL refresh that the rest of the project depends on.
    try:
        odds.run(bootstrap, fixtures, refresh=args.refresh_odds)
    except Exception as exc:  # noqa: BLE001 - optional third-party source
        print(f"odds: refresh failed ({exc}) — keeping any existing cache")

    # Free-text FPL news (RSS headlines, not official API data). Tied to this same
    # run rather than its own schedule — see fetch_news.py's docstring for why.
    # Third-party sites are flakier than the official API; a dead feed shouldn't
    # abort the rest of the fetch.
    try:
        fetch_news.main()
    except Exception as exc:  # noqa: BLE001
        print(f"  news: fetch_news.py failed entirely ({exc}) — continuing without it")

    entry = fetch(f"{BASE}/entry/{team_id}/")
    save("entry.json", entry)
    save("history.json", fetch(f"{BASE}/entry/{team_id}/history/"))
    save("transfers.json", fetch(f"{BASE}/entry/{team_id}/transfers/"))

    current_gw = args.gw or entry.get("current_event")
    picks = None
    if current_gw:
        picks = fetch(f"{BASE}/entry/{team_id}/event/{current_gw}/picks/")
        save(f"picks_gw{current_gw}.json", picks)

    if args.skip_slow:
        return

    # Per-player fixture history + remaining fixtures, for the whole pool — the minutes
    # model trains on it. See fetch_element_summaries for why it isn't a watchlist.
    owned = [pick["element"] for pick in picks["picks"]] if picks else []
    fetch_element_summaries(bootstrap, owned, refresh=args.refresh_summaries)
    observations.append_finalized()

    # Standings for the small leagues — rivals worth knowing about, not sponsor leagues.
    for league in entry.get("leagues", {}).get("classic", []):
        if league.get("rank_count") and league["rank_count"] <= LEAGUE_SIZE_LIMIT:
            save(f"standings_{league['id']}.json", fetch_standings(league["id"]))


if __name__ == "__main__":
    main()
