#!/usr/bin/env python3
"""Fast lifecycle tests with a fake emulator boundary."""
import asyncio
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
spec = importlib.util.spec_from_file_location("ota_gateway", SRC / "gateway.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)
import flagslots


class FakeInstance:
    def __init__(self, port):
        self.port = port
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeSession:
    def __init__(self, port):
        self.inst = FakeInstance(port)
        self.last_input = time.time()
        self.last_reset = 0
        self.reclaims = []
        self.resets = []
        self.reset_entered = None
        self.reset_release = None

    def reset(self, port):
        self.inst.port = port
        self.resets.append(port)
        if self.reset_entered is not None:
            self.reset_entered.set()
            self.reset_release.wait(timeout=2)

    def reclaim(self, port):
        self.inst.port = port
        self.reclaims.append(port)

    def _teardown_line(self):
        pass


def assert_flag_slots():
    master = SRC / "master.rk"
    original = master.read_bytes()
    assert b"noco{" not in original.lower()
    for _, token in flagslots.SLOTS:
        assert original.count(flagslots.slot_bytes(token)) == 1

    values = {
        "FLAG": "noco{runtime_primary_slot}",
        "NOCO_FLAG_LEDGER_ESCAPE": "noco{runtime_ledger_slot}",
        "NOCO_FLAG_PROPRIETOR": "noco{runtime_proprietor_slot}",
    }
    with tempfile.TemporaryDirectory() as directory:
        private = Path(directory) / "disk.rk"
        shutil.copyfile(master, private)
        flagslots.inject(private, values)
        patched = private.read_bytes()
        assert len(patched) == len(original)
        for name, token in flagslots.SLOTS:
            assert flagslots.slot_bytes(token) not in patched
            replacement = values[name].encode().ljust(flagslots.SLOT_SIZE, b" ")
            assert patched.count(replacement) == 1
    assert master.read_bytes() == original


def assert_terminal_translation():
    assert gateway.translate_input(b"clerx\x7fk\r") == b"clerx#k\r"
    assert gateway.translate_input(b"clerx\x08k\r") == b"clerx#k\r"
    assert gateway.translate_input(b"plain input\r") == b"plain input\r"


def assert_origin_policy():
    assert gateway.origin_allowed("https://old-town-accounts.chal.nocohackers.com")
    assert gateway.origin_allowed("http://old-town-accounts.chal.localhost")
    assert gateway.origin_allowed("http://127.0.0.1:49152")
    assert gateway.origin_allowed("http://localhost:8080")
    assert not gateway.origin_allowed("https://ghostdex.chal.nocohackers.com")
    assert not gateway.origin_allowed("https://old-town-accounts.chal.nocohackers.com.evil")
    assert not gateway.origin_allowed("")


def assert_replacement_guard():
    class FakeWriter:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        def write(self, data):
            pass

    class FakeInstanceForConnect:
        port = 4999

    def bare_session():
        session = gateway.Session.__new__(gateway.Session)
        session.gen = 0
        session.replacing = False
        session.writer = None
        session.state_lock = threading.Lock()
        session.ring = []
        session.live = None
        session.live_loop = None
        session.last_input = time.time()
        session.last_reset = 0
        session.line_alive = False
        session.pending = b""
        session.inst = FakeInstanceForConnect()
        return session

    session = bare_session()
    session.connect_lock = asyncio.Lock()
    session._teardown_line(replacing=True)
    assert asyncio.run(session.ensure_tcp()) is None

    async def replacement_during_connect():
        session = bare_session()
        session.connect_lock = asyncio.Lock()
        entered = asyncio.Event()
        release = asyncio.Event()
        writer = FakeWriter()
        original = gateway.asyncio.open_connection

        async def fake_open_connection(host, port):
            entered.set()
            await release.wait()
            return object(), writer

        gateway.asyncio.open_connection = fake_open_connection
        try:
            task = asyncio.create_task(session.ensure_tcp())
            await entered.wait()
            session._teardown_line(replacing=True)
            release.set()
            assert await task is None
            assert writer.closed and session.writer is None
        finally:
            gateway.asyncio.open_connection = original

    asyncio.run(replacement_during_connect())


def assert_stale_websocket_guard():
    class FakeSessionForWebSocket:
        def __init__(self):
            self.gen = 0
            self.live = None
            self.ring = []
            self.last_input = 123
            self.sent = []

        async def ensure_tcp(self):
            return self.gen

        def bind_websocket(self, generation, websocket, loop):
            if generation != self.gen:
                return False
            self.live = websocket
            return True

        def replay(self, generation):
            return b"" if generation == self.gen else None

        def unbind_websocket(self, websocket):
            if self.live is websocket:
                self.live = None

        def send_line(self, message, generation):
            if generation != self.gen:
                return False
            self.sent.append(message)
            self.last_input = time.time()
            return True

    session = FakeSessionForWebSocket()

    class FakePool:
        def get(self, token):
            return session if token == "old" else None

        def bind_websocket(self, token, candidate, generation, websocket, loop):
            if token != "old" or candidate is not session:
                return False
            return candidate.bind_websocket(generation, websocket, loop)

    class FakeRequest:
        headers = {"Cookie": "ota_sess=old"}

    class FakeWebSocket:
        request = FakeRequest()

        def __init__(self):
            self.closed = None
            self.sent = []
            self.once = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.once:
                raise StopAsyncIteration
            self.once = True
            session.gen += 1              # reset/reclaim before stale input
            return "whoami\r"

        async def send(self, data):
            self.sent.append(data)

        async def close(self, code, reason):
            self.closed = (code, reason)

    original = gateway.POOL
    gateway.POOL = FakePool()
    try:
        websocket = FakeWebSocket()
        asyncio.run(gateway.ws_handler(websocket))
        assert websocket.closed == (4403, "machine replaced")
        assert session.sent == []
        assert session.last_input == 123
    finally:
        gateway.POOL = original

    connecting = FakeSessionForWebSocket()

    class ReplacedWhileConnectingPool:
        def __init__(self):
            self.owned = True

        def get(self, token):
            return connecting if self.owned and token == "old" else None

        def bind_websocket(self, token, candidate, generation, websocket, loop):
            return False                    # old token was unbound meanwhile

    connecting_pool = ReplacedWhileConnectingPool()

    async def replaced_ensure_tcp():
        connecting_pool.owned = False
        connecting.gen += 1                # replacement completed during await
        return connecting.gen

    connecting.ensure_tcp = replaced_ensure_tcp
    gateway.POOL = connecting_pool
    try:
        websocket = FakeWebSocket()
        asyncio.run(gateway.ws_handler(websocket))
        assert websocket.closed == (4403, "machine replaced")
        assert connecting.live is None and connecting.sent == []
    finally:
        gateway.POOL = original


def assert_lifecycle():
    original = gateway.Session
    gateway.Session = FakeSession
    try:
        pool = gateway.Pool(2, 3, 10)
        assert len({session.inst.port for session in pool.warm}) == 2
        first, first_token = pool.allocate()
        second, second_token = pool.allocate()
        third, third_token = pool.allocate()
        assert pool.total() == 3 and not pool.warm
        assert pool.reset(first_token) and len(first.resets) == 1
        try:
            pool.reset(first_token)
        except gateway.ResetThrottled:
            pass
        else:
            raise AssertionError("reset cooldown wasn't enforced")
        try:
            pool.allocate()
        except gateway.CapacityError:
            pass
        else:
            raise AssertionError("pool exceeded its cap")

        now = time.time()
        first.last_input = now - 20
        second.last_input = now - 30            # least recently active
        third.last_input = now - 15
        reclaimed, replacement = pool.allocate()
        assert reclaimed is second
        assert second_token not in pool.sessions
        assert not pool.reset(second_token)
        assert pool.was_reclaimed(second_token)
        assert pool.sessions[replacement] is second
        assert pool.total() == 3
        assert gateway.CAPACITY_MESSAGE == (
            "no avaliable PDP/11 instances, reach out to the organizers on "
            "the NoCo Hackers CTF channel")
        pool.stop_all()

        expiring = gateway.Pool(1, 1, 3600)
        expired_session, expired_token = expiring.allocate()
        expiring.expires[expired_token] = time.time() - 1
        assert expiring.get(expired_token) is None
        replacement_session, replacement_token = expiring.allocate()
        assert replacement_session is expired_session
        assert replacement_token != expired_token
        assert expiring.was_reclaimed(expired_token)
        expiring.stop_all()

        racing = gateway.Pool(1, 1, 0)
        raced_session, raced_token = racing.allocate()
        raced_session.reset_entered = threading.Event()
        raced_session.reset_release = threading.Event()
        reset_result = []
        allocate_result = []
        reset_thread = threading.Thread(
            target=lambda: reset_result.append(racing.reset(raced_token)))
        reset_thread.start()
        assert raced_session.reset_entered.wait(timeout=1)
        allocate_thread = threading.Thread(
            target=lambda: allocate_result.append(racing.allocate()))
        allocate_thread.start()
        time.sleep(0.05)
        assert allocate_thread.is_alive()       # reset holds ownership lock
        raced_session.reset_release.set()
        reset_thread.join()
        allocate_thread.join()
        assert reset_result == [True] and len(allocate_result) == 1
        assert not racing.reset(raced_token)    # old token cannot reset assignee
        racing.stop_all()

        concurrent = gateway.Pool(0, 5, 3600)
        successes = []
        full = []

        def allocate():
            try:
                successes.append(concurrent.allocate())
            except gateway.CapacityError:
                full.append(True)

        threads = [threading.Thread(target=allocate) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(successes) == 5 and len(full) == 15
        assert concurrent.total() == 5
        assert len({session.inst.port for session, _ in successes}) == 5
        concurrent.stop_all()
    finally:
        gateway.Session = original


if __name__ == "__main__":
    assert_flag_slots()
    assert_terminal_translation()
    assert_origin_policy()
    assert_replacement_guard()
    assert_stale_websocket_guard()
    assert_lifecycle()
