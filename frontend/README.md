# FPL Decision Room frontend

Desktop-only local interface for the FPL repository. React renders a single sanitized
view model from `scripts/frontend_data.py`; model calculations remain in Python.

On macOS, double-click `Open FPL Decision Room.command` at the repository root for the
one-click local launcher. Closing its Terminal window stops the loopback server.

## Run the built app

```bash
cd frontend
npm install
npm run build
cd ..
python scripts/frontend_server.py
```

Open `http://127.0.0.1:8765`. The server binds only to loopback and serves a fixed API:
the coherent analysis view model, refresh, rebuild, and reviewed journal append. It cannot
write to the FPL account or overwrite immutable archives.

For development, run `python scripts/frontend_server.py` in one terminal and `npm run dev`
inside `frontend/` in another, then open `http://127.0.0.1:5173`.

## Verify

```bash
python -m pytest -q
cd frontend
npm test
npm run build
```

`scripts/horizon_compare.py` creates an independent two-week optimizer search from an
explicit first-two-week view of the canonical six-week projections, then cross-scores the
union of the two- and six-week candidate sets. It writes only the gitignored comparison
artifact. The adapter accepts that artifact only while its projection and decision hashes
still match the canonical caches; otherwise it automatically restores the honest
“same candidate set” fallback.
