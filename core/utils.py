import json
import re


def extract_json(text):
    try:
        return json.loads(text)
    except:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError("Invalid JSON from LLM")


def validate_output(data):
    if not isinstance(data, dict):
        raise ValueError("Output must be JSON")

    if "test_cases" not in data:
        raise ValueError("Missing test_cases")

    return True
