import unittest

from scripts import verify_agent


class VerificationGuardTests(unittest.TestCase):
    def test_old_workspace_artifact_is_not_proof_of_a_new_operation(self):
        with self.assertRaisesRegex(AssertionError, "current run"):
            verify_agent.require_current_artifact({"artifact": None, "artifacts": [{"id": 7}]}, 7)

    def test_only_current_run_matching_artifact_is_accepted(self):
        verify_agent.require_current_artifact({"artifact": {"id": 7, "rows": [["real row"]]}}, 7)
        with self.assertRaises(AssertionError):
            verify_agent.require_current_artifact({"artifact": {"id": 8, "rows": [["other"]]}}, 7)
