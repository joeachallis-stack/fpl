"""Loopback-only web server for the FPL decision room.

Development:
    python scripts/frontend_server.py
    cd frontend && npm run dev

Production-like local build:
    cd frontend && npm run build
    python scripts/frontend_server.py
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import frontend_data

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"


class DecisionRoomHandler(BaseHTTPRequestHandler):
    server_version = "FPLDecisionRoom/1"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 100_000:
            raise ValueError("Request body is too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/analysis":
            try:
                self._send_json(200, frontend_data.build_analysis())
            except frontend_data.AnalysisInputError as exc:
                self._send_json(409, {"error": str(exc), "recovery": "Refresh data, then rebuild comparisons."})
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://127.0.0.1:5173", "http://127.0.0.1:8765"}:
            self._send_json(403, {"error": "This local action rejected an untrusted browser origin."})
            return
        path = urlparse(self.path).path
        if path == "/api/actions/refresh":
            self._run_action([sys.executable, "scripts/fetch_data.py"])
            return
        if path == "/api/actions/rebuild":
            self._run_action(
                [sys.executable, "scripts/projections.py"],
                [sys.executable, "scripts/decisions.py"],
            )
            return
        if path == "/api/actions/journal":
            try:
                body = self._body()
                self._journal(body)
            except (ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
                self._send_json(400, {"error": str(exc)})
            return
        self._send_json(404, {"error": "Unknown action"})

    def _run_action(self, *commands: list[str]) -> None:
        outputs = []
        try:
            for command in commands:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=180,
                    check=True,
                )
                outputs.append(completed.stdout.strip())
            self._send_json(200, {"ok": True, "output": "\n".join(outputs), "analysis": frontend_data.build_analysis()})
        except subprocess.TimeoutExpired:
            self._send_json(504, {"error": "The local action exceeded three minutes; the previous analysis remains valid."})
        except subprocess.CalledProcessError as exc:
            self._send_json(
                500,
                {"error": (exc.stderr or exc.stdout or "Local action failed").strip(), "previousAnalysisPreserved": True},
            )
        except frontend_data.AnalysisInputError as exc:
            self._send_json(
                409,
                {
                    "error": str(exc),
                    "recovery": "The refresh succeeded, but comparisons now need a coherent rebuild.",
                    "previousAnalysisPreserved": True,
                },
            )

    def _journal(self, body: dict) -> None:
        allowed_categories = {"captain", "transfer", "chip", "hold", "other"}
        allowed_confidence = {"low", "medium", "high"}
        required = ("gw", "category", "recommendation", "reasoning", "runnerUp")
        missing = [field for field in required if not body.get(field)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        if body["category"] not in allowed_categories or body.get("confidence", "medium") not in allowed_confidence:
            raise ValueError("Invalid journal category or confidence")
        command = [
            sys.executable,
            "scripts/journal.py",
            "add",
            "--gw",
            str(int(body["gw"])),
            "--category",
            body["category"],
            "--recommendation",
            str(body["recommendation"])[:500],
            "--reasoning",
            str(body["reasoning"])[:2000],
            "--confidence",
            body.get("confidence", "medium"),
            "--runner-up",
            str(body["runnerUp"])[:500],
        ]
        if body.get("caseAgainst"):
            command.extend(["--case-against", str(body["caseAgainst"])[:1000]])
        if body.get("runnerUpDelta") is not None:
            command.extend(["--runner-up-delta", str(float(body["runnerUpDelta"]))])
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10, check=True)
        self._send_json(200, {"ok": True, "output": completed.stdout.strip(), "analysis": frontend_data.build_analysis()})

    def _serve_static(self, request_path: str) -> None:
        if not DIST.exists():
            self._send_json(404, {"error": "Frontend is not built. Run cd frontend && npm run dev."})
            return
        requested = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        candidate = (DIST / requested).resolve()
        if DIST.resolve() not in candidate.parents and candidate != DIST.resolve():
            self._send_json(403, {"error": "Invalid path"})
            return
        if not candidate.is_file():
            candidate = DIST / "index.html"
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DecisionRoomHandler)
    print(f"FPL Decision Room: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
