"""Serve the design review and save feedback locally, without cloud services.

Run .venv/bin/python scripts/design_review.py (loopback port 8080).
Only designs/ is served; the repository root and its .env are never exposed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 128 * 1024
SLUG = re.compile(r"[a-zA-Z0-9_-]{1,80}\Z")


def revision(document: object) -> str:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return '"' + hashlib.sha256(encoded).hexdigest() + '"'


def validate_document(value: object) -> dict:
    """Keep a bounded, explicit feedback document; never accept file paths."""
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Expected review document version 1")
    timestamp = value.get("updatedAt")
    if not isinstance(timestamp, str) or len(timestamp) > 40:
        raise ValueError("Missing update time")
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        raise ValueError("Update time requires a timezone")
    current = value.get("currentId", "")
    if not isinstance(current, str) or (current and not SLUG.fullmatch(current)):
        raise ValueError("Invalid scenario")
    theme = value.get("theme", "light")
    if theme not in ("light", "dark"):
        raise ValueError("Invalid theme")
    general = value.get("generalNote", "")
    if not isinstance(general, str) or len(general) > 10000:
        raise ValueError("General feedback is too long")
    decisions = value.get("decisions", {})
    if not isinstance(decisions, dict) or len(decisions) > 100:
        raise ValueError("Invalid decisions")
    clean = {}
    for key, decision in decisions.items():
        if (
            not isinstance(key, str)
            or not SLUG.fullmatch(key)
            or not isinstance(decision, dict)
        ):
            raise ValueError("Invalid decision")
        option, status, note = (decision.get(k) for k in ("option", "status", "note"))
        if option is not None and (
            not isinstance(option, str) or not SLUG.fullmatch(option)
        ):
            raise ValueError("Invalid option")
        if status not in ("pending", "approved", "rejected", "changes"):
            raise ValueError("Invalid decision status")
        if not isinstance(note, str) or len(note) > 5000:
            raise ValueError("Scenario feedback is too long")
        clean[key] = {"option": option, "status": status, "note": note}
    return {
        "version": 1,
        "updatedAt": timestamp,
        "currentId": current,
        "theme": theme,
        "generalNote": general,
        "decisions": clean,
    }


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], directory: Path, feedback: Path):
        self.directory = directory.resolve()
        self.feedback = feedback
        self.feedback_lock = threading.Lock()
        super().__init__(address, ReviewHandler)


class ReviewHandler(SimpleHTTPRequestHandler):
    server: ReviewServer

    def __init__(self, request, client_address, server: ReviewServer):
        super().__init__(
            request, client_address, server, directory=str(server.directory)
        )

    def allowed(self) -> bool:
        host = self.headers.get("Host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid_host = (
                parsed.hostname in ("127.0.0.1", "localhost")
                and parsed.username is None
                and parsed.password is None
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and (parsed.port is None or 0 < parsed.port < 65536)
            )
        except ValueError:
            valid_host = False
        if not valid_host:
            self.send_error(HTTPStatus.FORBIDDEN, "Local access only")
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{host}":
            self.send_error(
                HTTPStatus.FORBIDDEN, "Cross-origin requests are not allowed"
            )
            return False
        return True

    def json_response(
        self, status: int, document: object, etag: str | None = None
    ) -> None:
        data = json.dumps(document, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if etag is not None:
            self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(data)

    def read_feedback(self):
        try:
            return validate_document(json.loads(self.server.feedback.read_text()))
        except FileNotFoundError:
            return None

    def do_GET(self):
        if not self.allowed():
            return
        if urlsplit(self.path).path == "/api/review":
            try:
                with self.server.feedback_lock:
                    document = self.read_feedback()
                self.json_response(HTTPStatus.OK, document, revision(document))
            except (OSError, ValueError):
                self.json_response(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "Could not read saved feedback"},
                )
            return
        super().do_GET()

    def do_HEAD(self):
        if self.allowed():
            super().do_HEAD()

    def do_PUT(self):
        if not self.allowed():
            return
        if urlsplit(self.path).path != "/api/review":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get_content_type() != "application/json":
            self.json_response(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Expected JSON"}
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self.json_response(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"error": "Feedback exceeds size limit"},
                )
                return
            document = validate_document(json.loads(self.rfile.read(length)))
        except (ValueError, UnicodeError):
            self.json_response(
                HTTPStatus.BAD_REQUEST, {"error": "Invalid feedback document"}
            )
            return
        try:
            with self.server.feedback_lock:
                current = self.read_feedback()
                expected = self.headers.get("If-Match")
                if expected is None:
                    self.json_response(
                        HTTPStatus.PRECONDITION_REQUIRED,
                        {"error": "Load the saved review before writing"},
                    )
                    return
                if expected != revision(current):
                    self.json_response(
                        HTTPStatus.CONFLICT,
                        {
                            "error": "Feedback changed in another session",
                            "review": current,
                        },
                        revision(current),
                    )
                    return
                directory = self.server.feedback.parent
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                fd, filename = tempfile.mkstemp(prefix=".review-", dir=directory)
                try:
                    with os.fdopen(fd, "w") as stream:
                        json.dump(document, stream, ensure_ascii=False, indent=2)
                        stream.write("\n")
                    os.replace(filename, self.server.feedback)
                finally:
                    Path(filename).unlink(missing_ok=True)
            self.json_response(HTTPStatus.OK, document, revision(document))
        except (OSError, ValueError):
            self.json_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Could not save feedback on MSI"},
            )

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path)).resolve()
        if not translated.is_relative_to(self.server.directory):
            return str(self.server.directory / ".not-found")
        return str(translated)

    def list_directory(self, path: str):
        self.send_error(HTTPStatus.NOT_FOUND)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ReviewServer(
        ("127.0.0.1", args.port), ROOT / "designs", ROOT / ".local/design-review.json"
    )
    print(f"Design review: http://127.0.0.1:{args.port}/", flush=True)
    print(f"Feedback: {server.feedback}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
