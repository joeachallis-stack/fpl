"""The findings schema: its vocabulary, its loader, and its validator.

Extraction produces three constrained fields — `topic`, `kind`, `horizon` — and nothing
used to check them. The four validation layers in the gameweek-brief skill all guard
*identity*: they catch a fabricated player and say nothing about a fabricated category.
That was tolerable when there was one loose `category` field feeding a flat list. It is
not tolerable now that three fields decide which section of the brief a claim appears in,
because an unrecognised value makes a finding silently invisible rather than wrong.

Loading lives here too, because the migration introduced a trap: `gw04_*.jsonl` matches
both `gw04_batch1.jsonl` and its migrated twin `gw04_batch1.v2.jsonl`, and a caller that
globs naively counts every finding twice.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINDINGS_DIR = ROOT / "news" / "findings"
CREATORS_PATH = ROOT / "news" / "creators.json"

TOPICS = {
    "minutes", "injury", "role", "set_piece", "form",
    "fixtures", "price", "captaincy", "chip", "transfer",
}
KINDS = {"news", "read", "stat", "recommendation", "action"}
HORIZONS = {"this_gw", "next_few", "season"}
STANCES = {"positive", "negative", "neutral"}
CONVICTIONS = {"strong", "moderate", "passing"}

VOCABULARY = {
    "topic": TOPICS,
    "kind": KINDS,
    "horizon": HORIZONS,
    "stance": STANCES,
    "conviction": CONVICTIONS,
}


# Midweek football a player has already played, or is about to. The FPL API cannot see
# any of it: `element_summary` holds league rounds only, so a cup 90 is invisible to both
# the minutes model and the claim checker.
#
# This is deliberately NOT a model input. Cup goals score no FPL points, and a fatigue
# adjustment belongs in `minutes.py` only once `train_minutes.py` has fitted and
# walk-forward validated one. Until then it is shown to Joe as evidence beside the
# numbers, in the same spirit as the rest of the expert room: the model says what it can
# measure, and what it structurally cannot see sits next to it rather than inside it.
MIDWEEK = re.compile(
    r"\b(carabao|league cup|fa cup|champions league|europa|conference league|"
    r"european|midweek|cup tie|cup game)\b",
    re.I,
)


def midweek_findings(rows: list[dict]) -> list[dict]:
    """Cup and European claims that bear on whether a player will be fresh and playing."""
    out = []
    for row in rows:
        if row.get("topic") not in {"minutes", "injury", "role"}:
            continue
        text = f"{row.get('claim', '')} {row.get('quote', '')}"
        if MIDWEEK.search(text):
            out.append(row)
    return out


def load_creators() -> dict[str, dict]:
    if not CREATORS_PATH.exists():
        return {}
    with open(CREATORS_PATH) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def muted_sources() -> set[str]:
    """Creators Joe has chosen not to read.

    Muting rather than deleting: `news/entries.jsonl` is append-only because a feed item
    is unrecoverable once it scrolls off the source, and an editorial judgement is not a
    reason to lose the record that a video existed. Un-muting later costs nothing.
    """
    return {slug for slug, row in load_creators().items() if row.get("muted")}


def is_panel(source: str) -> bool:
    """Whether this channel publishes several named analysts under one brand."""
    return bool(load_creators().get(source, {}).get("panel"))


def creator_name(source: str, short: bool = True) -> str:
    """The human name for a feed slug, for use inside a claim sentence.

    Falls back to the slug rather than inventing a name: an unknown channel should read
    as an unknown channel, not as a plausible-looking person.
    """
    row = load_creators().get(source)
    if not row:
        return source
    return row.get("short") or row.get("display") or source


def paths(gw: int) -> list[Path]:
    """Migrated files where they exist, originals where they do not — never both."""
    migrated = sorted(FINDINGS_DIR.glob(f"gw{gw:02d}_*.v2.jsonl"))
    superseded = {path.name.replace(".v2.jsonl", ".jsonl") for path in migrated}
    legacy = [path for path in sorted(FINDINGS_DIR.glob(f"gw{gw:02d}_*.jsonl"))
              if not path.name.endswith(".v2.jsonl") and path.name not in superseded]
    return migrated + legacy


def load(gw: int) -> list[dict]:
    rows = []
    for path in paths(gw):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def validate(rows: list[dict]) -> list[dict]:
    """Every value outside the allowed vocabulary, and every missing required field.

    Reports rather than repairs. A finding with a bad topic is an extraction fault worth
    seeing, and guessing a replacement would hide the very thing worth knowing.
    """
    problems: list[dict] = []
    for i, row in enumerate(rows):
        for field, allowed in VOCABULARY.items():
            value = row.get(field)
            if value is None:
                # `horizon` and `topic` may be genuinely undetermined on migrated rows;
                # the migration records that in `inferred` and it is reported separately.
                if field in {"stance", "conviction", "kind"}:
                    problems.append({"row": i, "field": field, "value": None,
                                     "claim": row.get("claim", "")[:70]})
                continue
            if value not in allowed:
                problems.append({"row": i, "field": field, "value": value,
                                 "claim": row.get("claim", "")[:70]})
        if not row.get("claim"):
            problems.append({"row": i, "field": "claim", "value": None, "claim": ""})
    return problems
