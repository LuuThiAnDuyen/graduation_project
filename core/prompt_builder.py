"""
core/prompt_builder.py
-----------------------
Default prompt builder - dùng cho Generator page (single prompt).
"""

from __future__ import annotations

_COVERAGE_TYPES = """
Coverage checklist — apply ALL that are relevant, never skip Security or Boundary:
  [P]   Positive / Happy-path     – valid input, expected flow completes
  [N]   Negative / Error-path     – invalid/missing input, system rejects gracefully
  [B]   Boundary Value            – min, max, min-1, max+1, exact numeric/length limits
  [E]   Edge Case                 – empty, null, whitespace-only, very long string, special chars
  [S]   Security                  – SQL injection, XSS, auth bypass, IDOR, privilege escalation
  [U]   UX / Usability            – label clarity, loading state, error message wording
  [DB]  Database Integrity        – data correctly persisted / updated / deleted / not duplicated
  [INT] Integration               – interaction between modules, APIs, third-party services
"""

_FEATURE_GROUP_RULES = """
════ FEATURE GROUP RULES (CRITICAL — READ CAREFULLY) ════

PRIORITY RULE — "Chức năng" sections:
  If the requirement contains section headers like "Chức năng Đặt hàng",
  "Chức năng Tìm kiếm sản phẩm", etc., you MUST use EXACTLY the name after
  "Chức năng" as the feature_group for ALL test cases under that section.
  Do NOT invent a different name.

  Example:
    "Chức năng Đặt hàng"               → feature_group = "Đặt hàng"
    "Chức năng Tìm kiếm sản phẩm"      → feature_group = "Tìm kiếm sản phẩm"
    "Chức năng Đăng nhập"               → feature_group = "Đăng nhập"
    "Chức năng Quản lý sản phẩm yêu thích" → feature_group = "Quản lý sản phẩm yêu thích"

  ALL US-1, US-2, US-3... under "Chức năng Đặt hàng"
  → ALL get feature_group = "Đặt hàng" (not "User Login", not "Order", not "Checkout")

GENERAL RULE — when no "Chức năng" header exists:
  'feature_group' = the NAME OF THE MODULE / SCREEN / FUNCTIONAL AREA.
  It is used as the Excel SHEET NAME — must represent a FUNCTION, not a test scenario.

✅ CORRECT examples:
  - "Đặt hàng"        ← từ "Chức năng Đặt hàng"
  - "Đăng nhập"       ← từ "Chức năng Đăng nhập"
  - "User Login"      ← module name khi không có "Chức năng"
  - "Product Search"  ← module name khi không có "Chức năng"

❌ WRONG — NEVER use these patterns:
  - "Login Success"           ← test OUTCOME, not a module
  - "Login Failure"           ← test OUTCOME, not a module
  - "Login Validation"        ← test TYPE, not a module
  - "Đăng nhập thành công"    ← test outcome in Vietnamese
  - "Đăng nhập thất bại"      ← test outcome in Vietnamese
  - "Positive Tests"          ← test category, not a module
  - "Negative Tests"          ← test category, not a module
  - "Order"                   ← translation of "Chức năng Đặt hàng" — WRONG, use "Đặt hàng"
  - "Checkout"                ← invented name — WRONG, use exact name from "Chức năng"

RULE: ALL test cases (positive, negative, boundary, security, edge) for the
SAME functional module MUST share the EXACT SAME 'feature_group' string.

  TC: Login with valid credentials  (P) → feature_group = "Đăng nhập"
  TC: Login with wrong password     (N) → feature_group = "Đăng nhập"
  TC: Login with SQL injection      (S) → feature_group = "Đăng nhập"
  TC: Login with empty email        (E) → feature_group = "Đăng nhập"

If the requirement contains only ONE functional area, ALL TCs share ONE feature_group.
"""
_INPUT_TYPE_GUIDES = {
    "User Story": """
INPUT FORMAT: User Story  (As a / I want / So that + Acceptance Criteria)
Parsing rules:
  • Identify EVERY separate user story — each is a distinct feature block.
  • Actor  (As a …)       → who performs the action → use as precondition subject.
  • Goal   (I want …)     → the feature under test.
  • Benefit(So that …)    → implicit success criterion → add as Positive TC.
  • Acceptance Criteria   → EVERY numbered/bulleted criterion → ≥1 TC each, no exceptions.
  • Implicit rules to always add: required fields, max-length, format validation, role restriction.
  • FEATURE GROUP: assign 'feature_group' = the MODULE/SCREEN NAME derived from the user story goal.
    Example: "I want to log in" → feature_group = "User Login" (NOT "Login Success" or "Login Failure")
    Multiple acceptance criteria for the same story → ALL share the SAME feature_group.
""",
    "Use Case Spec": """
INPUT FORMAT: Use Case Specification
Parsing rules:
  • Main Flow → Positive TC step-by-step.
  • Each Alternate Flow → separate Positive or Negative TC.
  • Each Exception / Error Flow → Negative TC.
  • Preconditions → copy verbatim as TC Precondition.
  • FEATURE GROUP: assign 'feature_group' = the USE CASE NAME (e.g. "User Login", "Order Checkout").
    ALL TCs from the same use case (main flow + alternate flows + exception flows) share ONE feature_group.
    NEVER split by flow type: "Login Success" and "Login Failure" are WRONG.
""",
    "Natural Language": """
INPUT FORMAT: Free-form Natural Language description
Parsing rules:
  • Identify EVERY distinct feature, function, or business rule mentioned.
  • Extract: WHO does WHAT, under WHAT conditions, with WHAT outcome.
  • Identify all nouns that are data fields → candidate Boundary/Edge TCs.
  • Identify all verbs that are actions → candidate Positive/Negative TCs.
  • FEATURE GROUP: assign 'feature_group' = the FEATURE/MODULE NAME (e.g. "User Login", "Product Search").
    ALL TCs for the same feature (regardless of positive/negative/boundary) share ONE feature_group.
""",
}

_OUTPUT_SCHEMA = """
Return ONLY a valid JSON object — NO markdown fences, NO text outside JSON.

{
  "status": "SUCCESS" | "INPUT_AMBIGUOUS" | "ERROR",
  "reason": "<explain if not SUCCESS, else empty string>",
  "feature_name": "<overall feature name, ≤8 words>",
  "test_cases": [
    {
      "id": "TC-001",
      "feature_group": "<MODULE/SCREEN name — e.g. 'User Login', 'Password Reset'. NEVER use outcome words like Success/Failure/Positive/Negative>",
      "title": "<concise imperative title>",
      "coverage_type": "<P|N|B|E|S|U|DB|INT>",
      "priority": "High | Medium | Low",
      "precondition": "<system state required BEFORE execution>",
      "steps": ["<Step 1>", "<Step 2>", "... (3–8 steps)"],
      "element_locator": "<per-step UI element name list — see format below>",
      "expected_result": "<observable, verifiable outcome>",
      "actual_result": "",
      "status_result": "",
      "db_query": "<SQL to verify DB state, or empty string>",
      "db_expected": "<expected DB result, or empty string>",
      "test_data_ref": "TD-001"
    }
  ],
  "test_data_set": [
    {
      "id": "TD-001",
      "description": "<what this data set is for>",
      "data": { "<field>": "<concrete value — never a placeholder>" }
    }
  ]
}

════ ELEMENT & LOCATOR FORMAT ════
The "element_locator" field lists ONE UI element name per step, matching the step order.

Format each line as a simple snake_case element name:
  <element_name>

Rules:
  • One line per step, same count as steps array.
  • Use descriptive snake_case names (e.g., email_input, password_input, login_button, submit_btn, error_message).
  • If a step has NO UI interaction (e.g., "Verify database", "Navigate to URL"), write: N/A
  • Separate lines with newline character \\n inside the string.
  • Keep names short and clear — just the element name, nothing else.

Example for a 4-step login TC:
  "element_locator": "N/A\\nemail_input\\npassword_input\\nlogin_button"
"""

_COT = """
MANDATORY INTERNAL REASONING:
  STEP 1 — List every distinct FUNCTIONAL MODULE (screen/feature area) in the requirement.
            Example: "User Login", "Password Reset", "Profile Update"
            ⚠️ Do NOT split by outcome: "Login Success" / "Login Failure" are NOT modules.
  STEP 2 — For each MODULE: list explicit + implicit acceptance criteria.
  STEP 3 — Boundary analysis: min, max, min-1, max+1 for every numeric/string field.
  STEP 4 — Security: every free-text field → SQLi + XSS TC; every role-gated action → auth bypass TC.
  STEP 5 — Assign sequential IDs: TC-001, TC-002, …  TD-001, TD-002, …
  STEP 6 — Assign 'feature_group' to each TC = the MODULE NAME from STEP 1.
            ALL TC types (P/N/B/E/S/U/DB/INT) for the same module → SAME feature_group string.
  STEP 7 — For each TC, map every step to its UI element name (snake_case).
  STEP 8 — Self-check:
            • Every feature has ≥1 TC of each relevant type?
            • feature_group values are MODULE NAMES only (no outcome/type words)?
            • All TCs for same module share EXACT SAME feature_group string?
            • actual_result="" in every TC?
            • element_locator line count = steps count?
  THEN write ONLY the JSON.
"""

_EXAMPLE = """
--- EXAMPLE (abbreviated, 2 features) ---
{
  "status": "SUCCESS", "reason": "", "feature_name": "User Authentication",
  "test_cases": [
    { "id": "TC-001", "feature_group": "User Login",
      "title": "Login successfully with valid credentials",
      "coverage_type": "P", "priority": "High",
      "precondition": "Registered user exists. No prior failed attempts. On /login.",
      "steps": ["Navigate to /login", "Enter valid email", "Enter correct password", "Click Login button"],
      "element_locator": "N/A\\nemail_input\\npassword_input\\nlogin_button",
      "expected_result": "Redirected to /dashboard. Welcome message shows user name.",
      "actual_result": "", "status_result": "",
      "db_query": "SELECT last_login FROM users WHERE email='user@test.com';",
      "db_expected": "last_login updated to current timestamp", "test_data_ref": "TD-001" },
    { "id": "TC-002", "feature_group": "User Login",
      "title": "Login fails with incorrect password",
      "coverage_type": "N", "priority": "High",
      "precondition": "Registered user exists. On /login.",
      "steps": ["Navigate to /login", "Enter valid email", "Enter wrong password", "Click Login button"],
      "element_locator": "N/A\\nemail_input\\npassword_input\\nlogin_button",
      "expected_result": "Error message 'Invalid email or password' is displayed. User stays on /login.",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": "TD-002" },
    { "id": "TC-003", "feature_group": "User Login",
      "title": "Login with SQL injection in email field",
      "coverage_type": "S", "priority": "High",
      "precondition": "On /login.",
      "steps": ["Navigate to /login", "Enter SQL injection string in Email", "Enter any password", "Click Login"],
      "element_locator": "N/A\\nemail_input\\npassword_input\\nlogin_button",
      "expected_result": "Login rejected. No SQL error exposed.",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": "TD-003" },
    { "id": "TC-010", "feature_group": "Password Reset",
      "title": "Request password reset with registered email",
      "coverage_type": "P", "priority": "High",
      "precondition": "User registered. On /forgot-password.",
      "steps": ["Navigate to /forgot-password", "Enter registered email", "Click Send Reset Link"],
      "element_locator": "N/A\\nemail_input\\nsend_reset_button",
      "expected_result": "Success message shown. Reset email sent.",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": "TD-010" },
    { "id": "TC-011", "feature_group": "Password Reset",
      "title": "Request password reset with unregistered email",
      "coverage_type": "N", "priority": "Medium",
      "precondition": "On /forgot-password.",
      "steps": ["Navigate to /forgot-password", "Enter unregistered email", "Click Send Reset Link"],
      "element_locator": "N/A\\nemail_input\\nsend_reset_button",
      "expected_result": "Generic message shown: 'If this email exists, a reset link has been sent.'",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": "TD-011" }
  ],
  "test_data_set": [
    { "id": "TD-001", "description": "Valid credentials", "data": { "email": "user@test.com", "password": "Pass@123" } },
    { "id": "TD-002", "description": "Wrong password", "data": { "email": "user@test.com", "password": "WrongPass!" } },
    { "id": "TD-003", "description": "SQL injection payload", "data": { "email": "' OR '1'='1' --", "password": "x" } },
    { "id": "TD-010", "description": "Registered email for reset", "data": { "email": "user@test.com" } },
    { "id": "TD-011", "description": "Unregistered email", "data": { "email": "notfound@test.com" } }
  ]
}

NOTE in the example above:
  ✅ TC-001, TC-002, TC-003 are all "User Login" (same module, different coverage types P/N/S)
  ✅ TC-010, TC-011 are both "Password Reset" (same module, different coverage types P/N)
  ❌ They are NOT split into "Login Success"/"Login Failure"/"Password Reset Success" etc.
--- END EXAMPLE ---
"""


def build_generate_prompt(
    requirement: str, input_type: str = "User Story", language: str = "English"
) -> str:
    guide = _INPUT_TYPE_GUIDES.get(input_type, _INPUT_TYPE_GUIDES["Natural Language"])
    lang_instr = (
        "Write ALL human-readable fields in Vietnamese (title, precondition, steps, expected_result, db_expected, description). "
        "Keep JSON keys, enum values, feature_group, and element_locator element names in English (snake_case)."
        if language == "Tiếng Việt"
        else "Write ALL human-readable fields in English."
    )

    return f"""You are a Senior QA Engineer with 10 years of experience.
Your task: read the software requirement below and generate a COMPLETE, EXHAUSTIVE test suite.

════════ MANDATORY REASONING ════════
{_COT}

════════ INPUT FORMAT GUIDE ════════
{guide}

════════ FEATURE GROUP RULES ════════
{_FEATURE_GROUP_RULES}

════════ COVERAGE REQUIREMENTS ════════
{_COVERAGE_TYPES}

════════ QUALITY RULES ════════
1. COMPLETENESS      : Every feature MUST have test cases.
2. ONE-TO-ONE        : One acceptance criterion = one dedicated TC.
3. STEPS             : Each step is a concrete atomic action.
4. REAL DATA         : TD values must be real strings/numbers, never placeholders.
5. BLANK FIELDS      : actual_result and status_result MUST be "".
6. FEATURE GROUP     : Every TC must have 'feature_group' = MODULE NAME (not test outcome/type).
                       All TCs for the same module share the EXACT SAME feature_group string.
7. ELEMENT & LOCATOR : Every TC must have 'element_locator' with exactly as many lines as steps.
8. LANGUAGE          : {lang_instr}

════════ EXAMPLE ════════
{_EXAMPLE}

════════ OUTPUT FORMAT ════════
{_OUTPUT_SCHEMA}

════════ INPUT TO PROCESS ════════
Input Type  : {input_type}
Requirement :
{requirement}
════════
Produce the JSON now:"""
