import unittest

from cordia.onboarding import normalize_applications, score_profile
from cordia.survey_results import build_survey_results
from tests.test_survey import valid_stages


class SurveyResultsTests(unittest.TestCase):
    CATALOG = {
        "google_drive": {
            "id": "google_drive",
            "name": "Google Drive",
            "aliases": [],
            "logo": "",
            "auth_kind": "oauth2",
        }
    }

    def results(self, mutate=None):
        stages = valid_stages()
        if mutate:
            mutate(stages["workspace_discovery"]["answers"])
        discovery = stages["workspace_discovery"]["answers"]
        applications = normalize_applications(discovery["applications"], self.CATALOG, {})
        return build_survey_results(stages, score_profile(stages), applications)

    def test_plot_uses_only_documented_structured_scores(self):
        def configure(discovery):
            discovery["control_level"] = "automate_low_risk"
            discovery["applications"][0]["control_level"] = "perform_approved_actions"
            discovery["cadence"] = "Weekly"
            discovery["people_roles"] = "Founder reviews"
            discovery["source_locations"] = "Drive and Team Notes"
            discovery["environment"] = ["web", "cloud_services"]

        plot = self.results(configure)["plot"]

        self.assertEqual(71, plot["x"]["score"])
        self.assertEqual(75, plot["y"]["score"])
        self.assertEqual(88, plot["z"]["score"])
        self.assertEqual("Execution autonomy", plot["x"]["title"])
        self.assertEqual("Communication context", plot["y"]["title"])
        self.assertEqual("Workflow complexity", plot["z"]["title"])

    def test_plot_exposes_the_scored_answer_references_and_weights(self):
        plot = self.results()["plot"]

        self.assertEqual(
            {"title": "Requested control", "score": 33, "weight": 2},
            plot["x"]["references"][0],
        )
        self.assertEqual(
            {"title": "Context preference", "score": 100, "weight": 2},
            plot["y"]["references"][0],
        )
        self.assertEqual(
            {"title": "Workflow breadth", "score": 20, "weight": 2},
            plot["z"]["references"][0],
        )

    def test_direct_findings_reference_their_plot_axis(self):
        findings = {finding["title"]: finding for finding in self.results()["direct_findings"]}

        self.assertEqual("x", findings["Implementation preference"]["plot_axis"])
        self.assertEqual("y", findings["Context preference"]["plot_axis"])
        self.assertEqual("z", findings["Scope preference"]["plot_axis"])
        self.assertEqual("x", findings["Requested control"]["plot_axis"])

    def test_connector_plan_preserves_truthful_registry_status(self):
        connector = self.results()["connector_plans"][0]

        self.assertEqual("Google Drive", connector["name"])
        self.assertEqual("Setup required", connector["status"])
        self.assertEqual("OAuth", connector["auth_method"])
        self.assertIn("permission approval", connector["setup_note"])

    def test_unregistered_application_is_planned_not_failed(self):
        def configure(discovery):
            discovery["applications"] = [
                {
                    "application_id": None,
                    "name": "Private Ledger",
                    "already_uses": True,
                    "wants_added": True,
                    "current_activities": "Review balances.",
                    "desired_activities": "Prepare a summary.",
                    "inputs_outputs": "Balances in, summary out.",
                    "control_level": "suggest_actions_only",
                }
            ]

        connector = self.results(configure)["connector_plans"][0]

        self.assertEqual("Planned", connector["status"])
        self.assertEqual("Not known yet", connector["auth_method"])
        self.assertIn("not yet available", connector["setup_note"])

    def test_direct_findings_include_scored_and_explicit_answers(self):
        results = self.results()
        findings = {finding["title"]: finding["statement"] for finding in results["direct_findings"]}

        self.assertEqual("Publish a weekly project status report.", findings["Desired outcome"])
        self.assertEqual("Answer/action-first", findings["Implementation preference"])
        self.assertIn("4/5", findings["Technology & software"])
        self.assertIn("5.0/10", findings["Social energy"])

    def test_indirect_findings_name_independent_evidence_and_behavior(self):
        findings = self.results()["indirect_findings"]
        finding = next(item for item in findings if item["title"] == "Concise, context-aware execution")

        self.assertEqual("high", finding["confidence"])
        self.assertEqual(
            ["Implicit / high-context", "Answer/action-first"],
            finding["evidence"],
        )
        self.assertTrue(finding["cordia_behavior"])

    def test_missing_failure_recovery_is_explicit_for_automation(self):
        def configure(discovery):
            discovery["control_level"] = "automate_low_risk"
            discovery["cadence"] = "Every morning"
            discovery.pop("failure_behavior", None)

        unknowns = self.results(configure)["unknowns"]
        recovery = next(item for item in unknowns if item["title"] == "Failure recovery")

        self.assertTrue(recovery["statement"].startswith("Not enough evidence"))

    def test_control_preference_never_claims_authorization(self):
        serialized = str(self.results()).lower()

        self.assertNotIn("permission granted", serialized)
        self.assertNotIn("authorized to", serialized)


if __name__ == "__main__":
    unittest.main()
