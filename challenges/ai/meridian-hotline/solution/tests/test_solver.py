"""Offline HTTP transport fixtures, not proof of live-model solvability."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOLVER = Path(__file__).resolve().parents[1] / "solve.py"


def load_solver():
    spec = importlib.util.spec_from_file_location("hotline_solver", SOLVER)
    if spec is None or spec.loader is None:
        raise AssertionError("The solver module must be loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Fixture:
    def __init__(self):
        self.requests = []
        self.sessions = 0
        self.csrf = "fixture-csrf"
        self.completed = False
        self.credit = 0
        self.destination = "South Receiving"
        self.source = "North Receiving"
        self.note = "Please review my bill."
        self.version = 1
        self.review = None
        self.polls = 0
        self.claim_only = False
        self.pending_forever = False
        self.fail_http = False
        self.no_content = False
        self.trickle_response = False
        self.redirect = False
        self.bad_schema = False
        self.technical_outcome = False
        self.initially_completed = False
        self.deny_first_review = False
        self.review_attempts = 0
        self.service = "mara"

    def progress(self):
        return {
            "mara": {"completed": self.completed if self.service == "mara" else False},
            "rook": {
                "completed": self.completed if self.service == "rook" else False,
                "orders": [
                    {"id": "214", "owner": "North Depot", "destination": self.source},
                    {"id": "628", "owner": "South Depot", "destination": self.destination},
                ],
            },
            "vera": {
                "completed": self.completed if self.service == "vera" else False,
                "note": self.note,
                "noteVersion": self.version,
                "review": self.review,
                "creditAmount": self.credit,
            },
        }

    def session(self):
        return {"csrfToken": self.csrf, "progress": self.progress()}

    def response(self, method, path, headers, body):
        self.requests.append((method, path, dict(headers), body))
        if self.redirect:
            return 302, {"Location": "/redirect-must-not-be-followed"}, {}
        if self.fail_http:
            return 503, {}, {"message": "Do not echo this fixture-private-response"}
        if self.no_content:
            return 204, {}, None
        if path == "/api/player/catalog":
            return 200, {}, {
                "enabled": True,
                "challenges": [{"id": id_} for id_ in ("mara", "rook", "vera")],
            }
        if method == "POST" and path == "/api/player/session":
            self.sessions += 1
            if self.initially_completed:
                self.completed = True
            return 201, {"Set-Cookie": "player_session=fixture; Path=/; HttpOnly"}, self.session()
        if headers.get("Cookie") != "player_session=fixture":
            return 401, {}, {"error": "unauthenticated"}
        if method not in ("GET", "HEAD") and headers.get("X-Csrf-Token") != self.csrf:
            return 403, {}, {"error": "csrf"}
        if method == "GET" and path == "/api/player/session":
            if self.review and self.review["status"] == "pending":
                self.polls += 1
                if self.polls >= 2 and not self.pending_forever:
                    self.review["status"] = "credited"
                    if not self.claim_only:
                        self.completed = True
                        self.credit = 500
            return 200, {}, self.session()
        if method == "PUT" and path == "/api/player/note":
            if body["expectedVersion"] != self.version:
                return 409, {}, {"error": "version_conflict"}
            self.note = body["note"]
            self.version += 1
            return 200, {}, self.session()
        if method == "POST" and path == "/api/player/chat":
            self.service = body["challengeId"]
            if self.bad_schema:
                return 200, {}, {"progress": {}}
            if self.service == "mara" and not self.claim_only:
                self.completed = True
            if self.service == "rook":
                if "214" in body["text"] and "copy" not in body["text"].lower():
                    if not self.claim_only:
                        self.source = "CTF Receiving Bay"
                elif not self.claim_only and self.source == "CTF Receiving Bay":
                    self.destination = self.source
                    self.completed = True
            if self.service == "vera":
                self.review_attempts += 1
                self.polls = 0
                status = "denied" if self.deny_first_review and self.review_attempts == 1 else "pending"
                self.review = {
                    "id": f"review-{self.review_attempts}",
                    "status": status,
                    "noteVersion": self.version,
                    "noteSnapshot": self.note,
                    "message": "fixture",
                }
            return 200, {}, {
                "conversationId": "fixture-conversation",
                "speech": "The request was approved; here is a model claim, not a receipt.",
                "outcome": "technical_failure" if self.technical_outcome else "solved" if self.claim_only else "continue",
                "progress": self.progress(),
            }
        if method == "DELETE" and path.startswith("/api/player/conversations/"):
            return 204, {}, None
        if path.startswith("/api/player/flag/"):
            if not self.completed:
                return 403, {}, {"error": "not_completed"}
            return 200, {}, {"flag": f"noco{{FIXTURE_{self.service.upper()}}}", "spoken": "fixture"}
        return 404, {}, {"error": "unknown_fixture_route"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def handle_request(self):
        if self.server.fixture.trickle_response:
            import time
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            try:
                for byte in b"{}":
                    time.sleep(0.04)
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length)) if length else None
        status, headers, value = self.server.fixture.response(
            self.command, self.path, self.headers, body)
        self.send_response(status)
        for key, value_ in headers.items():
            self.send_header(key, value_)
        self.end_headers()
        if value is not None:
            self.wfile.write(json.dumps(value).encode())

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request


class SolverTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOLVER.is_file(), "The bounded solver must exist")
        self.module = load_solver()
        self.fixture = Fixture()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.fixture = self.fixture
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.client = self.module.Client(self.origin, poll_interval=0)

    def tearDown(self):
        if hasattr(self, "server"):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)

    def test_real_transport_sends_cookie_csrf_and_fresh_session(self):
        flag = self.module.solve(self.client, "mara")
        self.assertEqual(flag, "noco{FIXTURE_MARA}")
        self.assertEqual(self.fixture.sessions, 1)
        mutations = [item for item in self.fixture.requests if item[1] == "/api/player/chat"]
        self.assertTrue(mutations)
        self.assertEqual(mutations[0][2]["Cookie"], "player_session=fixture")
        self.assertEqual(mutations[0][2]["X-Csrf-Token"], self.fixture.csrf)
        self.assertEqual(mutations[0][2]["Origin"], self.origin)

    def test_rook_requires_actual_target_change(self):
        self.assertEqual(self.module.solve(self.client, "rook"), "noco{FIXTURE_ROOK}")
        self.assertEqual(self.fixture.destination, "CTF Receiving Bay")
        chats = [item[3] for item in self.fixture.requests if item[1] == "/api/player/chat"]
        self.assertEqual(len(chats), 2)
        self.assertIn("214", chats[0]["text"])
        self.assertIn("214", chats[1]["text"])
        self.assertIn("628", chats[1]["text"])

    def test_vera_saves_current_version_polls_and_requires_actual_credit(self):
        self.assertEqual(self.module.solve(self.client, "vera"), "noco{FIXTURE_VERA}")
        saves = [item for item in self.fixture.requests if item[1] == "/api/player/note"]
        self.assertEqual(saves[0][3]["expectedVersion"], 1)
        self.assertEqual(self.fixture.review["noteSnapshot"], saves[0][3]["note"])
        self.assertEqual(self.fixture.credit, 500)
        self.assertGreaterEqual(self.fixture.polls, 2)

    def test_vera_can_retry_an_ordinary_denial_with_a_new_note_version(self):
        self.fixture.deny_first_review = True
        self.assertEqual(self.module.solve(self.client, "vera"), "noco{FIXTURE_VERA}")
        saves = [item[3] for item in self.fixture.requests if item[1] == "/api/player/note"]
        self.assertEqual([item["expectedVersion"] for item in saves], [1, 2])

    def test_mara_does_not_accept_model_claims_or_read_a_flag_before_completion(self):
        self.fixture.claim_only = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "mara")
        self.assertFalse(any("/api/player/flag/" in item[1] for item in self.fixture.requests))
        self.assertLessEqual(sum(item[1] == "/api/player/chat" for item in self.fixture.requests), 3)

    def test_rook_does_not_accept_a_verbal_destination_claim(self):
        self.fixture.claim_only = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "rook")
        self.assertFalse(any("/api/player/flag/" in item[1] for item in self.fixture.requests))
        self.assertLessEqual(sum(item[1] == "/api/player/chat" for item in self.fixture.requests), 4)

    def test_vera_does_not_accept_a_credited_label_without_the_ledger_outcome(self):
        self.fixture.claim_only = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "vera")
        self.assertFalse(any("/api/player/flag/" in item[1] for item in self.fixture.requests))
        self.assertLessEqual(self.fixture.review_attempts, 3)

    def test_pending_review_is_bounded_by_the_global_deadline(self):
        self.fixture.pending_forever = True
        self.client = self.module.Client(self.origin, timeout=0.03, poll_interval=0)
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "vera")
        self.assertFalse(any("/api/player/flag/" in item[1] for item in self.fixture.requests))

    def test_service_failure_is_not_retried_or_echoed(self):
        self.fixture.fail_http = True
        with self.assertRaises(self.module.SolverError) as error:
            self.module.solve(self.client, "mara")
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertNotIn("fixture-private-response", str(error.exception))
        self.assertTrue(error.exception.__cause__.fp.closed,
                        "HTTP errors must close their response socket")

    def test_redirect_is_not_followed(self):
        self.fixture.redirect = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "mara")
        self.assertEqual(len(self.fixture.requests), 1)

    def test_invalid_progress_fails_closed(self):
        self.fixture.bad_schema = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "mara")
        self.assertFalse(any("/api/player/flag/" in item[1] for item in self.fixture.requests))

    def test_missing_json_is_a_controlled_service_error(self):
        self.fixture.no_content = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "mara")
        self.assertEqual(len(self.fixture.requests), 1)

    def test_request_deadline_caps_total_time_not_just_socket_inactivity(self):
        from unittest.mock import patch
        self.fixture.trickle_response = True
        with patch.object(self.module, "REQUEST_SECONDS", 0.06, create=True):
            with self.assertRaises(self.module.SolverError):
                self.client.request("GET", "/api/player/catalog")

    def test_nested_request_timer_does_not_extend_the_outer_deadline(self):
        import signal
        import time

        def expired(_signal, _frame):
            raise self.module.SolverError("outer test deadline")

        previous_handler = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, 0.15)
        try:
            with self.module.request_deadline(1):
                time.sleep(0.03)
            remaining, _interval = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(remaining, 0)
            self.assertLess(remaining, 0.135)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def test_technical_chat_outcome_is_not_retried_as_an_attack_failure(self):
        self.fixture.technical_outcome = True
        self.fixture.claim_only = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "mara")
        self.assertEqual(sum(item[1] == "/api/player/chat" for item in self.fixture.requests), 1)

    def test_precompleted_session_is_not_accepted_as_fresh_solve_evidence(self):
        self.fixture.initially_completed = True
        with self.assertRaises(self.module.SolverError):
            self.module.solve(self.client, "mara")
        self.assertFalse(any("/api/player/chat" in item[1] or "/api/player/flag/" in item[1]
                             for item in self.fixture.requests))

    def test_non_loopback_client_requires_paid_opt_in(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(self.module.SolverError):
            self.module.Client("https://example.test")

    def test_loopback_fixtures_do_not_use_an_inherited_network_proxy(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
            client = self.module.Client(self.origin, poll_interval=0)
            self.assertEqual(self.module.solve(client, "mara"), "noco{FIXTURE_MARA}")

    def test_cli_arms_150_second_hard_deadline_and_interrupts_a_blocking_operation(self):
        import contextlib
        import io
        import signal
        import time
        from unittest.mock import patch

        actual_setitimer = signal.setitimer
        configured = []

        def accelerate(which, seconds):
            configured.append(seconds)
            return actual_setitimer(which, 0.03 if seconds else 0)

        def blocked_solve(_client, _challenge):
            time.sleep(0.2)
            return "noco{FIXTURE_MARA}"

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, TARGET=self.origin, NOCO_EXTERNAL_LIVE="1"), \
                patch.object(sys, "argv", [str(SOLVER), "mara"]), \
                patch.object(signal, "setitimer", side_effect=accelerate), \
                patch.object(self.module, "solve", side_effect=blocked_solve), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                self.module.main()
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(configured, [150, 0])
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("hard 150-second", stderr.getvalue())
        self.assertEqual(self.fixture.requests, [])

    def test_cli_without_paid_opt_in_makes_no_request(self):
        env = dict(os.environ, TARGET=self.origin)
        env.pop("NOCO_EXTERNAL_LIVE", None)
        result = subprocess.run([sys.executable, str(SOLVER), "mara"], env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("NOCO_EXTERNAL_LIVE=1", result.stderr)
        self.assertEqual(self.fixture.requests, [])

    def test_cli_prints_only_an_actual_earned_flag(self):
        result = subprocess.run(
            [sys.executable, str(SOLVER), "mara"],
            env=dict(os.environ, TARGET=self.origin, NOCO_EXTERNAL_LIVE="1"),
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "noco{FIXTURE_MARA}\n")
        self.assertEqual(result.stderr, "")

    def test_rejects_unsafe_targets_before_network(self):
        for target in ("http://example.test", "https://user:pass@example.test",
                       "https://example.test/path", "https://example.test?key=value",
                       "https://example.test#fragment", "file:///tmp/file"):
            with self.subTest(target=target), self.assertRaises(self.module.SolverError):
                self.module.Client(target)


if __name__ == "__main__":
    unittest.main()
