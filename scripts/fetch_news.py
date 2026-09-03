"""Pull free FPL-adjacent RSS feeds and video transcripts, append new items to
news/entries.jsonl.

Called automatically from fetch_data.py's main() — there is no separate cron or
schedule; this runs whenever you refresh the data cache, so "what did we know and
when" stays tied to the same weekly loop instead of needing its own trigger.

Why append-only and why tracked in git (unlike data/, which is disposable cache):
an RSS feed only ever shows its most recent items. Once an item scrolls off, it is
gone — there is no backfill endpoint, the same problem set-piece order has in
bootstrap-static. Overwriting this file on every run would silently destroy that
history exactly the way fetch_data.py used to destroy set-piece order before
snapshots existed. Append-only + git-tracked is the fix.

Two kinds of item: "article" (blog RSS — headline, link, summary only) and "video"
(YouTube upload — headline, link, summary, plus a pulled transcript where one's
available). The index itself stays lightweight either way; transcripts are stored
as their own files under news/transcripts/, referenced by path, not inlined — a
transcript can run thousands of words and would blow up a file meant for short
items. Interpreting any of this — what a headline or transcript means for a
minutes prior or a transfer call — happens in the LLM judgment layer, not here.
This script's only job is to make sure nothing that was said gets lost before that
layer gets a chance to read it.

Usage:
    python scripts/fetch_news.py          # run standalone
    python scripts/fetch_data.py          # also runs this automatically
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

import requests
import yt_dlp

ROOT = Path(__file__).resolve().parent.parent
NEWS_PATH = ROOT / "news" / "entries.jsonl"
TRANSCRIPT_DIR = ROOT / "news" / "transcripts"

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

# Resolve a channel ID from the channel page's "externalId" field, NOT from the first
# "channelId" string in the markup — that one also appears for related and featured
# channels, and picking it silently pulls somebody else's uploads. fplblackbox was wrong
# for exactly this reason until 2026-09-03: it pointed at "BlackBox Gaming", a separate
# channel from the same brand, and ingested five horror-game livestreams as FPL analysis.
#
# Named trusted creators with their own channel, verified live 2026-09-03. Two more
# named in the design discussion (Ben Crellin, BigMan Bakar) don't have their own
# channel — they appear on Fantasy Football Hub's shared one — and aren't included
# here since that needs filtering by name, not a straight per-channel pull.
VIDEO_CHANNELS = {
    "fplharry": "UCcPWnCj5AKC19HaySZjb25g",
    "fplblackbox": "UCGJ8-xqhOLwyJNuPMsVoQWQ",
    "fplgeneral": "UCxj4WVoWBuwXPGJsvUFPVig",
    "fplraptor": "UC54QLWzsMifTRjNQ02z5pCw",
    "giannibuttice": "UCC2c5yVCFu7FKKyt6-_3uLQ",
}

_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
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


def parse_video_feed(xml_bytes: bytes, source: str) -> list[dict]:
    """YouTube's per-channel upload feed is Atom, not RSS 2.0 — different tags
    (<entry> not <item>, videoId under the yt: namespace, link as an href attribute
    rather than element text). Confirmed live 2026-09-03 against FPL Harry's channel."""
    ns = _ATOM_NS
    root = ElementTree.fromstring(xml_bytes)
    items = []
    for entry in root.findall("atom:entry", ns):
        video_id = entry.findtext("yt:videoId", namespaces=ns)
        title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
        if not video_id or not title:
            continue
        group = entry.find("media:group", ns)
        description = (
            group.findtext("media:description", namespaces=ns) if group is not None else None
        )
        items.append(
            {
                "kind": "video",
                "source": source,
                "title": title,
                "link": f"https://www.youtube.com/watch?v={video_id}",
                "video_id": video_id,
                "published": entry.findtext("atom:published", namespaces=ns),
                "summary": strip_html(description),
            }
        )
    return items


def fetch_video_feed(source: str, channel_id: str) -> list[dict]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    resp = requests.get(url, timeout=15, headers={"User-Agent": "fpl-decision-engine/1.0"})
    resp.raise_for_status()
    return parse_video_feed(resp.content, source)


def clean_vtt(vtt_text: str) -> str:
    """YouTube's auto-captions are a "roll-up" style: each cue repeats a growing
    prefix of the previous cue's text plus new words, with per-word timing tags
    inline. Strip both the outer cue timestamps and the inline word tags, then keep
    only the new suffix each cue adds over the last, to reconstruct flowing text
    without the repetition. Verified against a real 227KB caption file — output was
    clean, correctly-ordered prose, not garbled."""
    lines = []
    for raw_line in vtt_text.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            continue
        if "-->" in line:
            continue
        line = _TAG_RE.sub("", line).strip()
        if line:
            lines.append(line)

    out_words = []
    prev = ""
    for line in lines:
        if line == prev:
            continue
        if line.startswith(prev):
            out_words.append(line[len(prev) :].strip())
        else:
            out_words.append(line)
        prev = line
    return re.sub(r"\s+", " ", " ".join(w for w in out_words if w)).strip()


def pull_transcript(video_id: str) -> str | None:
    """Auto-generated captions, pulled via yt-dlp — a raw scrape of the same signed
    caption URL yt-dlp itself extracts returns HTTP 200 with an empty body from here
    (verified 2026-09-03, reproducibly, from a real residential IP, not a cloud
    sandbox); yt-dlp's own extraction logic is a different code path and works.
    Returns the relative path (from repo root) to the cleaned transcript text, or
    None if no captions were available for this video — not every video has them,
    and that's not an error worth surfacing louder than a skip.

    A courtesy delay before each pull: a first real run against 65 videos hit
    `HTTP 429 Too Many Requests` on 5 of them after a handful of back-to-back
    requests (2026-09-03). Fetch cost isn't a constraint here — a few minutes of
    delay on a weekly job is nothing — but tripping YouTube's rate limiting is a
    real failure mode worth just not causing. Two other failure modes seen in that
    run aren't fixable this way: unstarted livestreams (will resolve once they
    air) and age-restricted videos (need authenticated cookies to bypass, which
    isn't worth building — same call already made against session-cookie auth for
    the FPL `my-team` endpoint).
    """
    time.sleep(2)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    opts = {
        "skip_download": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "vtt",
        "outtmpl": str(TRANSCRIPT_DIR / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except Exception as exc:  # noqa: BLE001 - one video's captions failing shouldn't block the rest
        print(f"    transcript for {video_id} failed ({exc}) — skipping")
        return None

    vtt_candidates = list(TRANSCRIPT_DIR.glob(f"{video_id}.*.vtt"))
    if not vtt_candidates:
        return None
    vtt_path = vtt_candidates[0]
    text = clean_vtt(vtt_path.read_text(encoding="utf-8"))
    txt_path = TRANSCRIPT_DIR / f"{video_id}.txt"
    txt_path.write_text(text, encoding="utf-8")
    vtt_path.unlink()
    return str(txt_path.relative_to(ROOT))


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
            item.setdefault("kind", "article")
            key = (item["source"], item["link"])
            if key in seen:
                continue
            seen.add(key)
            item["fetched_at"] = fetched_at
            existing.append(item)
            added += 1
        new_count += added
        print(f"  news: {source} — {len(items)} in feed, {added} new")

    for source, channel_id in VIDEO_CHANNELS.items():
        try:
            items = fetch_video_feed(source, channel_id)
        except Exception as exc:  # noqa: BLE001 - one dead channel shouldn't block the others
            print(f"  news: {source} (video) failed ({exc}) — skipping")
            continue
        added = 0
        for item in items:
            key = (item["source"], item["link"])
            if key in seen:
                continue
            seen.add(key)
            item["fetched_at"] = fetched_at
            item["transcript_file"] = pull_transcript(item["video_id"])
            existing.append(item)
            added += 1
        new_count += added
        print(f"  news: {source} (video) — {len(items)} in feed, {added} new")

    if new_count:
        save_entries(existing)
    print(f"wrote {NEWS_PATH.relative_to(ROOT)} ({len(existing)} total, {new_count} new this run)")


if __name__ == "__main__":
    main()
