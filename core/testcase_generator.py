# core/testcase_generator.py

import time
import json
import re
from core.llm_client import get_client

MAX_RETRIES = 3
BASE_DELAY = 2


# ===============================
# PROMPTS
# ===============================
def _normalize_input_type(input_type: str) -> str:
    if not input_type:
        return "user story"
    s = input_type.strip().casefold()
    mapping = {
        "user story": "user story",
        "userstory": "user story",
        "user-story": "user story",
        "use case spec": "use case spec",
        "use case": "use case spec",
        "usecase": "use case spec",
        "natural language": "natural language",
        "natural": "natural language",
        "nl": "natural language",
    }
    return mapping.get(s, s)


def _normalize_language(language: str) -> str:
    if not language:
        return "English"
    s = language.strip().lower()
    if s in ("tiếng việt", "tieng viet", "vietnamese", "vi"):
        return "Tiếng Việt"
    return "English"


def build_analysis_prompt(text, input_type, language):
    input_type = _normalize_input_type(input_type)
    lang = _normalize_language(language)

    # Different templates depending on input type to help the LLM parse structured specs
    if input_type == "use case spec":
        template = f"""
You are a senior QA engineer.

Parse the following Use Case specification and return ONLY JSON with these fields:
{{
  "actors": [],
  "pre_conditions": [],
  "post_conditions": [],
  "main_flow": [],
  "alternate_flows": [],
  "edge_cases": [],
  "assumptions": []
}}

Language: {lang}

{text}
"""
        return template

    if input_type == "user story":
        template = f"""
You are a senior QA engineer.

Analyze the following User Story. Extract persona, goal, acceptance criteria and produce ONLY JSON in this format:
{{
  "actors": [],
  "persona": "",
  "goal": "",
  "acceptance_criteria": [],
  "main_flow": [],
  "edge_cases": [],
  "assumptions": []
}}

Language: {lang}

{text}
"""
        return template

    # fallback / natural language
    template = f"""
You are a senior QA engineer.

Analyze the following requirement (natural language) and return ONLY JSON:
{{
  "actors": [],
  "main_flow": [],
  "edge_cases": [],
  "assumptions": []
}}

Language: {lang}

{text}
"""

    return template


def build_testcase_prompt(text, analysis, language):
    lang = _normalize_language(language)
    guidance = "IDs must be UNIQUE. Prefer IDs with a feature prefix and zero-padded numbers, e.g. LOGIN_001."

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
- {guidance}
- Cover positive, negative, edge

Language: {lang}

Analysis:
{json.dumps(analysis, indent=2)}

Requirement:
{text}
"""


def build_testdata_prompt(testcases, language):
    lang = _normalize_language(language)

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
                model="gemini-1.5-flash-latest",
                contents=prompt,
            )

            raw = res.text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()

            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # Attempt to extract a JSON substring if there is extra text
                print("LLM raw response (non-JSON):", raw)
                # find first { or [ and last matching } or ]
                start = None
                end = None
                m1 = re.search(r"\{", raw)
                m2 = re.search(r"\[", raw)
                if m1:
                    start = m1.start()
                    # find last }
                    last = raw.rfind("}")
                    if last != -1:
                        end = last + 1
                if start is None and m2:
                    start = m2.start()
                    last = raw.rfind("]")
                    if last != -1:
                        end = last + 1

                if start is not None and end is not None and end > start:
                    substring = raw[start:end]
                    try:
                        return json.loads(substring)
                    except Exception as e:
                        print("Failed to parse JSON substring:", e)

                # If parsing fails, re-raise to trigger retry/backoff
                raise

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
