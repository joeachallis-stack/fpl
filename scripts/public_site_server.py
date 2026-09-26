"""Local-only API for the public-site prototype. Run with python3 scripts/public_site_server.py."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import public_site_data


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "public"] or parts[2] != "team" or not parts[3].isdigit():
            self.send_json(404, {"error": "Unknown route"})
            return
        entry_id = int(parts[3])
        if not 1 <= entry_id <= 999_999_999:
            self.send_json(400, {"error": "Enter a valid FPL team ID."})
            return
        try:
            result = public_site_data.identity(entry_id) if urlparse(self.path).query == "identity" else public_site_data.analysis(entry_id)
            self.send_json(200, result)
        except HTTPError as exc:
            self.send_json(404 if exc.code == 404 else 503, {"error": "We could not find that FPL team." if exc.code == 404 else "FPL data is temporarily unavailable. Please try again."})
        except (URLError, TimeoutError, ValueError, KeyError, OSError, json.JSONDecodeError):
            self.send_json(503, {"error": "FPL data is temporarily unavailable. Please try again."})

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Public site prototype API: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
