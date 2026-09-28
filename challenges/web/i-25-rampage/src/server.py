#!/usr/bin/env python3
"""Small in-memory event leaderboard for I-25 Rampage."""
import hashlib
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

FLAG = os.environ["FLAG"]
PICKUP_POINTS = {"fuel": 10, "bonus": 25}
# Deliberately shared with the browser for this challenge, not a real secret.
SIGNING_KEY = b"i25-road-crew-dispatch-2026"
# The game can spawn at most one pickup every five seconds. At 25 points
# each time, 72 hours of perfect play is 1,296,000 points.
IMPOSSIBLE_SCORE = 72 * 60 * 60 // 5 * max(PICKUP_POINTS.values())
MAX_PICKUPS = 1_000_000
BOARDS = {}
BOARDS_LOCK = threading.Lock()
ROOT = Path(__file__).parent


class Handler(BaseHTTPRequestHandler):
    def player(self):
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == "player" and value.isalnum() and len(value) == 32:
                return value
        return secrets.token_hex(16)

    def board(self, player):
        return BOARDS.setdefault(player, [{"name": "The Long Haul", "score": IMPOSSIBLE_SCORE}])

    def send_json(self, status, value, player=None):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if player:
            self.send_header("Set-Cookie", f"player={player}; Path=/; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/leaderboard":
            player = self.player()
            with BOARDS_LOCK:
                scores = self.board(player)[:3]
            self.send_json(200, {"scores": scores}, player)
            return
        if path == "/" or path == "/index.html":
            body = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/theme/"):
            file = (ROOT / path.lstrip("/")).resolve()
            if file.is_relative_to((ROOT / "theme").resolve()) and file.is_file():
                body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/css" if file.suffix == ".css" else "image/svg+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/crash":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError
            body = self.rfile.read(length)
            signature = self.headers.get("X-Run-Signature", "")
            expected = hmac.new(SIGNING_KEY, body, hashlib.sha256).hexdigest()
            if len(signature) != 64 or any(c not in "0123456789abcdef" for c in signature) or not hmac.compare_digest(signature, expected):
                self.send_json(403, {"error": "invalid run signature"})
                return
            data = json.loads(body)
            pickups = data["pickups"]
            if not isinstance(pickups, dict) or not pickups or set(pickups) - PICKUP_POINTS.keys():
                raise ValueError
            if any(type(count) is not int or count < 0 or count > MAX_PICKUPS for count in pickups.values()):
                raise ValueError
            if sum(pickups.values()) > MAX_PICKUPS:
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.send_json(400, {"error": "send pickup counts for known item types"})
            return

        score = sum(PICKUP_POINTS[kind] * count for kind, count in pickups.items())
        player = self.player()
        with BOARDS_LOCK:
            board = self.board(player)
            board.append({"name": "You", "score": score})
            board.sort(key=lambda entry: entry["score"], reverse=True)
            del board[3:]
            first = board[0]["name"] == "You" and board[0]["score"] == score
            scores = board[:]
        self.send_json(200, {
            "score": score,
            "scores": scores,
            "flag": FLAG if first and score > IMPOSSIBLE_SCORE else None,
        }, player)

    def log_message(self, fmt, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
