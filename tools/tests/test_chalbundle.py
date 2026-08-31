from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
import sys
sys.path.insert(0, str(TOOLS))

from chalbundle import (  # noqa: E402
    BundleError,
    container_flag_var,
    discover_bundle_dirs,
    host_flag_var,
    load_bundle,
    lock_key,
    selected_manifests,
)
import validate as validator  # noqa: E402


def manifest(name: str, flag: str, x: dict) -> str:
    return yaml.safe_dump({
        "name": name,
        "author": "tester",
        "category": "misc",
        "description": "fixture",
        "value": 100,
        "flags": [flag],
        "files": [],
        "state": "hidden",
        "x-noco": x,
    }, sort_keys=False)


class ChallengeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / "challenges" / "misc" / "device"
        self.directory.mkdir(parents=True)
        (self.directory / "challenge.yml").write_text(manifest(
            "Device: Main", "noco{fixture_main}", {"kind": "web", "subdomain": "device"}))

    def tearDown(self):
        self.temp.cleanup()

    def add_entry(self, entry_id="uart"):
        path = self.directory / f"challenge.{entry_id}.yml"
        path.write_text(manifest(
            f"Device: {entry_id}", f"noco{{fixture_{entry_id}}}",
            {"autosolve": f"solution/solve-{entry_id}.sh"}))
        return path

    def test_loads_primary_first_and_derives_stable_names(self):
        self.add_entry("uart")
        self.add_entry("firmware-dump")
        bundle = load_bundle(self.directory)

        self.assertEqual([entry.id for entry in bundle.entries],
                         ["main", "firmware-dump", "uart"])
        self.assertEqual(host_flag_var(bundle, bundle.primary), "FLAG_MISC_DEVICE")
        self.assertEqual(host_flag_var(bundle, bundle.entries[1]),
                         "FLAG_MISC_DEVICE__ENTRY_FIRMWARE_DUMP")
        self.assertEqual(container_flag_var(bundle.entries[1]),
                         "NOCO_FLAG_FIRMWARE_DUMP")
        self.assertEqual(lock_key(bundle, bundle.primary, self.root),
                         "challenges/misc/device")
        self.assertEqual(lock_key(bundle, bundle.entries[2], self.root),
                         "challenges/misc/device#uart")

    def test_discovery_ignores_nested_challenge_named_source_files(self):
        nested = self.directory / "src" / "challenge.notes.yml"
        nested.parent.mkdir()
        nested.write_text("this: is source data\n")
        self.assertEqual(discover_bundle_dirs(self.root / "challenges"),
                         [self.directory.resolve()])

    def test_host_variables_cannot_collide_with_another_primary_bundle(self):
        self.add_entry("uart")
        bundle = load_bundle(self.directory)
        other_dir = self.root / "challenges" / "misc" / "device-uart"
        other_dir.mkdir()
        (other_dir / "challenge.yml").write_text(manifest(
            "Other", "noco{fixture_other}", {"kind": "static"}))
        other = load_bundle(other_dir)
        self.assertNotEqual(host_flag_var(bundle, bundle.entries[1]),
                            host_flag_var(other, other.primary))
        self.assertEqual(host_flag_var(bundle, bundle.entries[1]),
                         "FLAG_MISC_DEVICE__ENTRY_UART")
        self.assertEqual(host_flag_var(other, other.primary), "FLAG_MISC_DEVICE_UART")

    def test_validator_rejects_any_computed_host_variable_collision(self):
        self.add_entry("uart")
        bundle = load_bundle(self.directory)
        other_dir = self.root / "challenges" / "misc" / "device__entry-uart"
        other_dir.mkdir()
        (other_dir / "challenge.yml").write_text(manifest(
            "Other", "noco{fixture_other}", {"kind": "web", "subdomain": "other"}))
        other = load_bundle(other_dir)
        items = []
        for current in (bundle, other):
            for entry in current.entries:
                items.append({"bundle": current, "entry": entry, "data": entry.data,
                              "flags": [entry.flag], "x": current.x,
                              "primary": entry.primary})

        old_root = validator.ROOT
        try:
            validator.ROOT = self.root
            report = validator.Report()
            validator.check_collisions(items, report)
        finally:
            validator.ROOT = old_root
        self.assertTrue(any("runtime flag variable" in item for item in report.errors))

    def test_directory_and_explicit_manifest_selection(self):
        supplemental = self.add_entry("uart")
        self.assertEqual(selected_manifests(str(self.directory)),
                         [self.directory / "challenge.yml", supplemental])
        self.assertEqual(selected_manifests(str(supplemental)), [supplemental])

    def test_rejects_reserved_main_supplement(self):
        self.add_entry("main")
        with self.assertRaisesRegex(BundleError, "reserved"):
            load_bundle(self.directory)

    def test_rejects_non_kebab_manifest_name(self):
        (self.directory / "challenge.Bad_Name.yml").write_text("name: bad\n")
        with self.assertRaisesRegex(BundleError, "invalid manifest filename"):
            load_bundle(self.directory)

    def test_rejects_supplement_without_primary(self):
        (self.directory / "challenge.yml").unlink()
        self.add_entry()
        with self.assertRaisesRegex(BundleError, "no challenge.yml"):
            load_bundle(self.directory)

    def test_malformed_flag_and_autosolve_report_errors_without_traceback(self):
        data = yaml.safe_load((self.directory / "challenge.yml").read_text())
        data["name"] = 42
        data["category"] = {"bad": "shape"}
        data["flags"] = {"bad": "shape"}
        data["files"] = 42
        data["x-noco"]["autosolve"] = []
        (self.directory / "challenge.yml").write_text(yaml.safe_dump(data, sort_keys=False))
        (self.directory / "Dockerfile").write_text("FROM scratch\n")
        (self.directory / "solution").mkdir()
        (self.directory / "solution" / "writeup.md").write_text("fixture\n")

        old_root = validator.ROOT
        try:
            validator.ROOT = self.root
            report = validator.Report()
            loaded = validator.check_bundle(self.directory, report)
        finally:
            validator.ROOT = old_root

        self.assertEqual(loaded[0]["entry"].flag, "")
        self.assertTrue(any("category" in item for item in report.errors))
        self.assertTrue(any("flags must be a list" in item for item in report.errors))
        self.assertTrue(any("files must be a list" in item for item in report.errors))
        self.assertTrue(any("autosolve must be a non-empty relative path" in item
                            for item in report.errors))

    def test_validator_restricts_supplement_and_scans_union_of_flags(self):
        entry = self.add_entry("uart")
        data = yaml.safe_load(entry.read_text())
        data["x-noco"]["kind"] = "tcp"
        entry.write_text(yaml.safe_dump(data, sort_keys=False))
        (self.directory / "Dockerfile").write_text("FROM scratch\n")
        (self.directory / "src").mkdir()
        (self.directory / "src" / "leak.txt").write_text("noco{fixture_uart}\n")
        (self.directory / "solution").mkdir()
        (self.directory / "solution" / "writeup.md").write_text(
            "fixture noco{fixture_uart}\n")
        for name in ("solve.sh", "solve-uart.sh"):
            solve = self.directory / "solution" / name
            solve.write_text("#!/bin/sh\n")
            solve.chmod(0o755)

        old_root = validator.ROOT
        try:
            validator.ROOT = self.root
            report = validator.Report()
            loaded = validator.check_bundle(self.directory, report)
        finally:
            validator.ROOT = old_root

        self.assertEqual(len(loaded), 2)
        self.assertTrue(any("may only contain autosolve" in item for item in report.errors))
        self.assertTrue(any("flag literal found in src/leak.txt" in item
                            for item in report.errors))
        self.assertTrue(any("flag literal found in solution/writeup.md" in item
                            for item in report.errors))

    def test_generator_preserves_legacy_env_and_adds_named_bundle_env(self):
        spec = importlib.util.spec_from_file_location(
            "noco_generate", ROOT / "deploy" / "chals" / "generate.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        single = load_bundle(self.directory)
        _, service = module.build_service(single, module.PROD)
        self.assertEqual(service["environment"], {
            "FLAG": "${FLAG_MISC_DEVICE:?missing flag}",
        })

        self.add_entry("uart")
        bundle = load_bundle(self.directory)
        _, service = module.build_service(bundle, module.PROD)
        self.assertEqual(service["environment"], {
            "FLAG": "${FLAG_MISC_DEVICE:?missing flag}",
            "NOCO_FLAG_MAIN": "${FLAG_MISC_DEVICE:?missing flag}",
            "NOCO_FLAG_UART": "${FLAG_MISC_DEVICE__ENTRY_UART:?missing flag}",
        })


if __name__ == "__main__":
    unittest.main()
