import unittest
from unittest.mock import patch

from core.testcase_generator import generate_full_testcase


class TestGenerateFullTestcase(unittest.TestCase):
    def test_generate_success_user_story(self):
        analysis = {
            "actors": ["User"],
            "persona": "",
            "goal": "",
            "acceptance_criteria": [],
            "main_flow": ["step1"],
            "edge_cases": [],
            "assumptions": [],
        }

        testcases = [
            {
                "id": "TC_LOGIN_001",
                "feature": "Login",
                "screen": "Login",
                "description": "desc",
                "pre_condition": "none",
                "steps": ["s1"],
                "expected_result": "ok",
                "priority": "High",
            }
        ]

        testdata = {
            "test_data": [
                {
                    "test_case_id": "TC_LOGIN_001",
                    "username": "u",
                    "password": "p",
                    "expected_result": "ok",
                }
            ]
        }

        # Patch call_llm so generate_full_testcase doesn't call real LLM
        with patch(
            "core.testcase_generator.call_llm",
            side_effect=[analysis, testcases, testdata],
        ):
            res = generate_full_testcase(
                "As a user, I want to login",
                input_type="User Story",
                language="English",
            )
            self.assertEqual(res.get("status"), "success")
            self.assertEqual(res.get("analysis"), analysis)
            self.assertEqual(res.get("test_cases"), testcases)
            self.assertEqual(res.get("test_data"), testdata["test_data"])

    def test_generate_success_use_case_vi(self):
        # Also test normalization of input_type and language mapping
        analysis = {
            "actors": ["User"],
            "main_flow": ["step1"],
            "edge_cases": [],
            "assumptions": [],
        }
        testcases = [{"id": "TC_001", "feature": "Login"}]
        testdata = {"test_data": []}

        with patch(
            "core.testcase_generator.call_llm",
            side_effect=[analysis, testcases, testdata],
        ):
            res = generate_full_testcase(
                "Use Case: Login...", input_type="Use Case Spec", language="Tiếng Việt"
            )
            self.assertEqual(res.get("status"), "success")


if __name__ == "__main__":
    unittest.main()
