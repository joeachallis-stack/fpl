"""Pull free FPL-adjacent RSS feeds and append new items to news/entries.jsonl.

Called automatically from fetch_data.py's main() — there is no separate cron or
schedule; this runs whenever you refresh the data cache, so "what did we know and
when" stays tied to the same weekly loop instead of needing its own trigger.

Why append-only and why tracked in git (unlike data/, which is disposable cache):
an RSS feed only ever shows its most recent items. Once an item scrolls off, it is
gone — there is no backfill endpoint, the same problem set-piece order has in
bootstrap-static. Overwriting this file on every run would silently destroy that
history exactly the way fetch_data.py used to destroy set-piece order before
snapshots existed. Append-only + git-tracked is the fix.

This is deliberately headlines-and-links, not full article text or any judgment
about what a headline means — that reading happens in the LLM judgment layer
(minutes priors, transfer context), not here. This script's only job is to make
sure nothing that was said gets lost before that layer gets a chance to read it.

Usage:
    python scripts/fetch_news.py          # run standalone
    python scripts/fetch_data.py          # also runs this automatically
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

import requests

ROOT = Path(__file__).resolve().parent.parent
NEWS_PATH = ROOT / "news" / "entries.jsonl"

# Free, no-key RSS feeds confirmed live as of 2026-09-03. FPL-specific content is
# thin online — most sites either have no feed or paywall the useful part (FFS's
# own "Scout Picks" analysis is members-only; this feed gives headline + link only).
# Re-check these URLs if a feed starts silently returning nothing — WordPress sites
# occasionally move /feed/ or redirect apex<->www.
FEEDS = {
    "fantasyfootballscout": "https://www.fantasyfootballscout.co.uk/feed/",
    "fplhints": "https://www.fplhints.com/blog-feed.xml",
    "fpltoolbox": "https://fpltoolbox.com/feed/",
}

_TAG_RE = re.compile(r"<[^>]+>")


def load_entries() -> list[dict]:
    if not NEWS_PATH.exists():
        return []
    with open(NEWS_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def save_entries(entries: list[dict]) -> None:
    NEWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(NEWS_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def strip_html(text: str | None) -> str:
    """RSS descriptions are usually a paragraph of raw HTML. Keep the words, not
    the markup — this is a headline index, not a renderer."""
    if not text:
        return ""
    return unescape(_TAG_RE.sub("", text)).strip()


def parse_pubdate(raw: str | None) -> str | None:
    """RSS dates are RFC 822 (e.g. 'Wed, 03 Sep 2026 09:00:00 +0000'). Normalize to
    ISO 8601 where possible; keep the raw string if the format is unexpected rather
    than dropping the item."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return raw


def parse_feed(xml_bytes: bytes, source: str) -> list[dict]:
    root = ElementTree.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            continue
        items.append(
            {
                "source": source,
                "title": unescape(title),
                "link": link,
                "published": parse_pubdate(item.findtext("pubDate")),
                "summary": strip_html(item.findtext("description")),
            }
        )
    return items


def fetch_feed(source: str, url: str) -> list[dict]:
    resp = requests.get(url, timeout=15, headers={"User-Agent": "fpl-decision-engine/1.0"})
    resp.raise_for_status()
    return parse_feed(resp.content, source)


def main() -> None:
    existing = load_entries()
    seen = {(e["source"], e["link"]) for e in existing}
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    new_count = 0
    for source, url in FEEDS.items():
        try:
            items = fetch_feed(source, url)
        except Exception as exc:  # noqa: BLE001 - one dead feed shouldn't block the others
            print(f"  news: {source} failed ({exc}) — skipping")
            continue
        added = 0
        for item in items:
            key = (item["source"], item["link"])
            if key in seen:
                continue
            seen.add(key)
            item["fetched_at"] = fetched_at
            existing.append(item)
            added += 1
        new_count += added
        print(f"  news: {source} — {len(items)} in feed, {added} new")

    if new_count:
        save_entries(existing)
    print(f"wrote {NEWS_PATH.relative_to(ROOT)} ({len(existing)} total, {new_count} new this run)")


if __name__ == "__main__":
    main()
