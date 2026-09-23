"""Simulated-device tests only. Never instantiate an unmocked live transport."""

from contextlib import contextmanager
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import write_signing_hash as writer


FLASH = bytes(writer.FLASH_SIZE)


def plan_for(tool):
    payload = bytes(range(32))
    return {"payload": payload, "payload_sha256": writer.sha(payload),
            "public_key_sha256_xy": payload.hex(), "tool_sha256": writer.recovery_images.digest(tool),
            "artifact_manifest_sha256": "a" * 64, "review_sha256": "b" * 64,
            "recovery_journal_sha256": "c" * 64, "flash_sha256": writer.sha(FLASH)}


class SimulatedDevice:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []
        self.write_count = 0
        self.programmed = False
        self.bad_identity = False
        self.raw_overrides = {}
        self.bad_ecc = False
        self.bad_flash = False
        self.write_failure = None
        self.after_write = lambda: None

    def identity(self):
        self.calls.append(("identity",))
        result = dict(writer.IDENTITY)
        if self.bad_identity:
            result["chipid"] = "another chip"
        return result

    def rows(self, rows, ecc=False):
        self.calls.append(("rows", tuple(rows), ecc))
        expected = writer.otp_policy.baseline_rows()
        expected.update({row: 0 for row in writer.CANDIDATES})
        if self.programmed:
            for item in writer.signing.row_plan(self.plan["payload"]):
                expected[int(item["row"], 16)] = int(item["after_ecc16" if ecc else "after_raw24"], 16)
        expected.update(self.raw_overrides)
        result = {row: expected[row] for row in rows}
        if ecc and self.bad_ecc:
            result[0x80] ^= 1
        return result

    def flash(self, destination):
        self.calls.append(("flash", destination.name))
        destination.write_bytes(FLASH)
        return "0" * 64 if self.bad_flash else self.plan["flash_sha256"]

    def program(self, payload, deadline):
        self.calls.append(("program", payload.name))
        self.write_count += 1
        if payload.read_bytes() != self.plan["payload"]:
            raise ValueError("simulation: wrong payload")
        self.programmed = True
        self.after_write()
        if self.write_failure:
            raise self.write_failure


class ParserTests(unittest.TestCase):
    def test_identity_requires_exact_and_unique_fields(self):
        text = "Program Information\n" + "\n".join(f"  {k}: {v}" for k, v in writer.IDENTITY.items())
        self.assertEqual(writer.parse_identity(text), writer.IDENTITY)
        for bad in (text + "\nrevision: A4", text + "\nWARNING: partition table unavailable", text.replace("secure boot: 0", "secure boot: 1"),
                    text.replace("chipid:", "unrecognized:"), text.replace("bootsel", "normal")):
            with self.assertRaises(ValueError):
                writer.parse_identity(bad)

    def test_raw_and_ecc_parsing_with_field_lines(self):
        raw = "ROW 0x0080: BOOTKEY0_0 (ECC)\n  VALUE 0x230001\nfield EXAMPLE (bit 1): 0\n"
        self.assertEqual(writer.parse_rows(raw, (0x80,)), {0x80: 0x230001})
        self.assertEqual(writer.parse_rows(raw.replace("0x230001", "0x0001"), (0x80,), True), {0x80: 1})

    def test_reject_missing_duplicate_extra_or_malformed_rows(self):
        good = "ROW 0x0080\nVALUE 0x000001\n"
        for bad in ("", good + good, good + "VALUE 0x000001\n", "VALUE 0x000001\n" + good,
                    good.replace("0080", "0081"), good.replace("VALUE ", "VALUE="),
                    good + "ROW 0x0081\n", good.replace("0x000001", "0x1000000")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                writer.parse_rows(bad, (0x80,))
        with self.assertRaises(ValueError):
            writer.parse_rows(good, (0x80, 0x80))
        with self.assertRaises(ValueError):
            writer.parse_rows(good.replace("0x000001", "0x10000"), (0x80,), True)

    def test_reject_warning_even_with_plausible_ecc_value(self):
        text = "ROW 0x0080\nVALUE 0x0001\nRAW_VALUE=0x000001 (WARNING - ECC IS INVALID)\n"
        with self.assertRaises(ValueError):
            writer.parse_rows(text, (0x80,), True)

    def test_exit_success_is_not_positive_verification(self):
        self.assertTrue(writer.positive_verification("  Verified OK\n"))
        for text in ("", "OK\n", "Verified OK\nVerified OK\n", "Mismatch at row 0\n",
                     "Verified OK\nWARNING: other problem\n", "Verified OK\nERROR: failure\n"):
            self.assertFalse(writer.positive_verification(text))


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hash-writer-simulation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mask = os.umask(0o077)
        self.addCleanup(os.umask, self.mask)
        self.tool = self.root / "tool"
        self.tool.write_bytes(b"simulated tool, never executed")
        self.plan = plan_for(self.tool)
        self.run = self.root / "run"
        self.run.mkdir(mode=0o700)
        self.device = SimulatedDevice(self.plan)
        self.confirm = lambda plan: writer.CONFIRMATION
        self.reload = lambda: self.plan

    def execute(self, program=True):
        return writer.execute(self.device, self.plan, self.run, self.root, program, self.confirm, self.reload)

    def test_read_only_preflight_never_prompts_latches_or_writes(self):
        self.confirm = lambda plan: self.fail("read-only path prompted")
        self.assertEqual(self.execute(False), "READ_ONLY_PREFLIGHT_PASS")
        self.assertEqual(self.device.write_count, 0)
        self.assertFalse((self.root / writer.LATCH_NAME).exists())

    def test_single_hash_write_and_all_preservation_checks(self):
        self.assertEqual(self.execute(), "HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID")
        self.assertEqual(self.device.write_count, 1)
        self.assertTrue((self.root / writer.LATCH_NAME).exists())
        self.assertEqual(len([c for c in self.device.calls if c[0] == "flash"]), 3)
        self.assertIn(("rows", writer.TARGETS, True), self.device.calls)
        final = json.loads(next(self.run.glob("*-HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID.json")).read_text())
        self.assertTrue(final["write_may_have_occurred"])
        self.assertFalse(final["more_programming_authorized"])
        self.assertEqual(final["control_writes"], [])
        self.assertEqual(final["secret_writes"], [])
        self.assertEqual((self.run / "slot0-hash.ecc.bin").stat().st_mode & 0o777, 0o400)

    def test_latched_success_cannot_be_replayed(self):
        self.execute()
        calls = len(self.device.calls)
        self.run = self.root / "second"
        self.run.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(len(self.device.calls), calls)
        self.assertEqual(self.device.write_count, 1)

    def test_wrong_board_stops_before_any_storage_read(self):
        self.device.bad_identity = True
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.device.calls, [("identity",)])
        self.assertEqual(self.device.write_count, 0)

    def test_nonblank_target_spare_or_secret_and_changed_policy_stop(self):
        for i, row in enumerate((0x80, 0x90, 0x740, 0x7ff, 0x40, 0x4b, 0xf85)):
            self.run = self.root / f"bad-{i}"
            self.run.mkdir(mode=0o700)
            self.device = SimulatedDevice(self.plan)
            self.device.raw_overrides[row] = 1
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.execute()
            self.assertEqual(self.device.write_count, 0)
            self.assertFalse((self.root / writer.LATCH_NAME).exists())

    def test_unknown_flash_prevents_write(self):
        self.device.bad_flash = True
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.device.write_count, 0)

    def test_cancel_and_input_mutation_prevent_write(self):
        self.confirm = lambda plan: "wrong confirmation"
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.device.write_count, 0)
        self.run = self.root / "input-change"
        self.run.mkdir(mode=0o700)
        self.confirm = lambda plan: writer.CONFIRMATION
        self.reload = lambda: {**self.plan, "review_sha256": "d" * 64}
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.device.write_count, 0)

    def test_confirmation_eof_records_stop_without_writing(self):
        def confirm(plan):
            raise EOFError()
        self.confirm = confirm
        with self.assertRaises(EOFError):
            self.execute()
        self.assertEqual(self.device.write_count, 0)
        self.assertFalse((self.root / writer.LATCH_NAME).exists())
        self.assertTrue(list(self.run.glob("*-STOP_BEFORE_WRITE.json")))

    def test_device_changes_during_confirmation_are_rechecked(self):
        def confirm(plan):
            self.device.raw_overrides[0x80] = 1
            return writer.CONFIRMATION
        self.confirm = confirm
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.device.write_count, 0)

    def test_payload_change_during_confirmation_is_rejected(self):
        def confirm(plan):
            frozen = self.run / "slot0-hash.ecc.bin"
            frozen.chmod(0o600)
            frozen.write_bytes(b"x" * 32)
            return writer.CONFIRMATION
        self.confirm = confirm
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.device.write_count, 0)

    def test_stale_final_preflight_latches_but_never_writes(self):
        with patch.object(writer, "freshness_clock", side_effect=[0, 0, 0, 0, 11]):
            with self.assertRaisesRegex(ValueError, "stale"):
                self.execute()
        self.assertEqual(self.device.write_count, 0)
        self.assertTrue((self.root / writer.LATCH_NAME).exists())

    def test_latch_sync_failure_prevents_write(self):
        real_sync = writer.sync_directory
        def fail(path):
            if path == self.root:
                raise OSError("latch directory sync failure")
            return real_sync(path)
        with patch.object(writer, "sync_directory", side_effect=fail), self.assertRaises(OSError):
            self.execute()
        self.assertTrue((self.root / writer.LATCH_NAME).exists())
        self.assertEqual(self.device.write_count, 0)

    def test_write_failure_or_interrupt_retains_latch_without_retry(self):
        self.device.write_failure = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.execute()
        self.assertEqual(self.device.write_count, 1)
        self.assertTrue((self.root / writer.LATCH_NAME).exists())
        self.assertTrue(list(self.run.glob("*-STOP_WRITE_STATE_UNCERTAIN.json")))
        self.assertFalse(list(self.run.glob("*-HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID.json")))

    def test_postwrite_raw_policy_secret_ecc_and_flash_failures_hold(self):
        for i, kind in enumerate(("raw", "policy", "secret", "ecc", "flash")):
            with tempfile.TemporaryDirectory(dir=self.root) as d:
                root = Path(d)
                run = root / "run"
                run.mkdir(mode=0o700)
                device = SimulatedDevice(self.plan)
                def corrupt():
                    if kind == "ecc": device.bad_ecc = True
                    elif kind == "flash": device.bad_flash = True
                    else: device.raw_overrides[{"raw": 0x80, "policy": 0x4b, "secret": 0x740}[kind]] = 1
                device.after_write = corrupt
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    writer.execute(device, self.plan, run, root, True, self.confirm, self.reload)
                self.assertEqual(device.write_count, 1)
                self.assertTrue((root / writer.LATCH_NAME).exists())
                self.assertFalse(list(run.glob("*-HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID.json")))

    def test_state_root_parent_sync_failure_prevents_native_access(self):
        state = self.root / "state"
        with patch.object(writer, "STATE_ROOT", state), \
             patch.object(writer.backup, "local_base", return_value=self.root), \
             patch.object(writer, "sync_directory", side_effect=OSError("parent sync failed")) as sync, \
             patch.object(writer, "NativeDevice") as native, self.assertRaises(OSError):
            writer.live(self.tool, self.plan, True)
        sync.assert_called_once_with(self.root)
        native.assert_not_called()

    def test_armed_state_is_durable_before_program_entry(self):
        def inspect():
            armed = next(self.run.glob("*-ARMED_WRITE_STATE_UNCERTAIN.json"))
            self.assertTrue(json.loads(armed.read_text())["write_may_have_occurred"])
        self.device.after_write = inspect
        self.execute()

    def test_exclusive_lease_blocks_concurrent_native_access(self):
        path = self.root / writer.LOCK_NAME
        with path.open("w") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(writer, "STATE_ROOT", self.root), \
                 patch.object(writer.backup, "local_base", return_value=self.root), \
                 patch.object(writer, "NativeDevice") as native, self.assertRaises(BlockingIOError):
                writer.live(self.tool, self.plan, True)
            native.assert_not_called()

    def test_offline_cli_never_constructs_native_transport(self):
        with patch.object(writer.sys, "argv", ["writer", "--offline-check", "--picotool", str(self.tool)]), \
             patch.object(writer, "load_plan", return_value=self.plan), \
             patch.object(writer, "NativeDevice") as native, \
             patch.object(writer, "live") as live, patch.object(writer.sys, "stdout", io.StringIO()):
            self.assertEqual(writer.main(), 0)
            native.assert_not_called()
            live.assert_not_called()

    def test_program_requires_ack_and_all_three_terminal_streams(self):
        for ack in ([], ["--ack-backup-restored"]):
            with patch.object(writer.sys, "argv", ["writer", "--program-hash-only", *ack]), \
                 patch.object(writer.sys.stdin, "isatty", return_value=False), \
                 patch.object(writer, "load_plan") as load, \
                 patch.object(writer, "live") as live, patch.object(writer.sys, "stderr", io.StringIO()):
                self.assertEqual(writer.main(), 1)
                load.assert_not_called()
                live.assert_not_called()


class NativeCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-command-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tool = self.root / "tool"
        self.tool.write_bytes(b"never executed")
        self.plan = plan_for(self.tool)
        self.native = writer.NativeDevice(self.tool, self.plan)
        self.payload = self.root / "payload.bin"
        self.payload.write_bytes(self.plan["payload"])
        self.payload.chmod(0o600)

    def test_exact_single_ecc_write_command(self):
        def run_command(command, **kwargs):
            self.assertEqual(command[:6], [str(self.tool), "otp", "load", "--ecc", "--start_row", "0x0080"])
            self.assertEqual(command[7:], ["-t", "bin", "--ser", writer.otp_policy.SERIAL])
            self.assertTrue(command[6].startswith("/proc/self/fd/"))
            self.assertEqual(Path(command[6]).read_bytes(), self.plan["payload"])
            self.assertEqual(Path(kwargs["executable"]).read_bytes(), self.tool.read_bytes())
            self.assertEqual(len(kwargs["pass_fds"]), 2)
            self.assertIsNone(kwargs["timeout"])
            return subprocess.CompletedProcess([], 0, b"  Verified OK\n", b"")
        with patch.object(writer.subprocess, "run", side_effect=run_command) as run:
            self.native.program(self.payload, writer.freshness_clock() + 10)
            with self.assertRaises(ValueError):
                self.native.program(self.payload, writer.freshness_clock() + 10)
            run.assert_called_once()

    def test_exit_zero_mismatch_and_stderr_are_failures(self):
        for stdout, stderr in ((b"Mismatch at row 0\n", b""), (b"", b""),
                               (b"Verified OK\n", b"unexpected warning")):
            native = writer.NativeDevice(self.tool, self.plan)
            with patch.object(writer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout, stderr)), \
                 self.assertRaises(ValueError):
                native.program(self.payload, writer.freshness_clock() + 10)
            self.assertTrue(native.write_called)

    def test_wrong_payload_or_tool_hash_cannot_reach_native_command(self):
        self.payload.write_bytes(b"x" * 32)
        with patch.object(writer.subprocess, "run") as run, self.assertRaises(ValueError):
            self.native.program(self.payload, writer.freshness_clock() + 10)
        run.assert_not_called()
        self.payload.write_bytes(self.plan["payload"])
        self.tool.write_bytes(b"changed tool")
        native = writer.NativeDevice(self.tool, self.plan)
        with patch.object(writer.subprocess, "run") as run, self.assertRaises(ValueError):
            native.program(self.payload, writer.freshness_clock() + 10)
        run.assert_not_called()

    def test_raw_option_order_serial_and_selector_scope(self):
        result = subprocess.CompletedProcess([], 0, b"ROW 0x0080\nVALUE 0x000000\n", b"")
        with patch.object(writer.subprocess, "run", return_value=result) as run:
            self.native.rows((0x80,))
            self.assertEqual(run.call_args.args[0], [str(self.tool), "otp", "get", "-c", "1", "-r", "-n",
                                                    "--ser", writer.otp_policy.SERIAL, "0x0080"])
        for rows, ecc in (((), False), ((0x80, 0x80), False), ((0x81,), True), ((0x100,), False)):
            with patch.object(writer.subprocess, "run") as run, self.assertRaises(ValueError):
                self.native.rows(rows, ecc)
            run.assert_not_called()

    def test_identity_stdout_warning_is_rejected(self):
        text = "\n".join(f"{k}: {v}" for k, v in writer.IDENTITY.items()) + "\nWARNING: partition table unavailable\n"
        with patch.object(writer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, text.encode(), b"")), \
             self.assertRaises(ValueError):
            self.native.identity()

    def test_late_path_replacement_cannot_change_child_inputs(self):
        original_tool = self.tool.read_bytes()
        def run_command(command, **kwargs):
            self.payload.write_bytes(b"enlarged replacement" * 32)
            self.tool.write_bytes(b"different executable")
            self.assertEqual(Path(command[6]).read_bytes(), self.plan["payload"])
            self.assertEqual(Path(kwargs["executable"]).read_bytes(), original_tool)
            for fd in kwargs["pass_fds"]:
                with self.assertRaises(OSError):
                    os.pwrite(fd, b"x", 0)
                with self.assertRaises(OSError):
                    os.ftruncate(fd, 1)
            return subprocess.CompletedProcess([], 0, b"Verified OK\n", b"")
        with patch.object(writer.subprocess, "run", side_effect=run_command):
            self.native.program(self.payload, writer.freshness_clock() + 10)

    def test_transport_preparation_delay_expires_deadline_before_spawn(self):
        clock = [0]
        real_seal = writer.sealed_file
        @contextmanager
        def delayed(*args, **kwargs):
            with real_seal(*args, **kwargs) as handle:
                if kwargs.get("executable"):
                    clock[0] = 11
                yield handle
        with patch.object(writer, "sealed_file", side_effect=delayed), \
             patch.object(writer, "freshness_clock", side_effect=lambda: clock[0]), \
             patch.object(writer.subprocess, "run") as run, self.assertRaisesRegex(ValueError, "expired"):
            self.native.program(self.payload, 10)
        run.assert_not_called()

    def test_missing_or_wrong_serial_cannot_spawn(self):
        for args in (["info", "--debug"], ["info", "--ser", "wrong"],
                     ["info", "--ser", writer.otp_policy.SERIAL, "--ser", writer.otp_policy.SERIAL]):
            with patch.object(writer.subprocess, "run") as run, self.assertRaises(ValueError):
                self.native._invoke(args)
            run.assert_not_called()

    def test_full_flash_save_command_and_positive_check(self):
        destination = self.root / "flash.bin"
        def save(command, **kwargs):
            self.assertEqual(command, [str(self.tool), "save", "-r", "0x10000000", "0x10200000", "-v",
                                       str(destination), "-t", "bin", "--ser", writer.otp_policy.SERIAL])
            destination.write_bytes(FLASH)
            destination.chmod(0o600)
            return subprocess.CompletedProcess([], 0, b"Saving ...\nVerifying ...\n  OK\n", b"")
        with patch.object(writer.subprocess, "run", side_effect=save):
            self.assertEqual(self.native.flash(destination), self.plan["flash_sha256"])
        with patch.object(writer.subprocess, "run") as run, self.assertRaises(ValueError):
            self.native.flash(destination)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
