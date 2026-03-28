# core/testcase_generator.py

import time
import json
from core.llm_client import get_client

MAX_RETRIES = 3
BASE_DELAY = 2


# ===============================
# PROMPTS
# ===============================
def build_analysis_prompt(text, input_type, language):
    lang = "Vietnamese" if language == "Tiếng Việt" else "English"

    return f"""
You are a senior QA engineer.

Analyze the following {input_type}.

Return ONLY JSON:

{{
  "actors": [],
  "main_flow": [],
  "edge_cases": [],
  "assumptions": []
}}

Language: {lang}

{text}
"""


def build_testcase_prompt(text, analysis, language):
    lang = "Vietnamese" if language == "Tiếng Việt" else "English"

    return f"""
Generate test cases in JSON.

STRICT FORMAT:

[
  {{
    "id": "TC_LOGIN_001",
    "feature": "...",
    "screen": "...",
    "description": "...",
    "pre_condition": "...",
    "steps": ["Step 1", "Step 2"],
    "expected_result": "...",
    "priority": "High/Medium/Low"
  }}
]

Rules:
- IDs must be UNIQUE
- Cover positive, negative, edge

Language: {lang}

Analysis:
{json.dumps(analysis, indent=2)}

Requirement:
{text}
"""


def build_testdata_prompt(testcases, language):
    lang = "Vietnamese" if language == "Tiếng Việt" else "English"

    return f"""
Generate test data.

STRICT FORMAT:

{{
  "test_data": [
    {{
      "test_case_id": "TC_LOGIN_001",
      "username": "...",
      "password": "...",
      "expected_result": "..."
    }}
  ]
}}

Language: {lang}

Test Cases:
{json.dumps(testcases, indent=2)}
"""


# ===============================
# LLM CALL
# ===============================
def call_llm(prompt):
    client = get_client()
    delay = BASE_DELAY

    for _ in range(MAX_RETRIES):
        try:
            res = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt,
            )

            raw = res.text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()

            return json.loads(raw)

        except Exception as e:
            print("LLM error:", e)
            time.sleep(delay)
            delay *= 2

    return None


# ===============================
# MAIN FUNCTION (API READY)
# ===============================
def generate_full_testcase(text, input_type="user story", language="English"):
    if not text.strip():
        return {"status": "error", "message": "Empty input"}

    analysis = call_llm(build_analysis_prompt(text, input_type, language))
    if not analysis:
        return {"status": "error", "step": "analysis"}

    testcases = call_llm(build_testcase_prompt(text, analysis, language))
    if not testcases:
        return {"status": "error", "step": "testcase"}

    testdata = call_llm(build_testdata_prompt(testcases, language))
    if not testdata:
        return {"status": "error", "step": "testdata"}

    return {
        "status": "success",
        "input": text,
        "analysis": analysis,
        "test_cases": testcases,
        "test_data": testdata.get("test_data", []),
    }
