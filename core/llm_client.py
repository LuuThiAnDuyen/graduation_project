import os
import time
import json
import re
from google import genai
from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(env_path)
# ================= CLIENT =================
def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")

    return genai.Client(api_key=api_key)


# ================= CLEAN JSON =================
def extract_json(text: str):
    try:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if not match:
            return None

        json_str = match.group(0)
        json_str = re.sub(r",\s*}", "}", json_str)

        return json.loads(json_str)

    except Exception:
        return None


# ================= GENERIC CALL =================
def call_llm(prompt: str, retries: int = 3):
    client = get_client()

    for i in range(retries):
        try:
            response = client.models.generate_content(
                model="models/gemini-2.5-flash", contents=prompt
            )

            raw = response.text or ""
            parsed = extract_json(raw)

            if parsed:
                return parsed

        except Exception as e:
            print(f"LLM error attempt {i+1}: {e}")
            time.sleep(2**i)

    return None


# ================= MAIN GENERATE =================
def generate_test_artifacts(
    text: str, input_type: str = "User Story", language: str = "English"
):
    prompt = f"""
You are a senior QA engineer.

Input:
{text}

Input Type: {input_type}
Language: {language}

Tasks:
1. Validate input
2. Generate test cases
3. Generate Gherkin (Given/When/Then)
4. Generate test data

Return ONLY JSON in this format:

{{
  "is_valid": true,
  "test_cases": [
    {{
      "id": "TC_01",
      "title": "",
      "steps": [],
      "expected_result": ""
    }}
  ],
  "gherkin": "",
  "test_data": {{}}
}}
"""

    result = call_llm(prompt)

    if result:
        return result

    return {"is_valid": False, "error": "LLM failed to generate valid response"}
