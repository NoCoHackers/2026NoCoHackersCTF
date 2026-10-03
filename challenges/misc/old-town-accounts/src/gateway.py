#!/usr/bin/env python3
"""Pool-enabled gateway for Old Town Accounts.

    browser --HTTP(S)--> gateway (cookie auth + terminal relay)
                     -> TCP -> emulator DLI line 0 (guest /dev/tty9)

Pool lifecycle:
  - NOCO_POOL_INITIAL warm instances booted at startup (default 5)
  - grows on demand to NOCO_POOL_MAX total (assigned + warm, default 20)
  - at cap: reclaim the least-recently-active instance idle >=
    NOCO_IDLE_SECS (default 21600 = 6h); activity = player keystrokes only
  - nothing reclaimable: HTTP 503 with the agreed capacity message
  - never auto-shrinks; reset reuses the allocation; reconnect keeps the
    guest login (TCP side outlives the websocket)

HTTP and WebSocket traffic share port 8080. Guest tty ports come from the
pool allocator (fresh port per boot -- simh tmxr sets no SO_REUSEADDR and a
killed emulator's port lingers in TIME_WAIT).
"""
import asyncio, atexit, collections, os, pty, re, secrets, shutil, signal, socket, subprocess, sys, termios, threading, time
from http import HTTPStatus

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT + "/vendor")          # vendored websockets wheel
from websockets.asyncio.server import serve    # noqa: E402
from websockets.datastructures import Headers  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402
from websockets.http11 import Response         # noqa: E402
from flagslots import inject as inject_flags   # noqa: E402

PORT = int(os.environ.get("PORT", "8080"))
# Port base varies per gateway process: simh tmxr sets no SO_REUSEADDR, so a
# restarted gateway must not hand out ports still in TIME_WAIT from the runs
# it replaced. Distinct pid -> distinct, non-adjacent port slots.
PORT_BASE = 4100 + 2 * ((os.getpid() * 13) % 400)
COOKIE = "ota_sess"
INST = os.environ.get("NOCO_INSTANCE_DIR", "/tmp/old-town-accounts")
MASTER = os.environ.get("NOCO_MASTER", ROOT + "/master.rk")
SIM = os.environ.get("NOCO_SIM", ROOT + "/bin/pdp11")
WEB = ROOT + "/web"
DEBUG_STATUS = os.environ.get("NOCO_DEBUG_STATUS") == "1"

POOL_INITIAL = int(os.environ.get("NOCO_POOL_INITIAL", "5"))
POOL_MAX = int(os.environ.get("NOCO_POOL_MAX", "20"))
IDLE_SECS = int(os.environ.get("NOCO_IDLE_SECS", "21600"))   # 6h
SESSION_TTL = int(os.environ.get("NOCO_SESSION_TTL", "43200"))  # 12h
RESET_COOLDOWN = int(os.environ.get("NOCO_RESET_COOLDOWN", "30"))

PRODUCTION_ORIGIN = "https://old-town-accounts.chal.nocohackers.com"
DEV_ORIGIN = "http://old-town-accounts.chal.localhost"
LOCAL_ORIGIN_RE = re.compile(r"http://(?:127\.0\.0\.1|localhost)(?::\d+)?$")
ALLOWED_ORIGINS = [PRODUCTION_ORIGIN, DEV_ORIGIN, LOCAL_ORIGIN_RE]

CAPACITY_MESSAGE = ("no avaliable PDP/11 instances, reach out to the "
                    "organizers on the NoCo Hackers CTF channel")


class CapacityError(Exception):
    pass


class ResetThrottled(Exception):
    pass


def make_ini(directory, port):
    """Boot config for one instance. The tty line port is per-boot: simh's
    tmxr sets no SO_REUSEADDR, so rebinding a port whose emulator died with
    an open connection fails silently (kernel TIME_WAIT). Fresh port per
    boot sidesteps it; a tmxr patch is a production-hardening option.
    Player terminal = DLI line 0, KL minor 1 (/dev/tty9) in the rebuilt V4
    kernel. DLO is enabled automatically with DLI by OpenSIMH."""
    return f"""\
set quiet
set cpu 11/45
set cpu idle
set tc enabled
attach rk0 {directory}/disk.rk
set dli enabled
set dli lines=1
set dlo0 7b
attach dli 127.0.0.1:{port}
deposit sr 2
send "k"
expect "\\r" send "unix\\r"; go
boot rk
"""


class Instance:
    """One emulator process with its private disk copy (copy-on-write from master)."""

    def __init__(self):
        self.proc = None
        self._master = None
        self._watcher = None
        self.directory = None
        self.port = None

    def start(self, port):
        self.stop()
        self.port = port
        self._wait_port_free(port)
        # Every instance gets its own directory: its private disk copy (the
        # per-player copy-on-write), its ini, and its logs. A shared path
        # made parallel boots overwrite each other's config and disk.
        d = f"{INST}/i{port}"
        self.directory = d
        os.makedirs(d, exist_ok=True)
        try:
            shutil.copyfile(MASTER, d + "/disk.rk")
            # Flags enter only the private runtime copy. The immutable master
            # carries unique fixed-width tokens, never event flag literals.
            inject_flags(d + "/disk.rk")
            open(d + "/boot.ini", "w").write(make_ini(d, port))
            # A pty makes SIMH's console output line-buffered for readiness.
            master, slave = pty.openpty()
            self._master = master
            try:
                attrs = termios.tcgetattr(master)
                attrs[0] = attrs[1] = 0
                attrs[3] &= ~(termios.ECHO | termios.ICANON)
                termios.tcsetattr(master, termios.TCSANOW, attrs)
                self.proc = subprocess.Popen(
                    [SIM, d + "/boot.ini"], cwd=d,
                    stdin=subprocess.DEVNULL, stdout=slave,
                    stderr=open(d + "/stderr.log", "ab"),
                    start_new_session=True)
            finally:
                os.close(slave)
            self.ready = threading.Event()
            self._watcher = threading.Thread(
                target=self._watch_console, daemon=True)
            self._watcher.start()
            # Console tty8 shows login: when init is ready. Never probe DLI:
            # connecting there would consume the player's single mux line.
            if not self.ready.wait(20):
                raise RuntimeError("no login prompt on console within 20s")
        except Exception:
            self.stop()
            raise

    def _watch_console(self):
        buf = b""
        full = open(f"{INST}/i{self.port}/console-full.log", "ab")  # simh msgs too
        try:
            while True:
                chunk = os.read(self._master, 4096)
                if not chunk:
                    break
                full.write(chunk); full.flush()
                if not self.ready.is_set():
                    buf += chunk
                    if b"login:" in buf:
                        self.ready.set()
        except OSError:
            pass
        finally:
            full.close()

    def _wait_port_free(self, port):
        """The mux attach silently fails if the old listener lingers."""
        for _ in range(40):
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=0.3)
                s.close()                      # old listener still up
            except OSError:
                return                         # refused = free
            time.sleep(0.25)
        raise RuntimeError("tty port still in use before boot")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None
        m = self._master
        if m is not None:
            try:
                os.close(m)
            except OSError:
                pass
            self._master = None
        if self._watcher is not None:
            self._watcher.join(timeout=2)
            self._watcher = None
        if self.directory is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None


def translate_input(buf):
    """Map modern terminal erase bytes to UNIX V4's configured '#' erase."""
    return buf.replace(b"\x7f", b"#").replace(b"\x08", b"#")


def strip_iac(buf, state):
    """Drop telnet negotiation (IAC ...) that simh's mux sends; pass data bytes.

    simh tmxr lines speak telnet control sequences on connect; we never
    negotiate back (legal), we just must not forward 0xFF commands to a
    browser terminal as garbage.
    """
    out = bytearray()
    for b in buf:
        if state.get("n"):
            state["n"] -= 1              # inside an IAC command
            if state["n"] == 0 and b == 250:   # SB: option subnegotiation
                state["n"] = None              # swallow until IAC SE
        elif state["n"] is None:
            if b == 240:                 # SE ends subnegotiation
                state["n"] = 0
        elif b == 255:
            state["n"] = 2               # IAC CMD OPT at minimum
        else:
            out.append(b)
    return bytes(out)


class Session:
    """TCP side of one player's terminal; websockets attach around it."""

    def __init__(self, port):
        self.gen = 0
        self.inst = Instance()
        self.inst.start(port)
        self.writer = None
        self.replacing = False
        self.state_lock = threading.Lock()
        self.connect_lock = asyncio.Lock()
        self.ring = collections.deque(maxlen=2048)   # last ~2KB for reattach replay
        self.live = None                              # attached ws, if any
        self.live_loop = None
        self.last_input = time.time()                 # activity = keystrokes only
        self.last_reset = 0
        self.line_alive = False      # guest line has produced output (ready to read)
        self.pending = b""           # keystrokes held until the line is alive

    async def ensure_tcp(self):
        async with self.connect_lock:
            with self.state_lock:
                if self.replacing:
                    return None
                if self.writer is not None:
                    return self.gen
                generation = self.gen
                port = self.inst.port
            for _ in range(10):              # listener may be mid-rebind
                try:
                    r, w = await asyncio.open_connection("127.0.0.1", port)
                    break
                except OSError:
                    await asyncio.sleep(0.5)
            else:
                raise RuntimeError("tty line unreachable")
            with self.state_lock:
                if self.replacing or generation != self.gen:
                    w.close()
                    return None
                if self.writer is not None:
                    w.close()
                    return self.gen
                self.writer = w
                # Warm instances started getty before this TCP client existed,
                # so its first prompt was discarded by the unattached DLO. A
                # lower-case bogus name wakes getty and proves lower-case support.
                self.writer.write(b"x\r")
            asyncio.create_task(self._drain(r, w, generation))
            asyncio.get_running_loop().call_later(
                3.0, self._flush_pending, generation)
            return generation

    def bind_websocket(self, generation, ws, loop):
        with self.state_lock:
            if self.replacing or generation != self.gen:
                return False
            self.live = ws
            self.live_loop = loop
            return True

    def replay(self, generation):
        with self.state_lock:
            if self.replacing or generation != self.gen:
                return None
            return b"".join(self.ring)[-512:]

    def unbind_websocket(self, ws):
        with self.state_lock:
            if self.live is ws:
                self.live = None
                self.live_loop = None

    def _flush_pending_locked(self):
        if self.pending and self.writer is not None:
            self.writer.write(self.pending)
            self.pending = b""

    def _flush_pending(self, generation):
        with self.state_lock:
            if not self.replacing and generation == self.gen:
                self._flush_pending_locked()

    def send_line(self, msg: bytes, generation):
        """Atomically validate ownership generation and deliver a keystroke."""
        with self.state_lock:
            if self.replacing or generation != self.gen:
                return False
            self.last_input = time.time()     # activity = accepted player input only
            if self.line_alive and self.writer:
                self.writer.write(msg)
            else:
                self.pending = (self.pending + msg)[:128]
            return True

    async def _drain(self, reader, writer, gen):
        state = {"n": 0}
        print(f"[drain] start gen={gen} port={self.inst.port}", flush=True)
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                clean = strip_iac(data, state)
                with self.state_lock:
                    if self.replacing or gen != self.gen:
                        break
                    if clean and not self.line_alive:
                        self.line_alive = True
                        self._flush_pending_locked()
                    if clean:
                        self.ring.append(clean)
                    live = self.live
                if clean and live is not None:
                    try:
                        await live.send(clean)
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            writer.close()
            with self.state_lock:
                if gen == self.gen and self.writer is writer:
                    self.writer = None

    def _teardown_line(self, replacing=False):
        with self.state_lock:
            self.replacing = replacing
            self.gen += 1                   # invalidates drain, input, and replay
            live, loop = self.live, self.live_loop
            self.live = None
            self.live_loop = None
            if self.writer:
                self.writer.close()
                self.writer = None
            self.line_alive = False
            self.pending = b""
            self.ring.clear()
        if live is not None and loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                live.close(code=4403, reason="machine replaced"), loop)

    def _replace(self, port):
        self._teardown_line(replacing=True)
        try:
            self.inst.start(port)
        finally:
            with self.state_lock:
                self.replacing = False

    def reset(self, port):
        """Fresh disk + reboot; reuses this allocation (no new session token)."""
        self._replace(port)

    def reclaim(self, port):
        """Same wipe as reset, but the old token is already unbound by the pool."""
        self._replace(port)


class Pool:
    """Bounded set of instances. All allocation decisions happen under one
    lock, so simultaneous arrivals can neither double-assign nor exceed the
    cap. Never shrinks on its own."""

    def __init__(self, initial, maxsize, idle_secs):
        self.lock = threading.Lock()
        self.sessions = {}                  # token -> assigned Session
        self.expires = {}                   # token -> server-side expiry
        self.warm = []                      # booted, unassigned
        self.reclaimed = {}                 # old token -> time, for notices
        self.maxsize = maxsize
        self.idle_secs = idle_secs
        self._port_n = 0
        self._boot_warm(initial)

    def next_port(self):
        with self.lock:
            return self._next_port_locked()

    def _next_port_locked(self):
        self._port_n += 2
        return PORT_BASE + self._port_n

    def _new_session(self):
        return Session(self._next_port_locked())   # boots; ~2-4s; caller holds lock

    def _boot_warm(self, n):
        """Warm instances boot in parallel; startup waits for all of them."""
        errs = []

        def boot():
            try:
                with self.lock:
                    port = self._next_port_locked()
                s = Session(port)
                with self.lock:
                    self.warm.append(s)
            except Exception as e:
                errs.append(e)
        threads = [threading.Thread(target=boot) for _ in range(n)]
        for t in threads: t.start()
        for t in threads: t.join()
        if errs:
            raise errs[0]

    def allocate(self):
        """Bind a fresh token to an instance. Warm first, then grow, then
        reclaim idle instances at cap. Raises CapacityError when full and
        nothing has been idle long enough."""
        with self.lock:
            now = time.time()
            expired = [(deadline, tok, self.sessions[tok])
                       for tok, deadline in self.expires.items()
                       if deadline <= now]
            if expired:
                _, old_token, sess = min(expired)
                del self.sessions[old_token]
                del self.expires[old_token]
                self.reclaimed[old_token] = now
                sess.reclaim(self._next_port_locked())
            elif self.warm:
                sess = self.warm.pop()
            elif self.total() < self.maxsize:
                sess = self._new_session()  # growth path; boot under lock
            else:
                idle = [(s.last_input, tok, s) for tok, s in self.sessions.items()
                        if now - s.last_input >= self.idle_secs]
                if not idle:
                    raise CapacityError()
                _, old_token, sess = min(idle)      # least recently active
                del self.sessions[old_token]
                del self.expires[old_token]
                self.reclaimed[old_token] = now
                sess.reclaim(self._next_port_locked())  # wipe + fresh boot
            token = secrets.token_urlsafe(24)
            sess.last_input = time.time()
            self.sessions[token] = sess
            self.expires[token] = now + SESSION_TTL
            return sess, token

    def total(self):
        return len(self.sessions) + len(self.warm)

    def get(self, token):
        with self.lock:
            if self.expires.get(token, 0) <= time.time():
                return None
            return self.sessions.get(token)

    def bind_websocket(self, token, sess, generation, ws, loop):
        """Bind only while token still owns this exact session generation."""
        with self.lock:
            if (self.expires.get(token, 0) <= time.time()
                    or self.sessions.get(token) is not sess):
                return False
            return sess.bind_websocket(generation, ws, loop)

    def reset(self, token):
        """Reset only while token still owns the session, serialized with reclaim."""
        with self.lock:
            now = time.time()
            sess = self.sessions.get(token)
            if sess is None or self.expires.get(token, 0) <= now:
                return False
            if now - sess.last_reset < RESET_COOLDOWN:
                raise ResetThrottled()
            sess.last_reset = now
            sess.reset(self._next_port_locked())
            return True

    def was_reclaimed(self, token):
        with self.lock:
            return token in self.reclaimed

    def status(self):
        with self.lock:
            now = time.time()
            return {
                "total": self.total(), "max": self.maxsize,
                "assigned": len(self.sessions), "warm": len(self.warm),
                "sessions": [
                    {"token": t[:8], "port": s.inst.port,
                     "idle_secs": round(now - s.last_input, 1)}
                    for t, s in sorted(self.sessions.items())],
            }

    def stop_all(self):
        """Stop every emulator owned by this gateway process."""
        with self.lock:
            sessions = list(self.sessions.values()) + list(self.warm)
            self.sessions.clear()
            self.expires.clear()
            self.warm.clear()
        for sess in sessions:
            sess._teardown_line()
            sess.inst.stop()


def build_pool():
    return Pool(POOL_INITIAL, POOL_MAX, IDLE_SECS)


POOL = None            # created in __main__; handlers resolve it at runtime


def shutdown(signum=None, frame=None):
    if POOL is not None:
        POOL.stop_all()
    if signum is not None:
        raise SystemExit(128 + signum)


def page(notice=None):
    html = open(WEB + "/terminal.html").read()
    block = ""
    if notice:
        block = (f'<div id="notice" class="visible">{notice}</div>')
    return html.replace("<!--NOTICE-->", block)


CAPACITY_PAGE = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Old Town Accounts</title>
<style>body{{background:#14120f;color:#d8cfae;font-family:ui-monospace,monospace;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
p{{max-width:32em;text-align:center;font-size:1.1em}}</style></head>
<body><p>{CAPACITY_MESSAGE}</p></body></html>
"""


def http_response(code, body, ctype="text/html; charset=utf-8", extra=None):
    data = body if isinstance(body, bytes) else body.encode()
    headers = Headers([
        ("Content-Type", ctype),
        ("Content-Length", str(len(data))),
        ("Connection", "close"),
        *((extra or [])),
    ])
    return Response(code, HTTPStatus(code).phrase, headers, data)


def cookie_token(headers):
    for part in (headers.get("Cookie", "") or "").split(";"):
        if part.strip().startswith(COOKIE + "="):
            return part.strip().split("=", 1)[1]
    return None


def origin_allowed(origin):
    if origin in (PRODUCTION_ORIGIN, DEV_ORIGIN):
        return True
    return bool(origin and LOCAL_ORIGIN_RE.fullmatch(origin))


def handle_http(request):
    path = request.path.split("?", 1)[0]
    if request.method == "GET" and path == "/healthz":
        return http_response(200, "ok\n", "text/plain; charset=utf-8")
    if request.method == "GET" and path == "/":
        token = cookie_token(request.headers)
        presented_token = token
        notice = None
        allocated = False
        if token and POOL.get(token) is not None:
            pass                                       # returning player
        else:
            if token and POOL.was_reclaimed(token):
                notice = ("Your previous machine was reclaimed after a long "
                          "period of inactivity.")
            try:
                _, token = POOL.allocate()
                allocated = True
                if presented_token and POOL.was_reclaimed(presented_token):
                    notice = ("Your previous machine was reclaimed after a long "
                              "period of inactivity.")
            except CapacityError:
                return http_response(503, CAPACITY_PAGE)
            except Exception as error:
                return http_response(500, f"allocation failed: {error!r}")
        extra = None
        if allocated:
            cookie = (f"{COOKIE}={token}; Path=/; Max-Age={SESSION_TTL}; "
                      "HttpOnly; SameSite=Strict")
            forwarded = request.headers.get("X-Forwarded-Proto", "")
            if forwarded.split(",", 1)[0].strip().lower() == "https":
                cookie += "; Secure"
            extra = [("Set-Cookie", cookie)]
        return http_response(200, page(notice), extra=extra)
    if request.method == "GET" and path == "/status" and DEBUG_STATUS:
        import json
        return http_response(200, json.dumps(POOL.status()), "application/json")
    if request.method == "GET" and path == "/xterm.js":
        return http_response(200, open(WEB + "/xterm.js", "rb").read(),
                             "application/javascript")
    if request.method == "GET" and path == "/xterm.css":
        return http_response(200, open(WEB + "/xterm.css", "rb").read(),
                             "text/css")
    if request.method == "POST" and path == "/reset":
        if not origin_allowed(request.headers.get("Origin", "")):
            return http_response(403, "origin denied", "text/plain; charset=utf-8")
        try:
            reset = POOL.reset(cookie_token(request.headers))
        except ResetThrottled:
            return http_response(429, "reset rate limited",
                                 "text/plain; charset=utf-8",
                                 [("Retry-After", str(RESET_COOLDOWN))])
        except Exception as error:
            return http_response(500, f"reset failed: {error!r}",
                                 "text/plain; charset=utf-8")
        if not reset:
            return http_response(403, "no session", "text/plain; charset=utf-8")
        return http_response(200, "restarted", "text/plain; charset=utf-8")
    return http_response(404, "not found", "text/plain; charset=utf-8")


async def process_request(connection, request):
    if request.path.split("?", 1)[0] == "/ws":
        return None
    return await asyncio.to_thread(handle_http, request)


async def ws_handler(ws):
    req = getattr(ws, "request", None)
    cookie = (req.headers.get("Cookie", "") if req else "") or ""
    token = None
    for part in cookie.split(";"):
        if part.strip().startswith(COOKIE + "="):
            token = part.strip().split("=", 1)[1]
    sess = await asyncio.to_thread(POOL.get, token) if token else None
    if sess is None:
        await ws.close(code=4403, reason="no session")
        return
    generation = await sess.ensure_tcp()
    loop = asyncio.get_running_loop()
    bound = (generation is not None and await asyncio.to_thread(
        POOL.bind_websocket, token, sess, generation, ws, loop))
    if not bound:
        await ws.close(code=4403, reason="machine replaced")
        return
    # replay the tail so a reconnecting player sees where they are
    tail = sess.replay(generation)
    if tail is None:
        await ws.close(code=4403, reason="machine replaced")
        return
    if tail:
        await ws.send(tail)
    try:
        async for msg in ws:            # keystrokes -> guest tty
            if isinstance(msg, str):
                msg = msg.encode("latin-1")
            msg = translate_input(msg)
            if not sess.send_line(msg, generation):
                await ws.close(code=4403, reason="machine replaced")
                return
    except ConnectionClosed:
        pass                            # browser refreshes and network drops are normal
    finally:
        sess.unbind_websocket(ws)        # detach: TCP and guest login survive


async def main():
    async with serve(ws_handler, "0.0.0.0", PORT, origins=ALLOWED_ORIGINS,
                     max_size=4096, process_request=process_request):
        await asyncio.Future()


if __name__ == "__main__":
    POOL = build_pool()
    atexit.register(shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"pool warm: {POOL.status()}", flush=True)
    asyncio.run(main())
