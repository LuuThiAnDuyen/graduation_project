import time
import json
import re

from core.llm_client import get_client

MAX_RETRIES = 3
BASE_DELAY = 2


# =========================
# CLEAN JSON
# =========================
def clean_json(raw_text: str) -> str:
    text = raw_text.strip()

    # remove markdown
    text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)

    return text.strip()


# =========================
# EXTRACT JSON FROM TEXT
# =========================
def extract_json(text: str):
    try:
        # lấy object hoặc array đầu tiên
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if not match:
            return None

        json_str = match.group(0)

        # fix trailing commas
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)

        return json.loads(json_str)

    except json.JSONDecodeError:
        return None


# =========================
# CALL LLM (RETRY + 429 SAFE)
# =========================
def call_llm(prompt: str):
    client = get_client()
    if client is None:
        return None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model="models/gemini-2.5-flash", contents=prompt
            )

            raw = response.text or ""

            raw = clean_json(raw)

            parsed = extract_json(raw)
            if parsed:
                return parsed

        except Exception as e:
            print(f"LLM Error (attempt {attempt+1}): {e}")

            # nếu lỗi 429 → backoff
            time.sleep(BASE_DELAY * (attempt + 1))

    return None


# =========================
# MAIN PIPELINE
# =========================
def run_pipeline(user_input: str):
    if not user_input or len(user_input.strip()) < 5:
        return {"status": "ERROR", "reason": "Input chưa đủ rõ"}

    # PROMPT 1: validate + generate testcase
    prompt = f"""
You are a Senior QA Engineer.

Analyze input and generate test cases.

Return ONLY JSON:

{{
  "status": "SUCCESS" | "INPUT_AMBIGUOUS",
  "reason": "",
  "test_cases": []
}}

Input:
{user_input}
"""

    result = call_llm(prompt)

    if not result:
        return {"status": "ERROR", "reason": "LLM không trả về dữ liệu hợp lệ"}

    return result
