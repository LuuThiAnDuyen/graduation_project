"""
core/prompt_builder.py
-----------------------
Prompt engineering tập trung tại đây – không có business logic.

Thay đổi v3:
  • Bỏ BDD (Gherkin) và min_cases hoàn toàn
  • MULTI-FEATURE DETECTION: LLM phải xử lý TỪNG feature, không bỏ sót
  • COT ép LLM đếm feature → enumerate criteria → map từng cái thành TC
  • Không giới hạn số TC — "as many as needed for 100% coverage"
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# COVERAGE MATRIX
# ─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
# PER-INPUT-TYPE PARSING INSTRUCTIONS
# ─────────────────────────────────────────────────────────────────────────────
_INPUT_TYPE_GUIDES: dict[str, str] = {
    "User Story": """
INPUT FORMAT: User Story  (As a / I want / So that + Acceptance Criteria)
Parsing rules:
  • Identify EVERY separate user story — each is a distinct feature block.
  • Actor  (As a …)       → who performs the action → use as precondition subject.
  • Goal   (I want …)     → the feature under test.
  • Benefit(So that …)    → implicit success criterion → add as Positive TC.
  • Acceptance Criteria   → EVERY numbered/bulleted criterion → ≥1 TC each, no exceptions.
  • Implicit rules to always add: required fields, max-length, format validation, role restriction.
  • Do NOT merge criteria from different stories into one TC.
""",
    "Use Case Spec": """
INPUT FORMAT: Use Case Specification  (Actor, Preconditions, Main Flow, Alternate Flows, Exceptions)
Parsing rules:
  • Identify EVERY separate use case — each is a distinct feature block.
  • Main Flow (Basic Path)        → Positive TC, step-by-step.
  • Each Alternate Flow           → separate Positive or Negative TC.
  • Each Exception / Error Flow   → Negative TC.
  • Preconditions in spec         → copy verbatim as TC Precondition.
  • Postconditions in spec        → use as Expected Result anchor.
  • Extension points (e.g. "2a.") → Boundary or Edge TC.
""",
    "Natural Language": """
INPUT FORMAT: Free-form Natural Language description
Parsing rules:
  • Identify EVERY distinct feature, function, or business rule mentioned.
  • Extract: WHO does WHAT, under WHAT conditions, with WHAT outcome.
  • Identify all nouns that are data fields → candidate Boundary/Edge TCs.
  • Identify all verbs that are actions     → candidate Positive/Negative TCs.
  • Infer business rules from context (e.g. "only admin can…" → Security TC).
  • When ambiguous: use the most conservative interpretation; note it in precondition.
  • Do NOT invent requirements not present or clearly implied.
""",
}

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT SCHEMA
# ─────────────────────────────────────────────────────────────────────────────
_OUTPUT_SCHEMA = """
Return ONLY a valid JSON object — NO markdown fences, NO text outside JSON.

{
  "status": "SUCCESS" | "INPUT_AMBIGUOUS" | "ERROR",
  "reason": "<explain if not SUCCESS, else empty string>",
  "feature_name": "<overall feature / project name, ≤8 words>",
  "test_cases": [
    {
      "id": "TC-001",
      "title": "<concise imperative title>",
      "coverage_type": "<P|N|B|E|S|U|DB|INT>",
      "priority": "High | Medium | Low",
      "precondition": "<system state and data required BEFORE execution>",
      "steps": [
        "<Step 1: concrete atomic UI or API action — subject + verb + object>",
        "<Step 2>",
        "... (3–8 steps)"
      ],
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
      "data": {
        "<field>": "<concrete value — never a placeholder>"
      }
    }
  ]
}

FIELD RULES:
  • actual_result  → ALWAYS ""  (tester fills in after execution)
  • status_result  → ALWAYS ""  (tester fills Pass/Fail after execution)
  • test_data_ref  → TD id of matching entry; "" if no specific data needed
  • Every TC using specific data values MUST reference a TD entry
  • Reuse the same TD id if two TCs share identical data
  • db_query/db_expected: provide for DB-write features; else ""
"""

# ─────────────────────────────────────────────────────────────────────────────
# CHAIN-OF-THOUGHT — FORCES EXHAUSTIVE PER-FEATURE COVERAGE
# ─────────────────────────────────────────────────────────────────────────────
_COT_INSTRUCTION = """
MANDATORY INTERNAL REASONING — complete ALL 7 steps before writing JSON:

  STEP 1 — FEATURE DETECTION
    • Read the entire input.
    • Count and list every distinct feature / user story / use case.
    • Label them F1, F2, F3, … (e.g. F1=Login, F2=Register, F3=Forgot Password).
    • You MUST produce test cases for EVERY feature — missing one is a critical failure.

  STEP 2 — CRITERIA EXTRACTION  (for each feature Fi)
    • List every EXPLICIT acceptance criterion.
    • List every IMPLICIT rule: required fields, max/min length, format, role restriction,
      uniqueness constraint, state machine transition (e.g. "locked account").
    • Label each: F1-C1, F1-C2, F2-C1, …

  STEP 3 — BOUNDARY ANALYSIS  (for each feature Fi)
    • For every numeric field       : min, max, min-1, max+1.
    • For every string/text field   : empty string, 1 char, max length, max+1 length.
    • For every enum / dropdown     : each valid option + at least one invalid value.
    • For every date/time field     : past, present, future, invalid format.

  STEP 4 — SECURITY ANALYSIS
    • Every field accepting free text → SQL injection TC + XSS TC.
    • Every action gated by role/auth → auth bypass TC + IDOR TC if applicable.

  STEP 5 — TEST CASE PLANNING
    • Each criterion Fi-Cj → ≥1 TC. Never bundle two criteria into one TC.
    • Each boundary value  → 1 dedicated TC.
    • Each security concern→ 1 dedicated TC.
    • Coverage types P, N, B, E, S must ALL appear across the full suite.
    • Order: High priority first, then Medium, then Low.
    • Assign sequential IDs: TC-001, TC-002, … with no gaps.

  STEP 6 — TEST DATA PLANNING
    • For each TC using specific values: create a TD entry with REAL values.
    • TD ids: TD-001, TD-002, … — reuse if data is identical across TCs.

  STEP 7 — SELF-CHECK  (before writing JSON)
    Answer each question — if the answer is NO, add the missing TCs before proceeding:
    ✓ Every feature Fi has at least one TC?
    ✓ Every acceptance criterion Fi-Cj has at least one dedicated TC?
    ✓ Every boundary condition has a TC?
    ✓ Every free-text input field has a Security TC?
    ✓ actual_result and status_result are "" in every TC?

  THEN — produce ONLY the JSON object. Do not output the reasoning.
"""

# ─────────────────────────────────────────────────────────────────────────────
# FEW-SHOT EXAMPLE
# ─────────────────────────────────────────────────────────────────────────────
_FEW_SHOT_EXAMPLE = """
--- EXAMPLE INPUT (2 User Stories) ---
Story 1 – Login
As a registered user I want to log in with email and password so I can access my account.
Acceptance criteria:
  - Email and password are required
  - Wrong credentials show "Invalid email or password"
  - Locked after 5 failed attempts

Story 2 – Logout
As a logged-in user I want to log out so my session is ended.
Acceptance criteria:
  - Clicking Logout invalidates the session
  - After logout, accessing /dashboard redirects to /login

--- EXAMPLE OUTPUT (abbreviated — your real output covers EVERY criterion exhaustively) ---
{
  "status": "SUCCESS",
  "reason": "",
  "feature_name": "User Authentication",
  "test_cases": [
    {
      "id": "TC-001", "title": "Login successfully with valid credentials",
      "coverage_type": "P", "priority": "High",
      "precondition": "Registered user exists. No prior failed attempts. On /login.",
      "steps": ["Navigate to /login", "Enter valid email", "Enter correct password", "Click Login button"],
      "expected_result": "Redirected to /dashboard. Welcome message shows user name.",
      "actual_result": "", "status_result": "",
      "db_query": "SELECT last_login FROM users WHERE email='user@test.com';",
      "db_expected": "last_login updated to current timestamp", "test_data_ref": "TD-001"
    },
    {
      "id": "TC-002", "title": "Login fails with incorrect password",
      "coverage_type": "N", "priority": "High",
      "precondition": "Registered user exists. On /login.",
      "steps": ["Navigate to /login", "Enter valid email", "Enter wrong password", "Click Login button"],
      "expected_result": "Error 'Invalid email or password' shown. User stays on /login.",
      "actual_result": "", "status_result": "",
      "db_query": "SELECT failed_attempts FROM users WHERE email='user@test.com';",
      "db_expected": "failed_attempts incremented by 1", "test_data_ref": "TD-002"
    },
    {
      "id": "TC-003", "title": "Login fails with empty email field",
      "coverage_type": "E", "priority": "Medium",
      "precondition": "On /login.",
      "steps": ["Navigate to /login", "Leave Email field empty", "Enter any password", "Click Login button"],
      "expected_result": "Validation error 'Email is required' shown. Form not submitted.",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": "TD-003"
    },
    {
      "id": "TC-004", "title": "Login fails with empty password field",
      "coverage_type": "E", "priority": "Medium",
      "precondition": "On /login.",
      "steps": ["Navigate to /login", "Enter valid email", "Leave Password field empty", "Click Login button"],
      "expected_result": "Validation error 'Password is required' shown. Form not submitted.",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": "TD-004"
    },
    {
      "id": "TC-005", "title": "Account locks on 5th consecutive failed login",
      "coverage_type": "B", "priority": "High",
      "precondition": "Account has exactly 4 prior failed attempts recorded.",
      "steps": ["Navigate to /login", "Enter valid email", "Enter wrong password", "Click Login (5th attempt)"],
      "expected_result": "'Account locked. Contact support.' shown. Login button disabled.",
      "actual_result": "", "status_result": "",
      "db_query": "SELECT is_locked FROM users WHERE email='user@test.com';",
      "db_expected": "is_locked = true", "test_data_ref": "TD-005"
    },
    {
      "id": "TC-006", "title": "Account NOT locked on 4th failed login",
      "coverage_type": "B", "priority": "High",
      "precondition": "Account has exactly 3 prior failed attempts.",
      "steps": ["Navigate to /login", "Enter valid email", "Enter wrong password", "Click Login (4th attempt)"],
      "expected_result": "Error 'Invalid email or password' shown. Account NOT locked. Login button still enabled.",
      "actual_result": "", "status_result": "",
      "db_query": "SELECT is_locked, failed_attempts FROM users WHERE email='user@test.com';",
      "db_expected": "is_locked=false, failed_attempts=4", "test_data_ref": "TD-006"
    },
    {
      "id": "TC-007", "title": "Login with SQL injection in email field",
      "coverage_type": "S", "priority": "High",
      "precondition": "On /login.",
      "steps": ["Navigate to /login", "Enter SQL injection string in Email field", "Enter any password", "Click Login"],
      "expected_result": "Login rejected. No SQL error exposed. No unauthorized access.",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": "TD-007"
    },
    {
      "id": "TC-008", "title": "Logout invalidates session",
      "coverage_type": "P", "priority": "High",
      "precondition": "User is logged in and on /dashboard.",
      "steps": ["Click the Logout button", "Observe redirect destination"],
      "expected_result": "Redirected to /login. Session token invalidated.",
      "actual_result": "", "status_result": "",
      "db_query": "SELECT session_token FROM sessions WHERE user_id=1;",
      "db_expected": "session_token is NULL or row deleted", "test_data_ref": ""
    },
    {
      "id": "TC-009", "title": "Accessing /dashboard after logout redirects to /login",
      "coverage_type": "S", "priority": "High",
      "precondition": "User has just logged out.",
      "steps": ["Paste /dashboard URL into browser address bar", "Press Enter"],
      "expected_result": "Browser redirects to /login. Dashboard content is NOT visible.",
      "actual_result": "", "status_result": "", "db_query": "", "db_expected": "", "test_data_ref": ""
    }
  ],
  "test_data_set": [
    { "id": "TD-001", "description": "Valid credentials", "data": { "email": "user@test.com", "password": "Pass@123" } },
    { "id": "TD-002", "description": "Valid email, wrong password", "data": { "email": "user@test.com", "password": "WrongPass99!" } },
    { "id": "TD-003", "description": "Empty email, any password", "data": { "email": "", "password": "AnyPass1" } },
    { "id": "TD-004", "description": "Valid email, empty password", "data": { "email": "user@test.com", "password": "" } },
    { "id": "TD-005", "description": "Account with 4 prior failures (triggers lockout)", "data": { "email": "almostlocked@test.com", "password": "BadPass!", "prior_failed_attempts": 4 } },
    { "id": "TD-006", "description": "Account with 3 prior failures (no lockout yet)", "data": { "email": "user@test.com", "password": "BadPass!", "prior_failed_attempts": 3 } },
    { "id": "TD-007", "description": "SQL injection payload", "data": { "email": "' OR '1'='1' --", "password": "x" } }
  ]
}
--- END EXAMPLE ---
"""

# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────


def build_generate_prompt(
    requirement: str,
    input_type: str = "User Story",
    language: str = "English",
) -> str:
    """
    Build prompt hoàn chỉnh gửi LLM.

    Parameters
    ----------
    requirement : str  — nội dung requirement (có thể chứa nhiều user story/use case)
    input_type  : str  — "User Story" | "Use Case Spec" | "Natural Language"
    language    : str  — "English" | "Tiếng Việt"

    Note: min_cases đã bị bỏ — số TC được quyết định hoàn toàn bởi
    số lượng feature/criteria trong input, không có giới hạn cứng.
    """
    input_guide = _INPUT_TYPE_GUIDES.get(
        input_type, _INPUT_TYPE_GUIDES["Natural Language"]
    )

    lang_instruction = (
        "Write ALL human-readable fields in Vietnamese "
        "(title, precondition, steps, expected_result, db_expected, description). "
        "Keep JSON keys and enum values (SUCCESS / High / P / etc.) in English."
        if language == "Tiếng Việt"
        else "Write ALL human-readable fields in English."
    )

    return f"""You are a Senior QA Engineer with 10 years of experience in manual and automated testing.
Your task: read the software requirement below and generate a COMPLETE, EXHAUSTIVE test suite.

"Exhaustive" means:
  — Every feature mentioned must have test cases.
  — Every acceptance criterion maps to ≥1 dedicated test case.
  — Every boundary value, edge condition, and security risk is covered.
  — You may NOT summarise, skip, or merge cases to reduce the total count.
  — There is NO upper limit on the number of test cases.

════════════════════════════════════════════
MANDATORY REASONING  (run before writing JSON)
════════════════════════════════════════════
{_COT_INSTRUCTION}

════════════════════════════════════════════
INPUT FORMAT GUIDE
════════════════════════════════════════════
{input_guide}

════════════════════════════════════════════
COVERAGE REQUIREMENTS
════════════════════════════════════════════
{_COVERAGE_TYPES}

════════════════════════════════════════════
NON-NEGOTIABLE QUALITY RULES
════════════════════════════════════════════
1.  COMPLETENESS  : Every feature in the input MUST have its own test cases. No skipping.
2.  ONE-TO-ONE    : One acceptance criterion = one dedicated TC. No bundling.
3.  STEPS         : Each step is a concrete atomic action: "Click the Submit button" ✓ / "Submit form" ✗
4.  REAL DATA     : TD values must be real strings/numbers, never "<email>" or "YOUR_VALUE".
5.  BLANK FIELDS  : actual_result and status_result MUST be "" — do not fill them.
6.  NO UPPER LIMIT: Generate as many TCs as the input demands. 10 stories → expect 50–100+ TCs.
7.  LANGUAGE      : {lang_instruction}
8.  SELF-CHECK    : Before outputting JSON, re-read the full input and confirm nothing was missed.

════════════════════════════════════════════
FEW-SHOT EXAMPLE
════════════════════════════════════════════
{_FEW_SHOT_EXAMPLE}

════════════════════════════════════════════
OUTPUT FORMAT  (strict — no deviation)
════════════════════════════════════════════
{_OUTPUT_SCHEMA}

════════════════════════════════════════════
INPUT TO PROCESS
════════════════════════════════════════════
Input Type  : {input_type}
Requirement :
{requirement}
════════════════════════════════════════════
Produce the JSON now — no preamble, no explanation, only the JSON object:"""
