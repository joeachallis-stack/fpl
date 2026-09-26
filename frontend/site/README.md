# Public site prototype

This is the first build against `docs/PUBLIC_SITE_SPEC.md`. It is separate from the running private Decision Room. `P⋆ITCH` is a temporary working name.

From the repository root, use two terminal sessions:

```bash
python3 scripts/public_site_server.py
cd frontend && npm run site:dev
```

Open `http://127.0.0.1:5174` on the Studio. The API listens on `127.0.0.1:8766`. Both are local only. The browser can enter any valid public FPL team ID or team URL. The backend reads the official FPL API and the Studio's current all-player projection artifact; it writes no visitor data to the repo and changes no FPL account. A plan draft stays in that browser's local storage.

Current slice: team lookup, settled season history, last public squad, honest loading, evidence-backed story cards, a shared gameweek rail, current-week view, captain forecast ranking, six-week player shopping, and draft swaps. The transfer story compares one recent settled transfer for one gameweek. It labels whether a frozen pre-deadline forecast exists and excludes any transfer hit.

Next build: generalize the decision engine to arbitrary teams, reconstruct selling prices and transfer legality, compare plans across the full horizon including hits and chips, and deepen Season in Review. The planning board currently shows projected XI points before transfer hits and budget checks. It is a read-only idea board.

To build the public site without touching the private frontend build:

```bash
cd frontend && npm run site:build
```
