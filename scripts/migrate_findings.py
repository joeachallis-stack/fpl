"""One-off migration of extracted findings from `category` to `topic`/`kind`/`horizon`.

The transcripts are NOT re-read. Reading one is the expensive step and a video is
extracted once, ever, so this works from the claim and quote text that extraction already
produced. Originals are left untouched; migrated rows are written beside them as
`*.v2.jsonl`.

Where the old category already names a topic on the new axis the map is mechanical.
Where it named Joe's relationship to the player instead (`owned_player`, `target`) or
nothing at all (`misc`), the topic is inferred from the text. Every inference is a visible
rule here rather than a model call, so the result is reproducible and auditable.

A row the rules cannot place is written with a null field and counted in the report. A
flagged unknown is a better outcome than a confident wrong label, same as with names.

Usage:
    python scripts/migrate_findings.py --dry-run
    python scripts/migrate_findings.py
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

import findings as findings_schema
import roster

ROOT = Path(__file__).resolve().parent.parent
FINDINGS_DIR = ROOT / "news" / "findings"

# Old categories that already sat on the topic axis.
DIRECT_TOPIC = {
    "minutes_risk": "minutes",
    "set_piece": "set_piece",
    "price": "price",
    "captaincy": "captaincy",
    "chip": "chip",
    "fixtures": "fixtures",
}

# Scored, not first-match. First-match put every "on a wildcard, lock in Calafiori" into
# `chip` when the claim is transfer advice that merely mentions a chip. A hit inside the
# opening clause counts double, because that is where a sentence says what it is about.
LEAD_CHARS = 60
LEAD_WEIGHT = 2

_NUM = r"\b(\d[\d,]*(\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\b"
_COUNTABLE = (r"\b(xg|xa|xgc|npxg|goals?|assists?|shots?|key passes|big chances|"
              r"defensive contributions|defcon|touches|clean sheets?|points?|"
              r"managers|involvements|attempts?|chances)\b")

TOPIC_PATTERNS: dict[str, list[str]] = {
    "injury": [r"\b(injur|hamstring|knock|strain|surgery|sidelined|ruled out|out for)",
               r"\b(suspend|ban(ned)?|red card|three.?match ban)",
               r"\b(fitness|doubt(ful)?|returns? from|back in training)"],
    "set_piece": [r"\b(penalt|spot.?kick|set.?piece|free.?kick|corners?)",
                  r"\b(takes? the (pens?|penalties|free.?kicks|corners))",
                  r"\b(on (pens|penalties)|penalty (duty|taker))"],
    "chip": [r"\b(wildcard|free.?hit|bench.?boost|triple.?captain)",
             r"\b(chip (strategy|timing)|play(ing)? (the|his|my) chip|activate)"],
    "captaincy": [r"\b(captain|armband|vice.?captain|skipper)"],
    "price": [r"\b(price (rise|drop|change|point)|rise to|risen to|drop to|dropped to)",
              r"\b(going to (rise|fall|drop)|about to (rise|fall|drop)|triple rise)",
              r"\b\d+\.\d+m\b"],
    "minutes": [r"\b(nailed|rotat|benched?|hooked|substitut|subbed (off|on)|"
                r"squad competition|game.?time|minutes)",
                r"\b(start(s|ing)? (the|ahead|again|every|the xi)|in the (starting )?xi)",
                r"\b(played \d+ minutes|60 minutes|full 90|came off (the bench|at))",
                r"\b(starting \w+ over|keeps? (his|their) place|leaning towards|"
                r"front line|back line|in (his|my|the) (xi|team|side)|drops? out)"],
    "role": [r"\b(role|plays? (central|deeper|wide|off|as|behind)|moved (central|inside|up))",
             r"\b(used (in|at|as)|played (in|at) (midfield|left|right|centre)|"
             r"centre.?back|in midfield)",
             r"\b(false 9|number 10|left.?sided|right.?back|left.?back|up front|"
             r"further forward|deeper)"],
    "fixtures": [r"\b(fixture|double.?game.?week|blank|schedul|congestion|fixture swing)",
                 r"\b(champions league|europa|midweek|european)",
                 r"\b(run of|away to|at home (in|to)|home against)"],
    "transfer": [r"\b(transfer|bring (him )?in|get him in|ship out|move (him )?on)",
                 r"\b(buy|sell|selling|buying|swap|target|bargain|good value)",
                 r"\b(hold on to|keep(ing)? him|stick with|route to)",
                 r"\b(invest in|would go for|consider(ing)?|rates?|own(s|ing)|"
                 r"as buys|transferred in by)"],
    "form": [r"\b(xg|xa|xgc|npxg|expected (goals|assists)|underlying|threat|shots)",
             r"\b(form|performance|played well|poor|impressive|looked)",
             r"\b(key passes|big chances|touches|defensive contributions|defcon)"],
}

# Only consulted when two topics score equally.
TOPIC_PRIORITY = ["injury", "set_piece", "captaincy", "chip", "minutes", "price",
                  "role", "fixtures", "transfer", "form"]

KIND_PATTERNS: dict[str, list[str]] = {
    # Later batches paraphrase the speaker as "the creator" rather than by name, which
    # left every one of their own-team statements falling through to `stat` on a stray
    # number ("99% likely to Wildcard", "his nine-point return").
    "action": [r"\b(raptor|harry|the creator)('s|s)? (has|is|was|will|would|owns?|bought|"
               r"sold|plans?|expects?|wants?|intends?|plays?|plan|rolled|judged|"
               r"triple.?captained|captained|started|benched|considered)",
               r"\bthe creator('s)?\b",
               r"\bhe (rolled|judged|wants|expects|plans|bought|sold|started|benched|"
               r"triple.?captained|captained)\b",
               r"\b(his|their) (draft|team|squad|wildcard|xi|bench|transfers?)",
               r"\b(the draft|i'?ve|i have|i'?m|i am|i'?ll|i will|i'?d go|my (team|squad))",
               r"\b(is (about )?\d+% sure|most tempting (move|double))"],
    "news": [r"\b(rumour|reportedly|confirmed|announced|press conference|manager said)",
             r"\b(went off|came off (injured|holding)|signed|signing|deadline day)",
             r"\b(is out|will miss|expected to (return|be fit)|team news|doubt for)",
             r"\b(injur|suspend|hamstring|red card)"],
    # A number and a countable within a few words of each other, in either order:
    # "32 defensive contributions" and "defensive contributions with 32" are both stats,
    # and requiring adjacency missed most of the corpus.
    "stat": [_NUM + r"[\s\w]{0,24}?" + _COUNTABLE,
             _COUNTABLE + r"[\s\w]{0,24}?" + _NUM,
             r"\(\d+(\.\d+)?\)",
             r"\b\d+(\.\d+)?%",
             r"\b(leads?|tops?|standout|best|worst) .{0,32}?(for|in) the",
             r"\b(first|second|third|top|\d+(st|nd|rd|th)) (in|for) ",
             r"\bper (game|90)\b|\braw numbers\b|\brank(ed|s)? \d+"],
    "recommendation": [r"\b(should|you (can|could|want|need|would)|worth (a|the|buying|it))",
                       r"\b(i'?d (go|buy|sell|keep|avoid)|would (favour|prefer|go for|"
                       r"consider|rather)|must|avoid)",
                       r"\b(don'?t (buy|bother|touch)|lock(ed)? in|no reason to|"
                       r"the best|an absolute bargain|get behind)",
                       r"\b(prefers?|rather than|doesn'?t (think|love|rate)|questions whether|"
                       r"offers? enough|not this gameweek|is fine but|as buys)"],
    "read": [r"\b(looked|looks|seems|felt|impressive|fantastic|awful|terrible|appalling)",
             r"\b(poor|lost|sharp|bright|constantly made|eye test|by eye)",
             r"\b(doesn'?t (look|seem)|not convinced|unconvincing|uninspiring)"],
}

# `read` absorbs the residue: a creator paraphrase with no external fact, no number and
# no advisory modal is that creator's own judgment. The fallback is recorded in
# `inferred` rather than hidden, so its share stays measurable.
KIND_PRIORITY = ["action", "news", "stat", "recommendation", "read"]
KIND_DEFAULT = "read"

HORIZON_SEASON = re.compile(
    r"\b(season|long.?term|later in the|second half|rest of the (season|year))\b", re.I)
HORIZON_THIS = re.compile(
    r"\b(this (week|gameweek|gw)|right now|tonight|before the deadline|this weekend)\b",
    re.I)
HORIZON_NEXT = re.compile(
    r"\b(next few|coming (weeks|gameweeks|fixtures)|run of|over the next|"
    r"in a few (weeks|gameweeks))\b", re.I)

# When nothing in the text dates the claim, the topic does. A minutes or injury claim is
# about the imminent team sheet; a transfer or fixture claim is about a run of weeks.
HORIZON_BY_TOPIC = {
    "minutes": "this_gw", "injury": "this_gw", "captaincy": "this_gw",
    "price": "this_gw", "set_piece": "next_few", "role": "next_few",
    "form": "next_few", "transfer": "next_few", "fixtures": "next_few",
    "chip": "season",
}


def score(patterns: dict[str, list[str]], text: str) -> dict[str, int]:
    """Count pattern hits per label, double-weighting the opening clause."""
    lead = text[:LEAD_CHARS]
    scores: dict[str, int] = {}
    for label, group in patterns.items():
        total = 0
        for pattern in group:
            if re.search(pattern, text, re.I):
                total += LEAD_WEIGHT if re.search(pattern, lead, re.I) else 1
        if total:
            scores[label] = total
    return scores


def best(patterns: dict[str, list[str]], priority: list[str], text: str) -> str | None:
    scores = score(patterns, text)
    if not scores:
        return None
    top = max(scores.values())
    tied = [label for label, n in scores.items() if n == top]
    return min(tied, key=priority.index)


def text_of(row: dict) -> str:
    return f"{row.get('claim', '')} {row.get('quote', '')}".lower()


def first_match(rules: list[tuple[str, str]], text: str) -> str | None:
    for label, pattern in rules:
        if re.search(pattern, text, re.I):
            return label
    return None


def infer_topic(row: dict, text: str) -> str | None:
    direct = DIRECT_TOPIC.get(row.get("category"))
    if direct:
        return direct
    return best(TOPIC_PATTERNS, TOPIC_PRIORITY, text)


def infer_kind(row: dict, text: str) -> tuple[str, bool]:
    """Returns the kind and whether it came from the fallback rather than a rule."""
    if row.get("category") == "creator_action":
        return "action", False
    found = best(KIND_PATTERNS, KIND_PRIORITY, text)
    return (found, False) if found else (KIND_DEFAULT, True)


def infer_horizon(topic: str | None, text: str, target_gw: int) -> tuple[str | None, bool]:
    # An explicit future gameweek number beats every keyword: "Haaland vs Ipswich GW7"
    # is a season-horizon claim however presently it is phrased.
    ahead = [n for n in (int(m) for m in re.findall(r"\bgw\s*(\d{1,2})\b", text, re.I))
             if n > target_gw]
    if ahead:
        return ("season" if max(ahead) - target_gw >= 4 else "next_few"), False
    if HORIZON_THIS.search(text):
        return "this_gw", False
    if HORIZON_SEASON.search(text):
        return "season", False
    if HORIZON_NEXT.search(text):
        return "next_few", False
    return HORIZON_BY_TOPIC.get(topic) if topic else None, True


def team_index() -> dict[str, str]:
    """Folded team name and short name -> canonical team name."""
    with open(ROOT / "data" / "bootstrap.json") as f:
        teams = json.load(f)["teams"]
    index: dict[str, str] = {}
    for team in teams:
        index[roster.fold(team["name"])] = team["name"]
        index[roster.fold(team["short_name"])] = team["name"]
    return index


def find_teams(text: str, index: dict[str, str]) -> list[str]:
    folded = roster.fold(text)
    found = {name for key, name in index.items()
             if len(key) > 3 and re.search(rf"\b{re.escape(key)}\b", folded)}
    return sorted(found)


# A claim that says "the creator" cannot be read back as a consensus: the whole point of
# lining claims up is seeing who agrees with whom, and an anonymous speaker breaks that.
# The row already carries its own `source`, so this is a substitution, not a guess — and
# it is done per row rather than per file, because most batches are mixed-source.
# Singular only. "Creators see higher upside in City assets" is the speaker reporting what
# the community thinks, not referring to himself, and rewriting it to his own name would
# invent a claim he did not make.
_ANONYMOUS = re.compile(r"\b(?:the creator|creator)(\u2019s|'s)?\b", re.I)


def name_the_speaker(text: str, source: str) -> str:
    name = findings_schema.creator_name(source)
    if name == source:
        return text
    return _ANONYMOUS.sub(lambda m: f"{name}'s" if m.group(1) else name, text)


def migrate_row(row: dict, target_gw: int, teams: dict[str, str]) -> dict:
    text = text_of(row)
    topic = infer_topic(row, text)
    kind, kind_default = infer_kind(row, text)
    horizon, horizon_default = infer_horizon(topic, text, target_gw)
    inferred = [name for name, used in
                (("kind", kind_default), ("horizon", horizon_default)) if used]
    return {
        "video_id": row.get("video_id"),
        "source": row.get("source"),
        "published": row.get("published"),
        "players": row.get("players", []),
        "teams": find_teams(f"{row.get('claim', '')} {row.get('quote', '')}", teams),
        "unresolved": row.get("unresolved", []),
        "topic": topic,
        "kind": kind,
        "horizon": horizon,
        "stance": row.get("stance"),
        "conviction": row.get("conviction"),
        # The claim is a paraphrase and may be rewritten; the quote is verbatim
        # evidence and is never touched.
        "claim": name_the_speaker(row.get("claim") or "", row.get("source") or ""),
        "quote": row.get("quote"),
        "migrated_from": row.get("category"),
        "inferred": inferred,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    teams = team_index()
    stats: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    unplaced: list[dict] = []
    total = 0

    for path in sorted(FINDINGS_DIR.glob("gw*_batch*.jsonl")):
        if path.name.endswith(".v2.jsonl"):
            continue
        target_gw = int(path.name[2:4])
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        migrated = [migrate_row(row, target_gw, teams) for row in rows]
        total += len(migrated)
        for row in migrated:
            stats["topic"][row["topic"]] += 1
            stats["kind"][row["kind"]] += 1
            stats["horizon"][row["horizon"]] += 1
            for field in row["inferred"]:
                stats["fallback"][field] += 1
            if row["topic"] is None:
                unplaced.append(row)
        if not args.dry_run:
            out = path.with_suffix(".v2.jsonl")
            out.write_text("".join(json.dumps(r) + "\n" for r in migrated))

    print(f"{total} findings migrated"
          f"{' (dry run, nothing written)' if args.dry_run else ''}\n")
    for field in ("topic", "kind", "horizon"):
        print(f"{field}:")
        for label, n in stats[field].most_common():
            print(f"   {str(label):16} {n:4}  {100 * n / total:4.1f}%")
        print()

    print("fallback used (no rule matched, default applied):")
    for field, n in stats["fallback"].most_common():
        print(f"   {field:16} {n:4}  {100 * n / total:4.1f}%")

    if unplaced:
        print(f"\n{len(unplaced)} rows with no topic — inspect before trusting:")
        for row in unplaced[:12]:
            print(f"   {row['claim'][:96]}")


if __name__ == "__main__":
    main()
