import os
import json
from dotenv import load_dotenv
import google.generativeai as genai

# Load env
load_dotenv()

# Config Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ✅ FIX MODEL (quan trọng)
model = genai.GenerativeModel("gemini-1.5-flash-latest")


# =========================
# 🔥 CALL LLM (FIX CHÍNH)
# =========================
def call_llm(prompt: str):
    try:
        print(">>> CALLING LLM...")

        response = model.generate_content(
            prompt, request_options={"timeout": 30}  # ✅ tránh treo
        )

        print(">>> LLM DONE")

        text = response.text.strip()

        # Try parse JSON
        try:
            return json.loads(text)
        except Exception:
            print(">>> WARNING: LLM output not JSON, returning raw text")
            return text

    except Exception as e:
        print(">>> LLM ERROR:", e)
        raise Exception(f"LLM error: {str(e)}")


# =========================
# 🧠 MAIN FUNCTION
# =========================
def generate_full_testcase(text, input_type="User Story", language="English"):
    try:
        print("===== GENERATE TESTCASE START =====")

        # Normalize input
        input_type = input_type.lower()
        language = "Vietnamese" if "vi" in language.lower() else "English"

        # =========================
        # STEP 1: ANALYSIS
        # =========================
        print(">>> STEP 1: ANALYSIS")

        prompt_analysis = f"""
        Analyze the following {input_type} and extract:
        - actors
        - persona
        - goal
        - acceptance_criteria
        - main_flow
        - edge_cases
        - assumptions

        Text:
        {text}

        Return JSON only.
        """

        analysis = call_llm(prompt_analysis)

        # =========================
        # STEP 2: TEST CASES
        # =========================
        print(">>> STEP 2: GENERATE TEST CASES")

        prompt_testcase = f"""
        Based on this analysis:
        {json.dumps(analysis, indent=2)}

        Generate test cases with:
        - id
        - feature
        - screen
        - description
        - pre_condition
        - steps
        - expected_result
        - priority

        Language: {language}

        Return JSON list only.
        """

        testcases = call_llm(prompt_testcase)

        # =========================
        # STEP 3: TEST DATA
        # =========================
        print(">>> STEP 3: GENERATE TEST DATA")

        prompt_testdata = f"""
        Based on these test cases:
        {json.dumps(testcases, indent=2)}

        Generate test data:
        - test_case_id
        - input values
        - expected_result

        Return JSON format:
        {{
          "test_data": [...]
        }}
        """

        testdata = call_llm(prompt_testdata)

        print("===== GENERATE DONE =====")

        return {
            "status": "success",
            "analysis": analysis,
            "test_cases": testcases,
            "test_data": (
                testdata.get("test_data", []) if isinstance(testdata, dict) else []
            ),
        }

    except Exception as e:
        print(">>> ERROR IN GENERATION:", e)

        return {"status": "error", "message": str(e)}
