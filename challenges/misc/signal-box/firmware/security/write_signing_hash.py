#!/usr/bin/env python3
"""Guarded sacrificial slot-0 hash writer. Preparation is not write authorization."""

import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

import otp_policy
import prepare_signing_hash as signing
import recovery_images
import restore_signing_hash as backup

ARTIFACT = signing.OUTPUT_PARENT / (
    "slot0-hash-9423D016AADE5950-prepared-20260911T173747.602106Z")
STATE_ROOT = backup.restore.BASE / "provisioning-attempts"
LATCH_NAME = f"slot0-hash-{otp_policy.SERIAL}.attempt.json"
LOCK_NAME = f"slot0-hash-{otp_policy.SERIAL}.lock"
TARGETS = tuple(range(0x80, 0x90))
CANDIDATES = tuple(range(0x80, 0xc0)) + tuple(range(0x740, 0x800))
FLASH_SIZE = 2097152
MAX_PREWRITE_AGE = 10
CONFIRMATION = f"PROGRAM HASH ONLY {otp_policy.SERIAL}"
IDENTITY = {
    "type": "RP2350", "revision": "A4", "chipid": "0x9423d016aade5950",
    "current cpu": "ARM", "available cpus": "ARM, RISC-V", "default cpu": "ARM",
    "secure boot": "0", "debug enable": "1", "secure debug enable": "1",
    "rom gitrev": "0xa8bfe860", "boot type": "bootsel",
}
BAD_DIAGNOSTIC = re.compile(r"\b(?:WARNING|ERROR|FATAL|FAILED|Mismatch)\b", re.I)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_identity(text):
    if BAD_DIAGNOSTIC.search(text):
        raise ValueError("Device information reported a diagnostic; stop")
    seen = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([^:]+):\s*(.*?)\s*", line)
        if match and match[1].strip() in IDENTITY:
            key, value = match[1].strip(), match[2]
            if key in seen:
                raise ValueError("Duplicate device identity field")
            seen[key] = value
    if seen != IDENTITY:
        raise ValueError("Target identity, BOOTSEL or unprovisioned security state differs")
    return seen


def parse_rows(text, rows, ecc=False):
    if BAD_DIAGNOSTIC.search(text):
        raise ValueError("OTP reader reported a diagnostic; contents suppressed")
    expected, result, current = set(rows), {}, None
    if not rows or len(expected) != len(rows):
        raise ValueError("Expected an exact, nonduplicate row selection")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ROW"):
            match = re.fullmatch(r"ROW (0x[0-9a-fA-F]{4})(?:\b.*)?", line)
            if not match or (current is not None and current not in result):
                raise ValueError("Malformed/incomplete OTP row header")
            current = int(match[1], 16)
            if current not in expected or current in result:
                raise ValueError("Unexpected/duplicate OTP row")
        elif line.startswith("VALUE"):
            match = re.fullmatch(r"VALUE (0x[0-9a-fA-F]+)", line)
            if not match or current is None or current in result:
                raise ValueError("Malformed, duplicate or orphan OTP value")
            value = int(match[1], 16)
            if value > (0xffff if ecc else 0xffffff):
                raise ValueError("OTP value exceeds the selected encoding")
            result[current] = value
    if set(result) != expected:
        raise ValueError("Incomplete OTP row coverage")
    return result


def positive_verification(text):
    return (not BAD_DIAGNOSTIC.search(text) and
            len(re.findall(r"(?m)^\s*Verified OK\s*$", text)) == 1)


def load_plan(tool):
    # No device connection: existing validator uses explicit file-only tools.
    artifact = backup.check_working(tool, ARTIFACT)
    review = json.loads((artifact / "review.json").read_text())
    journal = json.loads(signing.ROUND_TRIP.read_text())
    payload = (artifact / signing.PAYLOAD).read_bytes()
    if (payload != signing.hash_payload(review["signing_public_key_sha256_xy"]) or
            signing.row_plan(payload) != review["rows"]):
        raise ValueError("Hash artifact differs from its reviewed encoding")
    return {
        "payload": payload, "payload_sha256": sha(payload),
        "public_key_sha256_xy": review["signing_public_key_sha256_xy"],
        "tool_sha256": review["picotool_binary_sha256"],
        "artifact_manifest_sha256": recovery_images.digest(artifact / "SHA256SUMS"),
        "review_sha256": recovery_images.digest(artifact / "review.json"),
        "recovery_journal_sha256": review["recovery_test_audit_sha256"],
        "flash_sha256": journal["flash_after_sha256"],
    }


@contextmanager
def sealed_file(path, expected_hash, size=None, executable=False):
    """Linux sealed memfd: pin validated bytes, not a replaceable pathname."""
    limit = 64 * 1024 * 1024 if executable else 32
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("Invalid transport input file")
        data = source.read(limit + 1)
    if len(data) > limit or (size is not None and len(data) != size) or sha(data) != expected_hash:
        raise ValueError("Transport snapshot differs from validated bytes")
    flags = os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    if executable:
        flags |= getattr(os, "MFD_EXEC", 0)
    handle = os.memfd_create("noco-tool" if executable else "noco-hash", flags)
    try:
        view = memoryview(data)
        while view:
            written = os.write(handle, view)
            if written <= 0:
                raise OSError("Short memfd write")
            view = view[written:]
        os.lseek(handle, 0, os.SEEK_SET)
        os.fchmod(handle, 0o500 if executable else 0o400)
        seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        fcntl.fcntl(handle, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(handle, fcntl.F_GET_SEALS) & seals != seals:
            raise ValueError("Transport snapshot is not immutable")
        yield handle
    finally:
        os.close(handle)


class NativeDevice:
    """Fixed commands only. Every call is serial-selected and tool-hash checked."""

    def __init__(self, tool, plan):
        self.tool = tool.resolve(strict=True)
        self.plan = plan
        self.write_called = False

    def _invoke(self, args, writing=False, payload_fd=None, deadline=None):
        args = list(map(str, args))
        if (args.count("--ser") != 1 or args.index("--ser") == len(args) - 1 or
                args[args.index("--ser") + 1] != otp_policy.SERIAL):
            raise ValueError("Every device command must select the exact serial once")
        # The executable and (for writes) payload are immutable inherited fds.
        # No pathname is reopened by the child after our byte/hash validation.
        with sealed_file(self.tool, self.plan["tool_sha256"], executable=True) as executable_fd:
            inherited = (executable_fd,) if payload_fd is None else (executable_fd, payload_fd)
            # Check after potentially blocking file reads/sealing, immediately
            # before spawning. Scheduling/USB transactions cannot be atomic here.
            if writing and (deadline is None or freshness_clock() > deadline):
                raise ValueError("Preflight expired during transport preparation")
            result = subprocess.run([str(self.tool), *args],
                                    executable=f"/proc/self/fd/{executable_fd}", pass_fds=inherited,
                                    capture_output=True, timeout=None if writing else 120)
        if result.returncode or result.stderr.strip() or len(result.stdout) > 1024 * 1024:
            raise ValueError("Device command failed or reported diagnostics; raw output suppressed")
        text = result.stdout.decode("utf-8", errors="strict")
        if BAD_DIAGNOSTIC.search(text):
            raise ValueError("Device command reported a stdout diagnostic; contents suppressed")
        return text

    def identity(self):
        return parse_identity(self._invoke(["info", "--debug", "--ser", otp_policy.SERIAL]))

    def rows(self, rows, ecc=False):
        # Option order matters: '-r -c 1' previously parsed 1 as a row selector.
        if (not rows or len(set(rows)) != len(rows) or
                not set(rows).issubset(set(CANDIDATES) | set(otp_policy.baseline_rows())) or
                (ecc and tuple(rows) != TARGETS)):
            raise ValueError("Row selection leaves the reviewed preflight scope")
        # Device selection must precede the repeatable selector group; trailing
        # --ser can be consumed as another selector by this pinned CLI parser.
        args = ["otp", "get", "-c", "1", "-e" if ecc else "-r", "-n", "--ser", otp_policy.SERIAL]
        return parse_rows(self._invoke([*args, *[f"0x{r:04x}" for r in rows]]), rows, ecc)

    def flash(self, destination):
        if destination.exists() or destination.is_symlink():
            raise ValueError("Never overwrite a flash backup")
        text = self._invoke(["save", "-r", "0x10000000", "0x10200000", "-v",
                             destination, "-t", "bin", "--ser", otp_policy.SERIAL])
        signing.private_file(destination, FLASH_SIZE)
        if (destination.stat().st_size != FLASH_SIZE or BAD_DIAGNOSTIC.search(text) or
                "Verifying" not in text or not re.search(r"\bOK\s*$", text)):
            raise ValueError("Full-flash save verification failed")
        return recovery_images.digest(destination)

    def program(self, payload, deadline):
        if self.write_called:
            raise ValueError("A second write call is prohibited")
        signing.private_file(payload, 32)
        self.write_called = True
        with sealed_file(payload, self.plan["payload_sha256"], size=32) as payload_fd:
            # Never execute argv from JSON or caller-supplied row/mode parameters.
            text = self._invoke(["otp", "load", "--ecc", "--start_row", "0x0080",
                                 f"/proc/self/fd/{payload_fd}", "-t", "bin", "--ser", otp_policy.SERIAL],
                                writing=True, payload_fd=payload_fd, deadline=deadline)
        if not positive_verification(text):
            raise ValueError("No unambiguous positive OTP load verification; state may have changed")


def freshness_clock():
    # Linux BOOTTIME includes suspend; a laptop sleep must expire preflight.
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def raw_state(device, payload=None):
    started = freshness_clock()
    if device.identity() != IDENTITY:
        raise ValueError("Device identity changed; stop before reading storage")
    otp_policy.validate_baseline(device.rows(tuple(sorted(otp_policy.baseline_rows()))))
    observed = device.rows(CANDIDATES)
    expected = {row: 0 for row in CANDIDATES}
    if payload is not None:
        for item in signing.row_plan(payload):
            expected[int(item["row"], 16)] = int(item["after_raw24"], 16)
    if observed != expected:
        raise ValueError("Candidate-storage raw state differs; values suppressed; stop")
    return started


def preflight(device, plan, run, name):
    raw_state(device)
    if device.flash(run / name) != plan["flash_sha256"]:
        raise ValueError("Flash differs from the verified recovery round trip")
    return raw_state(device)


def postcheck(device, plan, run):
    raw_state(device, plan["payload"])
    expected = {int(item["row"], 16): int(item["after_ecc16"], 16)
                for item in signing.row_plan(plan["payload"])}
    if device.rows(TARGETS, ecc=True) != expected:
        raise ValueError("Separate host-parity ECC display does not match the hash")
    if device.flash(run / "flash-after.bin") != plan["flash_sha256"]:
        raise ValueError("Flash preservation failed after the hash attempt")
    raw_state(device, plan["payload"])


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def exclusive_json(path, record):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(record, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    sync_directory(path.parent)


def execute(device, plan, run, root, program, confirm, reload_plan):
    """One bounded attempt under the caller's lease; no retry or activation."""
    record = {
        "device_serial": otp_policy.SERIAL, "identity_expected": IDENTITY,
        "writer_sha256": recovery_images.digest(Path(__file__)),
        "artifact_manifest_sha256": plan["artifact_manifest_sha256"],
        "review_sha256": plan["review_sha256"], "tool_sha256": plan["tool_sha256"],
        "payload_sha256": plan["payload_sha256"], "mode": "program-hash-only" if program else "preflight",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": "0x0080–0x008f, 16 ECC16 inputs only",
        "control_writes": [], "secret_writes": [], "write_may_have_occurred": False,
        "more_programming_authorized": False,
    }
    checkpoint = 0

    def save(status):
        nonlocal checkpoint
        record["status"] = status
        exclusive_json(run / f"{checkpoint:02d}-{status}.json", record)
        checkpoint += 1

    latch = root / LATCH_NAME
    try:
        if program and (latch.exists() or latch.is_symlink()):
            raise ValueError("A prior write attempt is latched; investigate, do not retry")
        save("PREPARING")
        frozen = run / "slot0-hash.ecc.bin"
        with frozen.open("xb") as output:
            output.write(plan["payload"])
            output.flush()
            os.fsync(output.fileno())
        frozen.chmod(0o400)
        sync_directory(run)
        preflight(device, plan, run, "flash-before.bin")
        save("LIVE_PREFLIGHT_PASS")
        if not program:
            return "READ_ONLY_PREFLIGHT_PASS"
        if confirm(plan) != CONFIRMATION:
            raise ValueError("Confirmation did not match; no write requested")
        if reload_plan() != plan:
            raise ValueError("Working inputs changed while awaiting confirmation")
        checked = preflight(device, plan, run, "flash-before-final.bin")
        if recovery_images.digest(frozen) != plan["payload_sha256"] or frozen.stat().st_size != 32:
            raise ValueError("Frozen payload changed before intent publication")
        save("WRITE_INTENT_NOT_YET_CALLED")
        # Durable, exclusive attempt latch BEFORE the single irreversible call.
        # Even a later failure that programmed zero bits must not auto-retry.
        exclusive_json(latch, {"device_serial": otp_policy.SERIAL, "run": str(run),
                               "payload_sha256": plan["payload_sha256"],
                               "scope": "hash data only; no activation", "do_not_retry": True})
        record["write_may_have_occurred"] = True
        save("ARMED_WRITE_STATE_UNCERTAIN")
        if freshness_clock() - checked > MAX_PREWRITE_AGE:
            raise ValueError("Final preflight is stale; latch retained, no automatic retry")
        device.program(frozen, deadline=checked + MAX_PREWRITE_AGE)
        save("LOAD_VERIFIED_POSTCHECK_PENDING")
        postcheck(device, plan, run)
        save("HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID")
        return "HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID"
    except (OSError, ValueError, EOFError, subprocess.SubprocessError, KeyboardInterrupt):
        try:
            save("STOP_WRITE_STATE_UNCERTAIN" if record["write_may_have_occurred"] else "STOP_BEFORE_WRITE")
        except OSError:
            pass  # Never obscure a potentially irreversible attempt with a log error.
        raise


def confirm_locally(plan):
    print(f"Target: {otp_policy.SERIAL}, A4, ROM a8bfe860. IRREVERSIBLE HASH DATA ONLY.")
    print("32 bytes / 16 ECC rows 0x0080–0x008f; no KEY_VALID, other controls, locks or AES.")
    print("Public signing-key SHA256(X||Y): " + plan["public_key_sha256_xy"])
    print("Backup acknowledgment and this prompt do not replace separate stage approval.")
    return input(f"Type exactly '{CONFIRMATION}' to request this one write: ")


def live(tool, plan, program):
    backup.local_base()
    STATE_ROOT.mkdir(mode=0o700, exist_ok=True)
    root = signing.private_directory(STATE_ROOT)
    # Persist the new root's directory entry, not just files inside that root.
    sync_directory(root.parent)
    fd = os.open(root / LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    run = None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("Unsafe provisioning lease file")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if program and ((root / LATCH_NAME).exists() or (root / LATCH_NAME).is_symlink()):
            raise ValueError("A prior attempt is latched; no retry/override exists")
        run = Path(tempfile.mkdtemp(prefix="slot0-hash-", dir=root))
        sync_directory(root)
        result = execute(NativeDevice(tool, plan), plan, run, root, program,
                         confirm_locally, lambda: load_plan(tool))
        print(f"{result}. Private journal: {run}")
        print("STOP here. No activation, debug policy, locks, AES, reboot or next-stage writes.")
    except (OSError, ValueError, EOFError, subprocess.SubprocessError, KeyboardInterrupt):
        if run is not None:
            print(f"STOP: inspect private journal {run}; any attempt latch must be preserved.", file=sys.stderr)
        raise
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline-check", action="store_true", help="Files only; no device access")
    mode.add_argument("--preflight", action="store_true", help="LIVE read-only checks; separate permission required")
    mode.add_argument("--program-hash-only", action="store_true", help="IRREVERSIBLE; separate approval and local confirmation required")
    parser.add_argument("--ack-backup-restored", action="store_true", help="Operator acknowledgment, not automatic authorization")
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.ack_backup_restored and not args.program_hash_only:
            raise ValueError("Backup acknowledgment applies only to program mode")
        if args.program_hash_only and (not args.ack_backup_restored or
                not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))):
            raise ValueError("Program mode requires backup acknowledgment and a real local terminal")
        tool = args.picotool.resolve(strict=True)
        plan = load_plan(tool)
        if args.offline_check:
            print("OFFLINE WRITER CHECK PASS: fixed restored artifact/tool binding; 32-byte ECC hash scope only.")
            print("No live preflight or programming performed. Backup receipts are not read or treated as authorization.")
        else:
            live(tool, plan, args.program_hash_only)
    except (OSError, ValueError, EOFError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt):
        print("FATAL: Hash-only procedure stopped. Do not retry, clear a latch, activate a key or program another stage. "
              "If a write was attempted, OTP may have changed; investigate its private journal.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
