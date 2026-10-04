from __future__ import annotations

import contextlib
import importlib.util
import io
import os
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
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
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

    def test_offline_external_checks_fail_without_any_contract_tests(self):
        self.write_external_bundle()
        self.add_external_solvers()
        (self.bundle_dir / "solution" / "tests").mkdir()

        result = self.run_test_challenge()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must define at least one unittest", result.stderr + result.stdout)
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


if __name__ == "__main__":
    unittest.main()
