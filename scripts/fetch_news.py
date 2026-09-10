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
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

import requests
import yt_dlp

ROOT = Path(__file__).resolve().parent.parent
NEWS_PATH = ROOT / "news" / "entries.jsonl"
TRANSCRIPT_DIR = ROOT / "news" / "transcripts"

# How far back to retry a missing transcript. Older gaps belong to settled gameweeks.
TRANSCRIPT_RETRY_DAYS = 10

# Captions are fetched with the local browser's YouTube session. Unauthenticated pulls
# worked until 2026-09-08 and then returned HTTP 429 for well over a day — long enough
# that it reads as an IP-level block on the timedtext endpoint rather than a burst limit.
# Cookies clear it completely.
#
# Two traps, both cost hours to find:
#   * The browser must be CLOSED. A running Chrome rotates the cookies as yt-dlp reads
#     them, and the request fails with "The page needs to be reloaded" — which looks like
#     a yt-dlp bug and is not one.
#   * Only the default `web` client exposes automatic captions. Every alternative client
#     tried (android_vr, web_safari, mweb, tv, ios) reports zero caption languages, so
#     switching client to dodge the rate limit trades the error for silence.
#
# Set to None to pull anonymously; the code falls back to that on its own if the browser
# profile cannot be read, since an unauthenticated attempt is better than no attempt.
COOKIES_FROM_BROWSER = "chrome"

# Adaptive delay between caption downloads, in seconds. Shared across videos in a run:
# a 429 is a statement about the client, not about the video that happened to trigger it.
THROTTLE_MIN = 2.0
THROTTLE_MAX = 120.0
TRANSCRIPT_ATTEMPTS = 4
_throttle = THROTTLE_MIN

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
    "fpltips": "UCVPb_jLxwaoYd-Dm7aSWQKQ",
    "letstalkfpl": "UCxeOc7eFxq37yW_Nc-69deA",
    # Added 2026-09-10, each id resolved from the channel's own @handle rather than
    # guessed. Fantasy Football Hub is where Ben Crellin and BigManBakar post; an
    # earlier note here assumed that needed per-person filtering, but the whole
    # channel is FPL content and a straight per-channel pull works.
    "fplfocal": "UC72QokPHXQ9r98ROfNZmaDw",
    "fplmate": "UCweDAlFm2LnVcOqaFU4_AGA",
    "planetfpl": "UC8043oOKTB4uP8Nq15Kz6bg",
    "fantasyfootballhub": "UCcqEr3DfrRwtoF2a1yW8qgQ",
    "fplfamily": "UCDG_EqOaaO1SSxEMZwfrSkg",
    "aboveaveragefpl": "UCnaJiRMf5hju0TlaeGK5CDQ",
    "fplsurgery": "UC6ExTqGINJ8M_GPVmVjJubA",
    # Inactive: last upload 2025-09-10, and covering FanTeam rather than FPL. Kept so
    # the decision to drop it is visible rather than silent, but it contributes nothing.
    "giannibuttice": "UCC2c5yVCFu7FKKyt6-_3uLQ",
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


def load_muted() -> set[str]:
    """Read straight from creators.json rather than importing findings.py, so the news
    fetcher keeps no dependency on the analysis side of the repo."""
    path = ROOT / "news" / "creators.json"
    if not path.exists():
        return set()
    with open(path) as f:
        raw = json.load(f)
    return {slug for slug, row in raw.items()
            if isinstance(row, dict) and row.get("muted")}


def list_channel_uploads(source: str, channel_id: str, limit: int = 15) -> list[dict]:
    """Recent uploads for one channel, via yt-dlp rather than the Atom feed.

    `https://www.youtube.com/feeds/videos.xml?channel_id=...` began returning 404 for
    every channel on 2026-09-08 — including YouTube's own official channel, and in the
    `playlist_id=UU...` form, with a browser User-Agent, while the channel pages
    themselves still returned 200. The 404 came from YouTube's own "RSS Feeds server",
    so the endpoint is answering and refusing rather than being unreachable. That is not
    something a channel ID can fix, so upload discovery moved to the code path that still
    works — the same yt-dlp that already pulls the captions.

    One request per channel. A flat listing carries no publish date (`upload_date` and
    `timestamp` both come back None), so the date is fetched per video by
    `video_metadata`, and only for videos not already in the index.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
    }
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    items = []
    for entry in info.get("entries") or []:
        video_id = entry.get("id")
        title = (entry.get("title") or "").strip()
        if not video_id or not title:
            continue
        items.append(
            {
                "kind": "video",
                "source": source,
                "title": title,
                "link": f"https://www.youtube.com/watch?v={video_id}",
                "video_id": video_id,
                "published": None,  # filled by video_metadata for new videos only
                "summary": None,
            }
        )
    return items


def video_metadata(video_id: str) -> dict:
    """Publish date and description for one video.

    Separate from the flat listing because it costs a request per video, and separate
    from `pull_transcript` because captions fail on their own schedule — a video whose
    captions are rate-limited still deserves a correctly dated index entry, so that a
    later run can retry the transcript instead of losing the video entirely.
    """
    time.sleep(1)
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    stamp = info.get("timestamp")
    published = (
        datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()
        if stamp
        else _date_from_upload_date(info.get("upload_date"))
    )
    return {"published": published, "summary": strip_html(info.get("description"))}


def _date_from_upload_date(value: str | None) -> str | None:
    """`upload_date` is YYYYMMDD with no time. Midnight UTC is a stand-in, and the
    relevance filter compares against deadlines a day apart, so the imprecision is
    tolerable — an absent date is not, since it removes the video from the queue."""
    if not value or len(value) != 8:
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}T00:00:00+00:00"


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
    A fixed delay was not enough once the channel list grew. Moving upload discovery to
    yt-dlp brought 54 videos in one run, and a flat two seconds between them produced
    HTTP 429 on nearly every caption download — the delay stops you causing rate limiting
    from a standing start, but does nothing to recover once you are already limited. So
    429 now backs off and retries, and the backoff persists across videos: having been
    told to slow down, the next video should not immediately ask at the old rate.
    """
    global _throttle
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
    if COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER, None, None, None)
    # Captions are the only thing wanted here, so a missing video format is not an error.
    opts["ignore_no_formats_error"] = True

    for attempt in range(TRANSCRIPT_ATTEMPTS):
        time.sleep(_throttle)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            # Ease back gradually rather than snapping to the floor, so one success in
            # the middle of a limited run doesn't restart the burst that caused it.
            _throttle = max(THROTTLE_MIN, _throttle * 0.7)
            break
        except Exception as exc:  # noqa: BLE001 - one video's captions shouldn't block the rest
            # An unreadable browser profile shouldn't stop the run — drop the cookies and
            # let the attempt proceed anonymously rather than failing outright.
            if "cookies" in str(exc).lower() and opts.pop("cookiesfrombrowser", None):
                print(f"    browser cookies unavailable ({exc}) — continuing without them")
                continue
            if "429" not in str(exc) or attempt == TRANSCRIPT_ATTEMPTS - 1:
                print(f"    transcript for {video_id} failed ({exc}) — skipping")
                return None
            _throttle = min(THROTTLE_MAX, max(_throttle * 3, 8))
            print(f"    rate limited on {video_id} — backing off to {_throttle:.0f}s")

    vtt_candidates = list(TRANSCRIPT_DIR.glob(f"{video_id}.*.vtt"))
    if not vtt_candidates:
        return None
    vtt_path = vtt_candidates[0]
    text = clean_vtt(vtt_path.read_text(encoding="utf-8"))
    txt_path = TRANSCRIPT_DIR / f"{video_id}.txt"
    txt_path.write_text(text, encoding="utf-8")
    vtt_path.unlink()
    return str(txt_path.relative_to(ROOT))


def main(skip_transcripts: bool = False) -> None:
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

    # Discovery first, and saved before any caption is pulled. Captions are the slow,
    # rate-limited half of this job; when it was one interleaved loop, killing a run
    # part-way through the transcript phase threw away every video it had discovered,
    # because the index was only written at the very end. Twice.
    muted = load_muted()
    for source, channel_id in VIDEO_CHANNELS.items():
        if source in muted:
            print(f"  news: {source} (video) — muted, skipping")
            continue
        try:
            items = list_channel_uploads(source, channel_id)
        except Exception as exc:  # noqa: BLE001 - one dead channel shouldn't block the others
            print(f"  news: {source} (video) failed ({exc}) — skipping")
            continue
        added = 0
        for item in items:
            key = (item["source"], item["link"])
            if key in seen:
                continue
            item["fetched_at"] = fetched_at
            try:
                item.update(video_metadata(item["video_id"]))
            except Exception as exc:  # noqa: BLE001 - one video shouldn't block the rest
                print(f"    metadata for {item['video_id']} failed ({exc}) — skipping")
                continue
            if not item["published"]:
                print(f"    no publish date for {item['video_id']} — skipping")
                continue
            # Only mark it seen once it is actually going into the index, so a video
            # dropped for a transient failure is retried on the next run rather than
            # silently never fetched again.
            seen.add(key)
            item["transcript_file"] = None
            existing.append(item)
            added += 1
        new_count += added
        print(f"  news: {source} (video) — {len(items)} in feed, {added} new")

    if new_count:
        save_entries(existing)

    if skip_transcripts:
        pending = sum(1 for item in existing
                      if item.get("video_id") and not item.get("transcript_file"))
        print(f"  news: skipping transcripts ({pending} pending)")
        return

    # A newly discovered video and one whose caption pull failed last week are the same
    # case — an indexed video with no transcript — so there is one loop for both.
    # `prepare_extraction.py` only queues entries whose transcript file exists, so a
    # video stuck here is invisible to the work list; FPL Harry's GW4 Chelsea-Hull video
    # sat unfetched exactly that way while the queue reported nothing to do.
    #
    # Bounded to recent uploads: an older gap belongs to a settled gameweek and is worth
    # nothing, and some videos never have captions at all.
    cutoff = datetime.now(timezone.utc) - timedelta(days=TRANSCRIPT_RETRY_DAYS)
    wanted = [
        item for item in existing
        if item.get("video_id")
        and not item.get("transcript_file")
        and item.get("published")
        and datetime.fromisoformat(item["published"]) >= cutoff
    ]
    print(f"  news: {len(wanted)} video(s) need a transcript")
    got = 0
    for item in wanted:
        path = pull_transcript(item["video_id"])
        if not path:
            continue
        item["transcript_file"] = path
        got += 1
        print(f"  news: transcript for {item['source']} {item['video_id']}")
        # Saved as they land. Captions arrive slowly and unreliably, and a run killed
        # half way should keep what it already fetched.
        save_entries(existing)
    print(f"  news: {got} of {len(wanted)} transcripts fetched")

    print(f"wrote {NEWS_PATH.relative_to(ROOT)} ({len(existing)} total, {new_count} new this run)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-transcripts", action="store_true",
                        help="Index new uploads only; leave captions for a later run")
    _args = parser.parse_args()
    main(skip_transcripts=_args.skip_transcripts)
