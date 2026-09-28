#!/usr/bin/env python3
"""Small in-memory leaderboard for the Snake arcade."""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

FLAG = os.environ["FLAG"]
IMPOSSIBLE_SCORE = 1_000_000
BOARDS = {}
ROOT = Path(__file__).parent


class Handler(BaseHTTPRequestHandler):
    def player(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "player" and value.isalnum() and len(value) == 32:
                return value
        return secrets.token_hex(16)

    def board(self, player):
        return BOARDS.setdefault(player, [
            {"name": "Bloody Toothed Sam", "score": IMPOSSIBLE_SCORE},
            {"name": "Tommy Knockers", "score": 2500},
            {"name": "Flora Stanley", "score": 1500},
        ])

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
            self.send_json(200, {"scores": self.board(player)[:3]}, player)
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
        if urlparse(self.path).path != "/api/score":
            self.send_error(404)
            return
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            score = data["score"]
            if type(score) is not int or score < 0:
                raise ValueError("score must be a non-negative integer")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.send_json(400, {"error": "score must be a non-negative integer"})
            return

        player = self.player()
        board = self.board(player)
        board.append({"name": "You", "score": score})
        board.sort(key=lambda entry: entry["score"], reverse=True)
        del board[3:]
        first = board[0]["name"] == "You" and board[0]["score"] == score
        self.send_json(200, {"scores": board, "flag": FLAG if first and score > IMPOSSIBLE_SCORE else None}, player)

    def log_message(self, fmt, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
