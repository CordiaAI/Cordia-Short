import json
import unittest

from cordia.agent import Agent, AgentUnavailable, InvalidAgentAction


def response_for(action):
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(action)}],
            }
        ]
    }


class AgentTests(unittest.TestCase):
    def test_operator_profile_is_supplied_with_the_ternary_interpretation_contract(self):
        observed = {}

        def transport(url, headers, payload, timeout):
            observed["payload"] = payload
            return response_for(
                {
                    "action": "speak",
                    "message": "Here is the implementation.",
                    "connector_id": None,
                    "operation_id": None,
                }
            )

        Agent("api-key", transport=transport).respond(
            "# Operator profile\n\n- Implementation preference: Implementation-first (1)",
            [{"role": "user", "content": "Build it."}],
        )

        developer_content = "\n".join(
            item["content"]
            for item in observed["payload"]["input"]
            if item["role"] == "developer"
        )
        self.assertIn("-1, 0, or 1", developer_content)
        self.assertIn("Operator profile follows", developer_content)
        self.assertIn("Implementation-first (1)", developer_content)

    def test_builds_strict_request_and_parses_connector_proposal(self):
        observed = {}

        def transport(url, headers, payload, timeout):
            observed.update(url=url, headers=headers, payload=payload, timeout=timeout)
            return response_for(
                {
                    "action": "propose_connector",
                    "message": "I can connect Google Drive securely.",
                    "connector_id": "google_drive",
                    "operation_id": None,
                }
            )

        agent = Agent("secret-api-key", transport=transport)
        result = agent.respond(
            "# Workspace memory\n\n## Current apps\n\nGoogle Drive",
            [{"role": "user", "content": "Please connect my Drive"}],
        )

        self.assertEqual("propose_connector", result["action"])
        self.assertEqual("google_drive", result["connector_id"])
        self.assertEqual("Bearer secret-api-key", observed["headers"]["Authorization"])
        self.assertNotIn("secret-api-key", json.dumps(observed["payload"]))
        output_format = observed["payload"]["text"]["format"]
        self.assertEqual("json_schema", output_format["type"])
        self.assertTrue(output_format["strict"])
        self.assertFalse(output_format["schema"]["additionalProperties"])

    def test_redacts_secret_shaped_text_before_model_input(self):
        observed = {}

        def transport(url, headers, payload, timeout):
            observed["payload"] = payload
            return response_for(
                {
                    "action": "speak",
                    "message": "I did not retain that credential.",
                    "connector_id": None,
                    "operation_id": None,
                }
            )

        Agent("api-key", transport=transport).respond(
            "OPENAI_API_KEY=should-not-leave-process",
            [{"role": "user", "content": "token: ghp_123456789012345678901234567890123456"}],
        )

        serialized = json.dumps(observed["payload"])
        self.assertNotIn("should-not-leave-process", serialized)
        self.assertNotIn("ghp_123456789012345678901234567890123456", serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_transport_failure_is_plainly_unavailable(self):
        def transport(url, headers, payload, timeout):
            raise OSError("network unavailable")

        with self.assertRaisesRegex(AgentUnavailable, "model request failed"):
            Agent("api-key", transport=transport).respond("memory", [])

    def test_missing_key_is_plainly_unavailable(self):
        with self.assertRaisesRegex(AgentUnavailable, "OPENAI_API_KEY"):
            Agent("").respond("memory", [])

    def test_rejects_action_outside_bounded_contract(self):
        def transport(url, headers, payload, timeout):
            return response_for(
                {
                    "action": "delete_everything",
                    "message": "Done",
                    "connector_id": None,
                    "operation_id": None,
                }
            )

        with self.assertRaises(InvalidAgentAction):
            Agent("api-key", transport=transport).respond("memory", [])

    def test_run_operation_requires_connector_and_operation(self):
        def transport(url, headers, payload, timeout):
            return response_for(
                {
                    "action": "run_operation",
                    "message": "I will inspect Drive.",
                    "connector_id": "google_drive",
                    "operation_id": None,
                }
            )

        with self.assertRaisesRegex(InvalidAgentAction, "operation_id"):
            Agent("api-key", transport=transport).respond("memory", [])


if __name__ == "__main__":
    unittest.main()
