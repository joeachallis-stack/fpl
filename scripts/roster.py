"""Canonical player-name resolution against bootstrap.json.

The point of this module is that **an LLM is never the authority on a fact FPL already
publishes.** Auto-generated captions mangle names ("Gabrielle" for Gabriel, "Sessi
Muno's" for a run of names), and a model asked to tidy that up will reach for players it
remembers rather than players in the game — it produced "Kyle Walker of Arsenal" and
"Estupiñán of Brighton" on the first real test, neither of whom exist in 2026/27. It also
copied "Mac Allister of Brighton" straight from a caption when the roster says Liverpool.

So extraction names a player and states a claim; team, position and price are attached
here, from the roster. Two layers, because either alone leaks:

    roster_names()  the vocabulary an extractor is allowed to use
    resolve()       validation of whatever it actually returned

Matching has to be looser than string equality — the first version of this check missed
Konsa (stored second_name is "Konsa Ngoyo") and Groß (NFD normalisation leaves ß alone,
so "gross" never matched). Both were reported as hallucinations when they were real.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Folded before comparison. ß is the one that bit: unicodedata's NFD decomposition
# handles é -> e but leaves ß untouched, because it isn't an accented letter.
_FOLD = {"ß": "ss", "ø": "o", "đ": "d", "ł": "l", "æ": "ae", "œ": "oe", "'": "", "-": " "}


def fold(s: str) -> str:
    s = s.lower()
    for k, v in _FOLD.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def load_players() -> list[dict]:
    with open(DATA_DIR / "bootstrap.json") as f:
        bootstrap = json.load(f)
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    positions = {t["id"]: t["singular_name_short"] for t in bootstrap["element_types"]}
    return [
        {
            "element": e["id"],
            "web_name": e["web_name"],
            "full_name": f"{e['first_name']} {e['second_name']}".strip(),
            "team": teams[e["team"]],
            "position": positions[e["element_type"]],
            "now_cost": e["now_cost"] / 10,
            "status": e["status"],
        }
        for e in bootstrap["elements"]
    ]


def build_index(players: list[dict]) -> dict[str, list[dict]]:
    """Every name form a caption might plausibly use, folded, pointing at candidates.

    Deliberately generous: a surname alone is included, because that is what commentary
    actually says. Generosity means collisions (two Sangarés), which resolve() reports
    rather than silently picking one.
    """
    index: dict[str, list[dict]] = {}
    for p in players:
        forms = {p["web_name"], p["full_name"]}
        parts = p["full_name"].split()
        if parts:
            forms.add(parts[-1])            # surname
            forms.add(" ".join(parts[-2:]))  # compound surname, e.g. "Mac Allister"
        if len(parts) > 1:
            forms.add(f"{parts[0]} {parts[-1]}")  # first + last, skipping middle names
            # First name + display name. Konsa's stored second_name is "Konsa Ngoyo", so
            # "Ezri Konsa" — what anyone actually says — matches no other form.
            forms.add(f"{parts[0]} {p['web_name']}")
        for form in forms:
            key = fold(form)
            if key:
                index.setdefault(key, []).append(p)
    return index


def resolve(name: str, index: dict[str, list[dict]], team_hint: str | None = None) -> dict:
    """Resolve one extracted name. Never guesses past an ambiguity.

    Returns {"status": "ok"|"ambiguous"|"unknown", "player": ..., "candidates": [...]}.
    A caller storing a finding should treat anything but "ok" as unresolved and keep the
    raw text, rather than dropping the finding or picking a candidate.
    """
    hits = index.get(fold(name), [])
    if not hits:
        return {"status": "unknown", "player": None, "candidates": [], "raw": name}
    if len(hits) > 1 and team_hint:
        narrowed = [h for h in hits if fold(h["team"]) == fold(team_hint)]
        if len(narrowed) == 1:
            return {"status": "ok", "player": narrowed[0], "candidates": [], "raw": name}
    if len(hits) > 1:
        return {"status": "ambiguous", "player": None, "candidates": hits, "raw": name}
    out = {"status": "ok", "player": hits[0], "candidates": [], "raw": name}
    # A hint that disagrees with the roster means the transcript said something false —
    # the roster still wins, but the disagreement is worth surfacing rather than
    # swallowing. This is the "Mac Allister of Brighton" case.
    if team_hint and fold(hits[0]["team"]) != fold(team_hint):
        out["team_hint_mismatch"] = {"claimed": team_hint, "actual": hits[0]["team"]}
    return out


def roster_names(players: list[dict]) -> list[str]:
    """The vocabulary an extractor is allowed to emit — 'Web Name (Team, POS)' per line."""
    return [f"{p['web_name']} ({p['team']}, {p['position']})" for p in players]


if __name__ == "__main__":
    players = load_players()
    index = build_index(players)
    print(f"{len(players)} players, {len(index)} name forms indexed\n")
    # The exact cases that broke the first version of this check, plus the real errors.
    for name, hint in [("Ezri Konsa", None), ("Konsa", None), ("Gross", None), ("Groß", None),
                       ("Mac Allister", "Brighton"), ("Mac Allister", None),
                       ("Kyle Walker", None), ("Estupinan", None), ("Sangare", None),
                       ("Sangare", "Nott'm Forest"), ("Gabrielle", None), ("Joao Pedro", None)]:
        r = resolve(name, index, hint)
        p = r["player"]
        detail = (f"{p['web_name']} ({p['team']}, {p['position']})" if p
                  else f"{len(r['candidates'])} candidates" if r["candidates"] else "-")
        print(f"  {name:<16} hint={str(hint):<16} {r['status']:<10} {detail}")
