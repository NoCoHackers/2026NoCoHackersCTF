import unittest

import otp_policy as policy


class PolicyTests(unittest.TestCase):
    def test_exact_baseline_required(self):
        baseline = policy.baseline_rows()
        self.assertEqual(len(baseline), 34)
        policy.validate_baseline(baseline)
        for row in baseline:
            changed = baseline.copy()
            changed[row] ^= 1
            with self.assertRaises(ValueError):
                policy.validate_baseline(changed)
        incomplete = baseline.copy()
        incomplete.pop(0x41)
        with self.assertRaises(ValueError):
            policy.validate_baseline(incomplete)

    def test_final_raw_words_and_redundancy(self):
        final = policy.proposed_final_rows()
        self.assertEqual(len(policy.CRIT1_ROWS), 8)
        self.assertTrue(all(final[r] == 0x000005 for r in policy.CRIT1_ROWS))
        self.assertTrue(all(final[r] == 0x082000 for r in policy.BOOT_FLAGS0_ROWS))
        self.assertTrue(all(final[r] == 0x000001 for r in policy.BOOT_FLAGS1_ROWS))
        self.assertEqual(final[0xf83], 0x151515)
        self.assertEqual(final[0xf85], 0x151515)
        for row in (0xfbb, 0xfbd, 0xfbf):
            self.assertEqual(final[row], 0x3d3d3d)

    def test_transitions_only_set_bits(self):
        final = policy.proposed_final_rows()
        for row, old in policy.baseline_rows().items():
            self.assertEqual(old & ~final[row], 0)
        for _, _, old, new in policy.CONTROL_STAGES:
            self.assertEqual(old & ~new, 0)

    def test_page_zero_and_lock_zero_preserved(self):
        old = policy.baseline_rows()
        final = policy.proposed_final_rows()
        for row in [0xf80, 0xf81, 0xf82, 0xf84, 0xfba, 0xfbc, 0xfbe, *policy.CRIT0_ROWS]:
            self.assertEqual(final[row], old[row])

    def test_usb_and_signed_sram_recovery_preserved(self):
        flags = policy.proposed_final_rows()[0x48]
        for bit in (11, 12, 14, 17, 18, 21):
            self.assertEqual(flags & (1 << bit), 0)
        self.assertEqual(flags, (1 << 13) | (1 << 19))

    def test_only_slot_zero_activated_and_no_slots_revoked(self):
        final = policy.proposed_final_rows()
        for row in policy.BOOT_FLAGS1_ROWS:
            self.assertEqual(final[row] & 0xf, 1)
            self.assertEqual((final[row] >> 8) & 0xf, 0)
        transitions = [(old, new) for _, rows, old, new in policy.CONTROL_STAGES
                       if set(rows) & set(policy.BOOT_FLAGS1_ROWS)]
        self.assertEqual(transitions, [(0, 1)])
        for _, start, end, _, _ in policy.DATA_REGIONS:
            self.assertFalse(set(range(start, end + 1)) & set(range(0x90, 0xc0)))

    def test_data_regions_disjoint_and_no_salt_padding_writes(self):
        covered = set()
        for _, start, end, _, _ in policy.DATA_REGIONS:
            current = set(range(start, end + 1))
            self.assertFalse(covered & current)
            covered |= current
        self.assertEqual(len(covered), 16 + 144)
        self.assertFalse(covered & set(range(0x7c8, 0x7e0)))
        self.assertFalse(covered & set(range(0x7e8, 0x800)))
        self.assertFalse(covered & set(policy.baseline_rows()))

    def test_secret_locks_after_root_integrity(self):
        stages = [name for name, _, _, _ in policy.CONTROL_STAGES]
        root = stages.index("protect_policy_page")
        for i, (_, rows, _, _) in enumerate(policy.CONTROL_STAGES):
            if set(rows) & {0xfbb, 0xfbd, 0xfbf}:
                self.assertGreater(i, root)

    def test_policy_approval_does_not_authorize_programming(self):
        result = policy.proposal()
        self.assertTrue(result["policy_approved"])
        self.assertFalse(result["authorized_for_programming"])
        self.assertFalse(result["secret_values_included"])
        self.assertEqual(result["device_serial"], "9423D016AADE5950")
        self.assertEqual(result["kind"], "NOCO_REVIEW_ONLY_NOT_A_PICOTOOL_RECIPE")
        self.assertIn("runtime_not_otp", result)
        self.assertFalse(set(result) & {"bootkey0", "crit1", "boot_flags0", "boot_flags1"})


if __name__ == "__main__":
    unittest.main()
