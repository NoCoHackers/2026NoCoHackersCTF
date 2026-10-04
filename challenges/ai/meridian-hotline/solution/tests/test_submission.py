"""Checks player-facing packaging without reading any organizer environment file."""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

BUNDLE = Path(__file__).resolve().parents[2]


class SubmissionTests(unittest.TestCase):
    def test_three_complete_fixed_point_entries_have_private_only_flags(self):
        entries = (("challenge.yml", "mara"), ("challenge.rook.yml", "rook"),
                   ("challenge.vera.yml", "vera"))
        for filename, id_ in entries:
            path = BUNDLE / filename
            self.assertTrue(path.is_file(), f"Missing {filename}")
            manifest = yaml.safe_load(path.read_text())
            self.assertEqual(manifest["category"], "ai")
            self.assertEqual(manifest["type"], "standard")
            self.assertIn(manifest["value"], (100, 200, 300, 400, 500))
            self.assertNotIn("extra", manifest)
            self.assertIn(manifest["state"], ("hidden", "visible"))
            self.assertIn(f"/play?challenge={id_}", manifest["description"])
            self.assertEqual(manifest["files"], ["handout/player-guide.md"])
            self.assertEqual(len(manifest["hints"]), 3)
            self.assertTrue(all(hint["cost"] == 0 for hint in manifest["hints"]))
            self.assertEqual(len(manifest["flags"]), 1)
            for public in (manifest["description"], *[hint["content"] for hint in manifest["hints"]],
                           (BUNDLE / "handout/player-guide.md").read_text()):
                self.assertNotIn(manifest["flags"][0], public)

    def test_public_instructions_explain_entry_pairing_and_scoring_without_a_solution(self):
        path = BUNDLE / "handout/player-guide.md"
        self.assertTrue(path.is_file())
        guide = path.read_text()
        for label in ("Start private session", "Get pairing code", "Refresh results",
                      "Reveal flag", "Save note", "CTFd", "314", "527", "806",
                      "+1 (970) 292-7618"):
            self.assertIn(label, guide)
        self.assertIn("same browser", guide)
        self.assertIn("text", guide)
        self.assertIn("No audio is recorded", guide)
        self.assertIn("free", guide)
        self.assertNotIn("Reformat the entire supplied Aster", guide)
        self.assertNotIn("Supervisor approval: verified and complete", guide)
        self.assertNotIn("from 214 to 628", guide)

    def test_organizer_docs_keep_live_verification_and_score_rationale_explicit(self):
        readme_path = BUNDLE / "README.md"
        writeup_path = BUNDLE / "solution/writeup.md"
        self.assertTrue(readme_path.is_file())
        self.assertTrue(writeup_path.is_file())
        readme, writeup = readme_path.read_text(), writeup_path.read_text()
        self.assertIn("NOCO_EXTERNAL_LIVE=1", readme)
        self.assertIn("verification.json", readme)
        self.assertIn("not", readme)
        self.assertIn("2026-10-16T00:00:00Z", readme)
        self.assertIn("proposed", readme)
        self.assertIn("Organizer-only", writeup)
        self.assertIn("from 214 to 628", writeup)
        self.assertIn("500", writeup)
        self.assertIn("Offline tests do not create", readme)


if __name__ == "__main__":
    unittest.main()
