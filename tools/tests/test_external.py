from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import chalbundle  # noqa: E402
import validate as validator  # noqa: E402


def load_generate_module():
    spec = importlib.util.spec_from_file_location(
        "noco_generate_external", ROOT / "deploy" / "chals" / "generate.py")
    if spec is None or spec.loader is None:
        raise AssertionError("generate.py must be loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(name: str, flag: str, *, state: str = "hidden", version: str = "0.1",
             x_noco: dict, value: int = 100, tags: list[str] | None = None,
             hints: list[dict] | None = None) -> str:
    return yaml.safe_dump({
        "name": name,
        "author": "tester",
        "category": "ai",
        "description": "fixture",
        "value": value,
        "type": "standard",
        "version": version,
        "flags": [flag],
        "tags": tags or ["ai"],
        "hints": hints or [{"content": "hint", "cost": 0}],
        "files": [],
        "state": state,
        "x-noco": x_noco,
    }, sort_keys=False)


class ExternalSupportTests(unittest.TestCase):
    def test_live_selection_and_awards_are_bound_to_the_same_snapshot(self):
        import external
        self.assertTrue(hasattr(external, "validate_live_selection"))
        self.assertTrue(hasattr(external, "validate_live_award"))
        self.write_external_bundle(entry_ids=("rook",))
        bundle = self.load_bundle()
        old_flag = bundle.primary.flag
        data = yaml.safe_load((self.bundle_dir / "challenge.yml").read_text())
        data["flags"] = ["noco{changed_before_snapshot}"]
        (self.bundle_dir / "challenge.yml").write_text(yaml.safe_dump(data))
        current = self.load_bundle()
        snapshot = external.live_snapshot(current)
        self.assertTrue(external.validate_live_selection(snapshot, ["main"]))
        self.assertFalse(external.validate_live_selection(snapshot, ["main", "rook"]))
        self.assertTrue(external.validate_live_award(snapshot, "main", old_flag))
        self.assertFalse(external.validate_live_award(snapshot, "main", current.primary.flag))
        self.assertTrue(external.validate_live_award(snapshot, "unknown", current.primary.flag))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".external-test-", dir=ROOT)
        self.root = Path(self.temp.name).resolve()
        self.bundle_dir = self.root / "challenges" / "ai" / "external-fixture"
        self.bundle_dir.mkdir(parents=True)
        self.project_tmp = self.root / "project-tmp"
        self.project_tmp.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_external_bundle(self, *, state: str = "hidden", url: str = "https://example.test",
                              extra_primary: dict | None = None, entry_ids: tuple[str, ...] = (),
                              versions: dict[str, str] | None = None) -> None:
        versions = versions or {}
        if self.bundle_dir.exists():
            for path in sorted(self.bundle_dir.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            self.bundle_dir.mkdir(parents=True, exist_ok=True)
        primary_x = {"kind": "external", "url": url, "autosolve": "solution/solve.sh"}
        if extra_primary:
            primary_x.update(extra_primary)
        (self.bundle_dir / "challenge.yml").write_text(manifest(
            "External Main", "noco{fixture_main}", state=state,
            version=versions.get("main", "0.1"), x_noco=primary_x))
        for entry_id in entry_ids:
            (self.bundle_dir / f"challenge.{entry_id}.yml").write_text(manifest(
                f"External {entry_id}", f"noco{{fixture_{entry_id}}}", state=state,
                version=versions.get(entry_id, "0.1"),
                x_noco={"autosolve": f"solution/solve-{entry_id}.sh"},
                value=200 if entry_id == "rook" else 300))
        solution = self.bundle_dir / "solution"
        solution.mkdir()
        (solution / "writeup.md").write_text("fixture\n")

    def add_external_solvers(self, *, overrides: dict[str, str] | None = None) -> None:
        overrides = overrides or {}
        scripts = {"main": "challenge.yml"}
        for path in self.bundle_dir.glob("challenge.*.yml"):
            entry_id = path.stem.split(".", 1)[1]
            scripts[entry_id] = path.name
        for entry_id, manifest_name in scripts.items():
            name = "solve.sh" if entry_id == "main" else f"solve-{entry_id}.sh"
            body = overrides.get(entry_id, f"""#!/usr/bin/env bash
set -euo pipefail
[[ "${{NOCO_EXTERNAL_LIVE:-}}" == "1" ]] || {{ echo "need live opt-in" >&2; exit 2; }}
[[ -n "${{TARGET:-}}" ]] || {{ echo "missing TARGET" >&2; exit 2; }}
python3 -c 'import yaml; print(yaml.safe_load(open("{manifest_name}"))["flags"][0])'
""")
            solve = self.bundle_dir / "solution" / name
            solve.write_text(body)
            solve.chmod(0o755)

    def add_contract_tests(self, body: str | None = None) -> None:
        tests_dir = self.bundle_dir / "solution" / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_body = body or """
import os
import unittest
from pathlib import Path


class ContractTests(unittest.TestCase):
    def test_offline_contract_only(self):
        self.assertNotEqual(os.getenv("NOCO_EXTERNAL_LIVE"), "1")
        marker = Path(__file__).resolve().parents[2] / "solver-ran.txt"
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
"""
        (tests_dir / "test_contract.py").write_text(textwrap.dedent(test_body).lstrip())

    def load_bundle(self):
        return chalbundle.load_bundle(self.bundle_dir)

    def validate_bundle(self) -> tuple[list[dict], list[str]]:
        report = validator.Report()
        old_root = validator.ROOT
        try:
            validator.ROOT = self.root
            loaded = validator.check_bundle(self.bundle_dir, report)
        finally:
            validator.ROOT = old_root
        return loaded, report.errors

    def run_chalbundle_env(self, bundle) -> str:
        stdout = io.StringIO()
        with patch.object(chalbundle, "discover_bundles", return_value=[bundle]), \
                patch.object(sys, "argv", ["chalbundle.py", "env"]), \
                contextlib.redirect_stdout(stdout):
            rc = chalbundle.main()
        self.assertEqual(rc, 0)
        return stdout.getvalue()

    def run_test_challenge(self, *, live: bool = False) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, TMPDIR=str(self.project_tmp))
        if live:
            env["NOCO_EXTERNAL_LIVE"] = "1"
        else:
            env.pop("NOCO_EXTERNAL_LIVE", None)
        return subprocess.run(
            [str(ROOT / "tools" / "test-challenge.sh"), str(self.bundle_dir)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def run_sync_fixture(self, *, state: str | None, with_receipt: bool = False) -> tuple[
            subprocess.CompletedProcess[str], Path, Path]:
        fixture_root = self.root / "sync-fixture"
        for directory in (
            fixture_root / "deploy" / "scoreboard",
            fixture_root / "tools",
            fixture_root / "bin",
            fixture_root / "challenges" / "ai" / "external-fixture",
        ):
            directory.mkdir(parents=True, exist_ok=True)

        for relative in (
            "deploy/scoreboard/sync.sh",
            "tools/chalbundle.py",
            "tools/chalmeta.py",
            "tools/external.py",
        ):
            source = ROOT / relative
            target = fixture_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        config_log = fixture_root / "config.log"
        (fixture_root / "tools" / "ctfd-config.py").write_text(textwrap.dedent(f"""
            #!/usr/bin/env python3
            from pathlib import Path
            Path({str(config_log)!r}).write_text("called\\n", encoding="utf-8")
        """).lstrip())
        (fixture_root / "tools" / "ctfd-config.py").chmod(0o755)

        ctf_log = fixture_root / "ctf.log"
        (fixture_root / "bin" / "ctf").write_text(textwrap.dedent(f"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\\n' "$*" >> {str(ctf_log)!r}
            printf 'Syncing existing challenge\\n'
        """).lstrip())
        (fixture_root / "bin" / "ctf").chmod(0o755)

        self.write_external_bundle(state="hidden" if state is None else state, entry_ids=("rook",))
        if state is None:
            for filename in ("challenge.yml", "challenge.rook.yml"):
                path = self.bundle_dir / filename
                data = yaml.safe_load(path.read_text())
                data.pop("state", None)
                path.write_text(yaml.safe_dump(data, sort_keys=False))
        shutil.copytree(self.bundle_dir, fixture_root / "challenges" / "ai" / "external-fixture",
                        dirs_exist_ok=True)
        if with_receipt:
            import external  # noqa: E402
            bundle = chalbundle.load_bundle(fixture_root / "challenges" / "ai" / "external-fixture")
            external.write_receipt(bundle, verified_at="2026-10-03T19:00:00Z")

        env = {
            **os.environ,
            "PATH": f"{fixture_root / 'bin'}:{os.environ['PATH']}",
            "CTFCLI_ACCESS_TOKEN": "fixture-token",
            "TMPDIR": str(self.project_tmp),
        }
        result = subprocess.run(
            [str(fixture_root / "deploy" / "scoreboard" / "sync.sh"), "--dev", "--dry-run",
             "-c", "challenges/ai/external-fixture"],
            cwd=fixture_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result, ctf_log, config_log

    def test_validator_rejects_invalid_external_origins_and_local_fields(self):
        self.write_external_bundle()
        self.add_external_solvers()
        invalid_urls = {
            "http://example.test": "must use https",
            "https://user:pass@example.test": "must not include credentials",
            "https://example.test/live": "must be the root origin",
            "https://example.test?token=secret": "must not include a query string",
            "https://example.test#fragment": "must not include a fragment",
            "https://example.test:444": "must not include an explicit port",
        }
        for url, message in invalid_urls.items():
            with self.subTest(url=url):
                self.write_external_bundle(url=url, extra_primary={"memory": "512m"})
                self.add_external_solvers()
                _loaded, errors = self.validate_bundle()
                self.assertTrue(any(message in item for item in errors), errors)
                self.assertTrue(any("must not declare local container fields" in item
                                    for item in errors), errors)

    def test_external_bundles_need_no_docker_and_are_skipped_by_env_and_generator(self):
        self.write_external_bundle(entry_ids=("rook",))
        self.add_external_solvers()
        loaded, errors = self.validate_bundle()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(errors, [])

        bundle = self.load_bundle()
        self.assertEqual(self.run_chalbundle_env(bundle), "")

        generate = load_generate_module()
        self.assertIsNone(generate.build_service(bundle, generate.PROD))

    def test_visible_external_entries_require_a_matching_receipt(self):
        self.write_external_bundle(state="hidden", entry_ids=("rook",))
        self.add_external_solvers()
        import external  # noqa: E402

        _loaded, errors = self.validate_bundle()
        self.assertEqual(errors, [])

        self.write_external_bundle(state="visible", entry_ids=("rook",))
        self.add_external_solvers()
        _loaded, errors = self.validate_bundle()
        self.assertTrue(any("verification.json" in item for item in errors), errors)

        bundle = self.load_bundle()
        external.write_receipt(bundle, verified_at="2026-10-03T19:00:00Z")
        loaded, errors = self.validate_bundle()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(errors, [])

    def test_missing_or_null_state_still_requires_receipt(self):
        self.write_external_bundle(state="hidden", entry_ids=("rook",))
        self.add_external_solvers()

        for filename, value in (("challenge.yml", None), ("challenge.rook.yml", "remove")):
            path = self.bundle_dir / filename
            data = yaml.safe_load(path.read_text())
            if value == "remove":
                data.pop("state", None)
            else:
                data["state"] = value
            path.write_text(yaml.safe_dump(data, sort_keys=False))

        _loaded, errors = self.validate_bundle()
        self.assertTrue(any("verification.json is required" in item for item in errors), errors)

    def test_receipt_ignores_value_hint_tag_and_state_edits_but_detects_version_changes(self):
        self.write_external_bundle(state="hidden", entry_ids=("rook",), versions={
            "main": "1.0",
            "rook": "1.1",
        })
        self.add_external_solvers()
        import external  # noqa: E402

        bundle = self.load_bundle()
        external.write_receipt(bundle, verified_at="2026-10-03T19:00:00Z")

        for filename in ("challenge.yml", "challenge.rook.yml"):
            path = self.bundle_dir / filename
            data = yaml.safe_load(path.read_text())
            data["value"] += 100
            data["hints"].append({"content": "new hint", "cost": 0})
            data["tags"].append("updated")
            data["state"] = "visible"
            path.write_text(yaml.safe_dump(data, sort_keys=False))

        _loaded, errors = self.validate_bundle()
        self.assertEqual(errors, [])

        data = yaml.safe_load((self.bundle_dir / "challenge.rook.yml").read_text())
        data["version"] = "2.0"
        (self.bundle_dir / "challenge.rook.yml").write_text(yaml.safe_dump(data, sort_keys=False))
        _loaded, errors = self.validate_bundle()
        self.assertTrue(any("metadata fingerprint mismatch" in item for item in errors), errors)

    def test_normalize_origin_rejects_userinfo_whitespace_and_malformed_hosts(self):
        import external  # noqa: E402

        invalid = {
            "https://@example.test": "must not include credentials",
            " https://example.test": "must not contain whitespace or control characters",
            "https://example.test\t": "must not contain whitespace or control characters",
            "https://example.test/\n": "must not contain whitespace or control characters",
            "https://[::1": "is malformed",
            "https://[2001:db8::1%25eth0]": "must not include a scoped IPv6 host",
        }
        for url, message in invalid.items():
            with self.subTest(url=url), self.assertRaisesRegex(external.ExternalError, message):
                external.normalize_origin(url)

        self.assertEqual(external.normalize_origin("https://[2001:db8::1]"),
                         "https://[2001:db8::1]")

    def test_invalid_receipt_bytes_and_json_fail_closed_without_traceback(self):
        self.write_external_bundle(state="visible")
        self.add_external_solvers()

        receipt = self.bundle_dir / "verification.json"
        receipt.write_bytes(b"\xff")
        _loaded, errors = self.validate_bundle()
        self.assertTrue(any("verification.json is invalid" in item for item in errors), errors)
        self.assertFalse(any("Traceback" in item for item in errors), errors)

        receipt.write_text("{not json}\n")
        _loaded, errors = self.validate_bundle()
        self.assertTrue(any("verification.json is invalid" in item for item in errors), errors)
        self.assertFalse(any("Traceback" in item for item in errors), errors)

    def test_offline_external_checks_run_contract_tests_only(self):
        self.write_external_bundle(entry_ids=("rook",))
        self.add_external_solvers(overrides={
            "main": """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' main >> solver-ran.txt
exit 99
""",
            "rook": """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' rook >> solver-ran.txt
exit 99
""",
        })
        self.add_contract_tests()

        result = self.run_test_challenge()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("offline contract only, live solve not attempted", result.stdout)
        self.assertNotIn("PASS", result.stdout)
        self.assertFalse((self.bundle_dir / "solver-ran.txt").exists())
        self.assertFalse((self.bundle_dir / "verification.json").exists())

    def test_live_external_rejects_mid_run_metadata_changes_before_writing_receipt(self):
        self.write_external_bundle(entry_ids=("rook",))
        self.add_contract_tests()
        for mutation in ("flag", "entry-set"):
            with self.subTest(mutation=mutation):
                self.write_external_bundle(entry_ids=("rook",))
                if mutation == "flag":
                    self.add_external_solvers(overrides={
                        "main": """#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import yaml
path = Path("challenge.rook.yml")
data = yaml.safe_load(path.read_text())
data["flags"] = ["noco{mutated_rook}"]
path.write_text(yaml.safe_dump(data, sort_keys=False))
PY
python3 -c 'import yaml; print(yaml.safe_load(open("challenge.yml"))["flags"][0])'
""",
                    })
                else:
                    self.add_external_solvers(overrides={
                        "main": """#!/usr/bin/env bash
set -euo pipefail
cat > challenge.vera.yml <<'YML'
name: External vera
author: tester
category: ai
description: fixture
value: 300
type: standard
version: "0.1"
flags:
  - noco{fixture_vera}
tags: [ai]
hints:
  - content: hint
    cost: 0
files: []
state: hidden
x-noco:
  autosolve: solution/solve-vera.sh
YML
python3 -c 'import yaml; print(yaml.safe_load(open("challenge.yml"))["flags"][0])'
""",
                    })
                result = self.run_test_challenge(live=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("metadata changed during live verification",
                              result.stderr + result.stdout)
                self.assertFalse((self.bundle_dir / "verification.json").exists())

    def test_offline_external_checks_fail_without_any_contract_tests(self):
        self.write_external_bundle()
        self.add_external_solvers()
        (self.bundle_dir / "solution" / "tests").mkdir()

        result = self.run_test_challenge()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must define at least one unittest", result.stderr + result.stdout)
        self.assertFalse((self.bundle_dir / "verification.json").exists())

    def test_external_cli_cannot_fabricate_receipts(self):
        self.write_external_bundle()
        self.add_external_solvers()

        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "external.py"), "write-receipt",
             str(self.bundle_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.bundle_dir / "verification.json").exists())

    def test_live_external_checks_write_receipt_only_after_all_solvers_pass(self):
        self.write_external_bundle(entry_ids=("rook", "vera"))
        self.add_external_solvers()
        self.add_contract_tests()

        result = self.run_test_challenge(live=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("wrote verification.json", result.stdout)

        import external  # noqa: E402
        bundle = self.load_bundle()
        receipt = external.load_receipt(self.bundle_dir / "verification.json")
        self.assertEqual(receipt["origin"], "https://example.test")
        self.assertEqual([entry["id"] for entry in receipt["entries"]], ["main", "rook", "vera"])
        self.assertFalse(any("noco{" in str(value) for value in receipt["entries"]))
        self.assertEqual(external.validate_receipt(bundle), [])

    def test_live_external_failures_do_not_refresh_receipts_or_leak_flags(self):
        self.write_external_bundle(state="visible", entry_ids=("rook",))
        self.add_external_solvers(overrides={
            "rook": """#!/usr/bin/env bash
set -euo pipefail
[[ "${NOCO_EXTERNAL_LIVE:-}" == "1" ]]
printf '%s\n' 'noco{wrong_flag}'
""",
        })
        self.add_contract_tests()

        import external  # noqa: E402
        bundle = self.load_bundle()
        external.write_receipt(bundle, verified_at="2026-10-03T18:00:00Z")
        original = (self.bundle_dir / "verification.json").read_text()

        result = self.run_test_challenge(live=True)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("did not return its declared flag", combined)
        self.assertNotIn("noco{fixture_rook}", combined)
        self.assertNotIn("noco{wrong_flag}", combined)
        self.assertEqual((self.bundle_dir / "verification.json").read_text(), original)
        self.assertFalse((self.bundle_dir / "verification.json.tmp").exists())

    def test_domain_consistency_exempts_declared_external_origin_only(self):
        data = yaml.safe_load(manifest(
            "External Main", "noco{fixture_main}", x_noco={
                "kind": "external",
                "url": "https://approved.example.test",
                "autosolve": "solution/solve.sh",
            }))
        data["description"] = ("visit https://approved.example.test for play and "
                                "https://mistyped.example.net for a typo")
        (self.bundle_dir / "challenge.yml").write_text(yaml.safe_dump(data, sort_keys=False))
        (self.bundle_dir / "solution").mkdir()
        (self.bundle_dir / "solution" / "writeup.md").write_text("fixture\n")
        solve = self.bundle_dir / "solution" / "solve.sh"
        solve.write_text("#!/bin/sh\npython3 -c 'import yaml; print(yaml.safe_load(open(\"challenge.yml\"))[\"flags\"][0])'\n")
        solve.chmod(0o755)

        report = validator.Report()
        old_root = validator.ROOT
        try:
            validator.ROOT = self.root
            validator.check_domain_consistency(report, [self.bundle_dir])
        finally:
            validator.ROOT = old_root

        self.assertTrue(any("mistyped.example.net" in item for item in report.warnings),
                        report.warnings)
        self.assertFalse(any("approved.example.test" in item for item in report.warnings),
                         report.warnings)

    def test_sync_preflight_blocks_visible_external_without_receipt(self):
        result, ctf_log, config_log = self.run_sync_fixture(state=None, with_receipt=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verification.json is required", result.stderr + result.stdout)
        self.assertFalse(ctf_log.exists())
        self.assertFalse(config_log.exists())

    def test_sync_preflight_allows_hidden_external_without_receipt(self):
        result, ctf_log, config_log = self.run_sync_fixture(state="hidden", with_receipt=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(ctf_log.exists())
        self.assertIn("challenge install --force -c challenges/ai/external-fixture/challenge.yml",
                      ctf_log.read_text())
        self.assertTrue(config_log.exists())

    def test_ci_autosolve_explicitly_disables_live_external_verification(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn('NOCO_EXTERNAL_LIVE: "0"', workflow)


if __name__ == "__main__":
    unittest.main()
