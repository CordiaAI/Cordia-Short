import copy
import unittest

from cordia.survey import (
    SCHEMA_VERSION,
    STAGE_ORDER,
    conditional_discovery_fields,
    next_stage,
    public_stage_schema,
    validate_stage,
)


def valid_part_one_payload():
    return {"answers": {f"p1_{number:02d}": 3 for number in range(1, 21)}}


def valid_part_two_payload():
    return {
        "domains": ["technology_software"],
        "ratings": {"technology_software": 4},
        "familiarity": {
            "technology_software": {
                "cloud storage": "familiar",
                "two-factor authentication": "familiar",
                "adaptive port throttling": "not_familiar",
                "browser cache": "familiar",
                "API": "familiar",
            }
        },
    }


def valid_part_three_payload():
    return {
        "briefing_style": "requirements_upfront",
        "reply_preference": "literal_narrow",
        "most": "logical",
        "least": "imaginative",
        "flawed_plan": "state_plainly",
        "answer_order": "reasoning_first",
        "background_assumption": "spell_out_background",
        "edit_boundary": "only_requested_edits",
        "bad_idea": "say_so_directly",
    }


def valid_part_four_payload():
    return {
        "request_1": "Help me plan today.",
        "request_2": "Review this project outline.",
        "request_3": "",
    }


def valid_discovery_payload():
    return {
        "outcome": "Publish a weekly project status report.",
        "success_criteria": "The report is ready every Friday.",
        "current_workflow": "I collect notes and write the report manually.",
        "applications": [
            {
                "application_id": "google_drive",
                "name": "Google Drive",
                "already_uses": True,
                "wants_added": True,
                "current_activities": "Store weekly notes.",
                "desired_activities": "Collect the source notes.",
                "inputs_outputs": "Notes in, report draft out.",
                "control_level": "prepare_for_approval",
            }
        ],
        "inputs": "Weekly notes.",
        "outputs": "A status report.",
        "control_level": "prepare_for_approval",
        "first_workspace": "A report drafting workspace.",
    }


class SurveyManifestTests(unittest.TestCase):
    def test_schema_version_and_stage_order_are_stable(self):
        self.assertEqual(2, SCHEMA_VERSION)
        self.assertEqual(
            (
                "assessment_part_1",
                "assessment_part_2",
                "assessment_part_3",
                "assessment_part_4",
                "profile_snapshot",
                "workspace_discovery",
                "workspace_review",
            ),
            STAGE_ORDER,
        )

    def test_part_one_contains_all_twenty_source_statements(self):
        schema = public_stage_schema("assessment_part_1")
        prompts = [item["prompt"] for item in schema["questions"]]
        self.assertEqual(20, len(prompts))
        self.assertEqual("Am the life of the party.", prompts[0])
        self.assertEqual("Do not have a good imagination.", prompts[-1])
        self.assertTrue(all(item["options"] == [1, 2, 3, 4, 5] for item in schema["questions"]))

    def test_domain_terms_match_the_source(self):
        schema = public_stage_schema("assessment_part_2")
        self.assertEqual(
            ["cloud storage", "two-factor authentication", "adaptive port throttling", "browser cache", "API"],
            schema["domains"]["technology_software"]["terms"],
        )
        self.assertEqual([], schema["domains"]["work_professional"]["terms"])
        self.assertIn("passive humidity banking", schema["domains"]["everyday_general"]["terms"])

    def test_part_three_prompts_and_options_match_the_source(self):
        schema = public_stage_schema("assessment_part_3")
        questions = {item["id"]: item for item in schema["questions"]}
        self.assertEqual(
            "You're briefing a new assistant on a task. You'd rather:",
            questions["briefing_style"]["prompt"],
        )
        self.assertEqual(
            ["Write out every requirement and constraint upfront", "Give the gist and correct it as you go"],
            [option["label"] for option in questions["briefing_style"]["options"]],
        )
        self.assertEqual(
            ['A literal, narrow reply that answers only what was explicitly asked', 'A reply that infers likely unstated context and addresses it'],
            [option["label"] for option in questions["reply_preference"]["options"]],
        )
        self.assertEqual(["logical", "practical", "imaginative", "data-driven"], questions["most_least"]["options"])
        self.assertEqual(["State it plainly", "Ask leading questions to get them there", "Hint at it", "Go along with it"], [option["label"] for option in questions["flawed_plan"]["options"]])
        self.assertEqual(["Walk through your reasoning first, then give the answer", "Give the answer first, then reasoning if asked"], [option["label"] for option in questions["answer_order"]["options"]])
        self.assertEqual(["Assume they need the background spelled out", "Assume they'll pick up what you mean from context"], [option["label"] for option in questions["background_assumption"]["options"]])
        self.assertEqual(['A reply that makes only the specific edits literally requested', "A reply that also flags likely problems the sender didn't mention"], [option["label"] for option in questions["edit_boundary"]["options"]])
        self.assertEqual(["Say so directly", "Soften it heavily", "Ask questions instead of stating your view"], [option["label"] for option in questions["bad_idea"]["options"]])
        self.assertTrue(questions["most_least"]["distinct_selection"])

    def test_part_four_required_and_optional_fields_match_the_source(self):
        fields = public_stage_schema("assessment_part_4")["fields"]
        self.assertEqual(
            [("request_1", "Request 1", True), ("request_2", "Request 2", True), ("request_3", "Request 3", False)],
            [(field["id"], field["label"], field["required"]) for field in fields],
        )

    def test_part_two_requires_one_or_two_domains(self):
        schema = public_stage_schema("assessment_part_2")
        self.assertEqual({"minimum": 1, "maximum": 2}, schema["domain_limit"])

    def test_schema_is_a_fresh_browser_safe_copy(self):
        first = public_stage_schema("assessment_part_1")
        first["questions"][0]["prompt"] = "changed"
        self.assertEqual("Am the life of the party.", public_stage_schema("assessment_part_1")["questions"][0]["prompt"])

    def test_workspace_schema_uses_saved_discovery_answers_for_active_conditions(self):
        schema = public_stage_schema("workspace_discovery", {
            "workspace_discovery": {
                "schema_version": 2,
                "answers": {"control_level": "automate_low_risk"},
            }
        })
        self.assertEqual(["failure_behavior", "approval_boundaries"], schema["active_conditional_fields"])


class SurveyValidationTests(unittest.TestCase):
    def test_part_one_normalizes_answers(self):
        result = validate_stage("assessment_part_1", valid_part_one_payload())
        self.assertEqual(SCHEMA_VERSION, result["schema_version"])
        self.assertEqual(valid_part_one_payload()["answers"], result["answers"]["answers"])

    def test_part_one_requires_all_integer_ratings(self):
        with self.assertRaisesRegex(ValueError, "all 20 statements"):
            validate_stage("assessment_part_1", {"answers": {"p1_01": 5}})

    def test_part_one_rejects_booleans_and_out_of_range_ratings(self):
        payload = valid_part_one_payload()
        payload["answers"]["p1_01"] = True
        with self.assertRaisesRegex(ValueError, "p1_01"):
            validate_stage("assessment_part_1", payload)
        payload["answers"]["p1_01"] = 6
        with self.assertRaisesRegex(ValueError, "p1_01"):
            validate_stage("assessment_part_1", payload)

    def test_domains_are_limited_to_two(self):
        with self.assertRaisesRegex(ValueError, "1 or 2 domains"):
            validate_stage("assessment_part_2", {"domains": ["technology_software", "money_finance", "creative_writing"], "ratings": {}, "familiarity": {}})

    def test_part_two_rejects_unknown_domains_and_missing_familiarity(self):
        payload = valid_part_two_payload()
        payload["domains"] = ["unknown"]
        with self.assertRaisesRegex(ValueError, "unknown domain"):
            validate_stage("assessment_part_2", payload)
        payload = valid_part_two_payload()
        del payload["familiarity"]["technology_software"]["API"]
        with self.assertRaisesRegex(ValueError, "familiarity"):
            validate_stage("assessment_part_2", payload)

    def test_part_three_normalizes_all_choices(self):
        result = validate_stage("assessment_part_3", valid_part_three_payload())
        self.assertEqual(valid_part_three_payload(), result["answers"])

    def test_most_and_least_must_differ(self):
        payload = valid_part_three_payload()
        payload["most"] = payload["least"] = "logical"
        with self.assertRaisesRegex(ValueError, "different"):
            validate_stage("assessment_part_3", payload)

    def test_part_three_rejects_unknown_options(self):
        payload = valid_part_three_payload()
        payload["briefing_style"] = "unknown"
        with self.assertRaisesRegex(ValueError, "briefing_style"):
            validate_stage("assessment_part_3", payload)

    def test_part_four_requires_two_real_prompts(self):
        with self.assertRaisesRegex(ValueError, "Request 2"):
            validate_stage("assessment_part_4", {"request_1": "Help me plan today", "request_2": ""})

    def test_part_four_rejects_too_long_prompt_and_unexpected_keys(self):
        payload = valid_part_four_payload()
        payload["request_1"] = "x" * 2001
        with self.assertRaisesRegex(ValueError, "Request 1"):
            validate_stage("assessment_part_4", payload)
        payload = valid_part_four_payload()
        payload["unexpected"] = "no"
        with self.assertRaisesRegex(ValueError, "unexpected"):
            validate_stage("assessment_part_4", payload)

    def test_workspace_discovery_normalizes_core_and_applications(self):
        result = validate_stage("workspace_discovery", valid_discovery_payload())
        self.assertEqual(valid_discovery_payload(), result["answers"])

    def test_workspace_discovery_rejects_long_text_and_more_than_twenty_applications(self):
        payload = valid_discovery_payload()
        payload["outcome"] = "x" * 4001
        with self.assertRaisesRegex(ValueError, "outcome"):
            validate_stage("workspace_discovery", payload)
        payload = valid_discovery_payload()
        payload["applications"] = [copy.deepcopy(payload["applications"][0]) for _ in range(21)]
        with self.assertRaisesRegex(ValueError, "20 applications"):
            validate_stage("workspace_discovery", payload)

    def test_unknown_and_computed_stages_are_rejected(self):
        for stage in ("unknown", "profile_snapshot", "workspace_review"):
            with self.assertRaisesRegex(ValueError, "unknown onboarding stage"):
                validate_stage(stage, {})

    def test_next_stage_skips_computed_stages_and_resumes_first_incomplete(self):
        self.assertEqual("assessment_part_1", next_stage({}))
        saved = {stage: {"answers": {}} for stage in STAGE_ORDER[:4]}
        self.assertEqual("workspace_discovery", next_stage(saved))
        self.assertIsNone(next_stage({stage: {"answers": {}} for stage in ("assessment_part_1", "assessment_part_2", "assessment_part_3", "assessment_part_4", "workspace_discovery")}))

    def test_conditional_discovery_fields_are_stable_and_rule_based(self):
        self.assertEqual([], conditional_discovery_fields({}))
        fields = conditional_discovery_fields({
            "sensitive_data": ["financial", "health"],
            "control_level": "automate_low_risk",
            "environment": ["cloud_services", "company_network"],
        })
        self.assertEqual(
            ["sensitive_data_details", "failure_behavior", "approval_boundaries", "environment_policy"],
            fields,
        )
