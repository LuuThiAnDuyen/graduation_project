"""
core/prompt_variants.py
-----------------------
Thư viện 5 prompt strategy được thiết kế theo hướng tăng dần mức độ cấu trúc:

  P1 – Basic Prompt         : Chỉ yêu cầu mô hình sinh test case từ yêu cầu phần mềm.
  P2 – Role-based Prompt    : Xác định vai trò mô hình là chuyên gia kiểm thử phần mềm.
  P3 – Step-by-step Prompt  : Hướng dẫn phân tích yêu cầu, xác định điều kiện kiểm thử,
                              dữ liệu đầu vào và kết quả mong đợi (CoT 6 bước + EP + BVA).
  P4 – Structured Output    : Yêu cầu đầu ra theo JSON có cấu trúc cụ thể + coverage checklist
                              đầy đủ (P/N/B/E/S/U/DB/INT) + Decision Table awareness.
  P5 – Full Prompt Framework: Kết hợp vai trò + phân tích 4 bước + coverage matrix đầy đủ
                              + few-shot example + Error Guessing list + self-check 10 điểm.

Mục tiêu nghiên cứu: So sánh chất lượng test case sinh ra theo từng mức độ cấu trúc prompt
để đánh giá ảnh hưởng của prompt engineering đến hiệu quả sinh test case tự động bằng LLMs.

Lý thuyết nền:
  - Boundary Value Analysis (BVA)  : Myers (1979) — test tại min-1, min, min+1, max-1, max, max+1
  - Equivalence Partitioning (EP)  : Myers (1979) — chia vùng, chỉ test 1 đại diện mỗi vùng
  - Decision Table Testing         : test tổ hợp nhiều điều kiện kết hợp
  - State Transition Testing       : test chuyển trạng thái hợp lệ và không hợp lệ
  - Use Case Testing               : test Basic Flow, Alternate Flow, Exception Flow
  - Error Guessing                 : kinh nghiệm tester — null, "null", emoji, SQLi, XSS, ...
  - Security Testing               : SQLi, XSS, IDOR, Auth Bypass, Privilege Escalation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# ── Fix: dùng Callable từ typing thay vì built-in callable (không phải type) ──
@dataclass
class PromptVariant:
    id: str
    name: str
    description: str
    tags: list[str]
    template_fn: Callable  # Callable[[str, str, str], str]


# ────────────────────────────────────────────────────────────────────────────
# SHARED BLOCKS — tái sử dụng trong tất cả các prompt
# ────────────────────────────────────────────────────────────────────────────

# ── Output JSON schema ────────────────────────────────────────────────────────
_OUTPUT_SCHEMA = """
Return ONLY valid JSON — no markdown fences, no text outside JSON:

{
  "status": "SUCCESS" | "INPUT_AMBIGUOUS" | "ERROR",
  "reason": "",
  "feature_name": "<≤8 words>",
  "test_cases": [
    {
      "id": "TC-001",
      "title": "<imperative verb phrase, e.g. Verify login succeeds with valid credentials>",
      "coverage_type": "P|N|B|E|S|U|DB|INT",
      "priority": "High|Medium|Low",
      "precondition": "<specific system state before execution — never just 'none'>",
      "steps": ["<atomic action 1>", "<atomic action 2>"],
      "element_locator": "<one snake_case UI element name per step, joined by \\n — N/A for non-UI steps>",
      "expected_result": "<observable, verifiable, specific outcome>",
      "actual_result": "",
      "status_result": "",
      "db_query": "<SQL verification query or empty string>",
      "db_expected": "<expected DB result description or empty string>",
      "test_data_ref": "TD-001 or empty"
    }
  ],
  "test_data_set": [
    {
      "id": "TD-001",
      "description": "<purpose of this data set>",
      "data": { "<field_name>": "<real concrete value — NEVER a placeholder>" }
    }
  ]
}

════ ELEMENT LOCATOR FORMAT ════
"element_locator" = one line per step, matching step order exactly, joined by \\n.
  • snake_case element names: email_input, password_input, login_button, error_message
  • Steps with NO UI interaction (navigate to URL, verify DB, check inbox): write N/A
  • Line count MUST equal step count — this is MANDATORY
  • Example for 4 steps: "N/A\\nemail_input\\npassword_input\\nlogin_button"
"""

# ── Coverage Matrix (BVA + EP + Decision Table + State Transition + Security) ─
_COVERAGE_MATRIX = """
Coverage types — apply ALL that are relevant. NEVER skip Security (S) or Boundary (B):

  P   = Positive / Happy-path
          → valid input, all required fields filled, expected flow completes successfully
          → Source: Use Case Testing — Basic Flow

  N   = Negative / Error-path
          → invalid format, missing required field, business rule violated → system rejects gracefully
          → Source: Equivalence Partitioning (EP) — invalid partition representative

  B   = Boundary Value (BVA — Myers 1979)
          → For EVERY numeric or length-limited field, test ALL 6 points:
            min-1 (FAIL) | min (PASS) | min+1 (PASS) | max-1 (PASS) | max (PASS) | max+1 (FAIL)
          → For string fields: boundary = character COUNT, not character value
          → For date fields: boundary = first valid date − 1 day, first valid date, last valid date, last valid date + 1 day

  E   = Edge Case / Error Guessing
          → empty string "", whitespace-only "   ", string "null", string "undefined"
          → leading/trailing spaces "  abc  ", very long string (>255 chars)
          → special characters !@#$%^&*()[], emoji 😀🔥, Unicode Ñ ñ ö ü
          → negative numbers, zero, decimal when integer expected
          → leap year date 29/02 on non-leap year → FAIL; on leap year → PASS
          → invalid calendar date 31/04 → FAIL (April has 30 days)

  S   = Security Testing
          → SQL Injection  : ' OR '1'='1' --   /   1; DROP TABLE users--   /   admin'--
          → XSS            : <script>alert('XSS')</script>   /   <img src=x onerror=alert(1)>
          → Auth Bypass    : access restricted URL directly without login → expect redirect/403
          → IDOR           : change resource ID in URL to access another user's data → expect 403
          → Privilege Esc. : perform admin action as regular user → expect 403

  U   = UX / Usability
          → label clarity, loading state visible, error message wording specific and helpful

  DB  = Database Integrity
          → data correctly saved / updated / deleted; no duplicate records created

  INT = Integration
          → correct interaction with email service, payment gateway, third-party APIs
"""

# ── BVA Quick Reference (injected into P3, P4, P5) ───────────────────────────
_BVA_REFERENCE = """
════ BVA QUICK REFERENCE (Boundary Value Analysis — Myers 1979) ════

Numeric field [min, max]:
  min-1 → FAIL  |  min → PASS  |  min+1 → PASS
  max-1 → PASS  |  max → PASS  |  max+1 → FAIL

String/text field [min_len, max_len] — boundary = character COUNT:
  min_len-1 chars → FAIL  |  min_len chars → PASS  |  min_len+1 chars → PASS
  max_len-1 chars → PASS  |  max_len chars → PASS  |  max_len+1 chars → FAIL

Date field [start_date, end_date]:
  start_date - 1 day → FAIL  |  start_date → PASS
  end_date → PASS             |  end_date + 1 day → FAIL
"""

# ── EP Quick Reference (injected into P3, P4, P5) ────────────────────────────
_EP_REFERENCE = """
════ EQUIVALENCE PARTITIONING (EP — Myers 1979) ════

Divide the input domain into partitions where all values in a partition
are expected to be handled the same way. Test ONE representative per partition.

Typical partitions for a text field (e.g. Email):
  Valid partition    : "user@example.com"        → PASS
  Missing @          : "userexample.com"          → FAIL
  Missing domain     : "user@"                    → FAIL
  Missing local part : "@example.com"             → FAIL
  With whitespace    : "user @example.com"        → FAIL
  Empty              : ""                         → FAIL

Rule: Do NOT test 100 variations of the same invalid partition.
      One representative per partition is sufficient.
      Use BVA to cover the exact boundaries between partitions.
"""

# ── Decision Table Reference (injected into P4, P5) ──────────────────────────
_DECISION_TABLE_REFERENCE = """
════ DECISION TABLE — when to apply ════

Use Decision Table testing when the feature outcome depends on
MULTIPLE CONDITIONS combined. List all condition combinations.

Example with 2 conditions (2² = 4 rules):
  C1: Email valid?  C2: Password correct?  →  Result
  Y               Y                       →  Login success
  Y               N                       →  "Invalid password" error
  N               Y                       →  "Email not found" error
  N               N                       →  "Email not found" (email checked first)

Rule: If N conditions exist → 2^N combinations maximum.
      Collapse equivalent rules when outcome is identical regardless of one condition.
"""

# ── State Transition Reference (injected into P5) ────────────────────────────
_STATE_TRANSITION_REFERENCE = """
════ STATE TRANSITION TESTING — when to apply ════

Use when the feature has a defined lifecycle (workflow states).
Test EVERY valid transition AND every invalid transition.

Example — Order lifecycle:
  [Draft] → [Placed] → [Processing] → [Shipping] → [Completed]
                                    ↘ [Cancelled]

Valid transitions to test   : Draft→Placed, Placed→Cancelled, Shipping→Completed
Invalid transitions to test : Shipping→Cancelled (should FAIL), Completed→Placed (should FAIL)
"""

# ── Error Guessing List (injected into P4, P5) ───────────────────────────────
_ERROR_GUESSING = """
════ ERROR GUESSING — high-risk input values ════

Always consider these values that commonly trigger bugs:

Numbers  : 0, -1, very large (999999999999), decimal when integer expected (1.5)
Strings  : "" (empty), " " (whitespace only), "  abc  " (leading/trailing spaces),
           "null" (string literal), "undefined" (JS bug trigger),
           "A" * 256 (extremely long), "DROP TABLE" (SQL),
           "<script>alert(1)</script>" (XSS), "' OR '1'='1'" (SQLi),
           "../../etc/passwd" (path traversal), "😀🔥🎉" (emoji), "Ñoño" (Unicode)
Emails   : "user+tag@example.com" (valid RFC 5321 but many systems reject),
           "user@localhost" (no TLD), " user@example.com" (leading space)
Dates    : 29/02 on non-leap year → FAIL; 29/02 on leap year → PASS;
           31/04 → FAIL (April has 30 days); 00/01/2024 → FAIL (day 0 invalid)
"""

# ── Shared Quality Rules ──────────────────────────────────────────────────────
_QUALITY_RULES = """
════ QUALITY RULES (mandatory for every test case) ════

  1. ATOMIC STEPS     : Each step = exactly ONE user action.
                        ✓ "Click the Login button"
                        ✗ "Fill in the form and submit"

  2. VERIFIABLE RESULT: Expected result must be specific and observable.
                        ✓ "Error message 'Invalid email format' appears in red below the Email field"
                        ✗ "System works correctly"

  3. REAL DATA        : Test data must be concrete real values — never placeholders.
                        ✓ "alice.nguyen@company.com"   ✗ "valid_email"
                        ✓ "' OR '1'='1' --"            ✗ "sql_injection_payload"

  4. NO DUPLICATION   : Each TC must test a DIFFERENT condition.
                        Never write two TCs with identical steps.

  5. BLANK FIELDS     : actual_result and status_result MUST always be empty string "".

  6. ELEMENT LOCATOR  : Line count of element_locator MUST equal step count exactly.
"""

# ── Language instruction map ──────────────────────────────────────────────────
_LANG = {
    "English": "Write ALL human-readable fields in English.",
    "Tiếng Việt": (
        "Viết tất cả các trường human-readable bằng Tiếng Việt "
        "(title, precondition, steps, expected_result, db_expected, description). "
        "Giữ JSON keys, enum values và element_locator element names bằng tiếng Anh (snake_case)."
    ),
}

# ── Few-shot example (P5 only) ────────────────────────────────────────────────
# Fix: escape sequences dùng raw string để tránh lỗi \\n trong JSON example
_FEW_SHOT_EXAMPLE = r"""
━━━ EXAMPLE OUTPUT (abbreviated — demonstrates expected quality level) ━━━
{
  "status": "SUCCESS",
  "reason": "",
  "feature_name": "User Login",
  "test_cases": [
    {
      "id": "TC-001",
      "title": "Verify login succeeds with valid credentials",
      "coverage_type": "P",
      "priority": "High",
      "precondition": "Registered user exists. No prior failed attempts. Browser at /login.",
      "steps": [
        "Navigate to /login",
        "Enter 'user@example.com' in the Email field",
        "Enter 'Pass@1234' in the Password field",
        "Click the Login button"
      ],
      "element_locator": "N/A\nemail_input\npassword_input\nlogin_button",
      "expected_result": "User is redirected to /dashboard. Header shows 'Welcome, User'. last_login timestamp updated in DB.",
      "actual_result": "",
      "status_result": "",
      "db_query": "SELECT last_login FROM users WHERE email='user@example.com';",
      "db_expected": "last_login equals current UTC timestamp (within 5 seconds)",
      "test_data_ref": "TD-001"
    },
    {
      "id": "TC-002",
      "title": "Verify login fails with incorrect password",
      "coverage_type": "N",
      "priority": "High",
      "precondition": "Registered user exists. failed_attempts = 0. Browser at /login.",
      "steps": [
        "Navigate to /login",
        "Enter 'user@example.com' in the Email field",
        "Enter 'WrongPass!' in the Password field",
        "Click the Login button"
      ],
      "element_locator": "N/A\nemail_input\npassword_input\nlogin_button",
      "expected_result": "Error toast appears: 'Invalid email or password'. User remains on /login. failed_attempts incremented to 1 in DB.",
      "actual_result": "",
      "status_result": "",
      "db_query": "SELECT failed_attempts FROM users WHERE email='user@example.com';",
      "db_expected": "failed_attempts = 1",
      "test_data_ref": "TD-002"
    },
    {
      "id": "TC-003",
      "title": "Verify SQL injection in email field is rejected",
      "coverage_type": "S",
      "priority": "High",
      "precondition": "Browser at /login. No active session.",
      "steps": [
        "Navigate to /login",
        "Enter \\\" OR '1'='1' -- in the Email field",
        "Enter 'x' in the Password field",
        "Click the Login button"
      ],
      "element_locator": "N/A\nemail_input\npassword_input\nlogin_button",
      "expected_result": "Login is rejected. No SQL error message exposed. Server returns HTTP 401 with generic error message.",
      "actual_result": "",
      "status_result": "",
      "db_query": "",
      "db_expected": "",
      "test_data_ref": "TD-003"
    },
    {
      "id": "TC-004",
      "title": "Verify account locks after 5 consecutive failed attempts (boundary max)",
      "coverage_type": "B",
      "priority": "High",
      "precondition": "User exists. failed_attempts = 4 (one attempt away from lockout). Browser at /login.",
      "steps": [
        "Navigate to /login",
        "Enter 'user@example.com' in the Email field",
        "Enter 'WrongAgain!' in the Password field",
        "Click the Login button"
      ],
      "element_locator": "N/A\nemail_input\npassword_input\nlogin_button",
      "expected_result": "Account is locked. Message: 'Account locked. Please reset your password.' Even correct password is rejected. is_locked=true in DB.",
      "actual_result": "",
      "status_result": "",
      "db_query": "SELECT is_locked FROM users WHERE email='user@example.com';",
      "db_expected": "is_locked = true",
      "test_data_ref": "TD-004"
    },
    {
      "id": "TC-005",
      "title": "Verify empty email field shows inline required error",
      "coverage_type": "E",
      "priority": "Medium",
      "precondition": "Browser at /login.",
      "steps": [
        "Navigate to /login",
        "Leave the Email field empty",
        "Enter 'AnyPass123' in the Password field",
        "Click the Login button"
      ],
      "element_locator": "N/A\nemail_input\npassword_input\nlogin_button",
      "expected_result": "Inline error 'Please fill out this field.' appears below the Email field. No API call is made.",
      "actual_result": "",
      "status_result": "",
      "db_query": "",
      "db_expected": "",
      "test_data_ref": "TD-005"
    }
  ],
  "test_data_set": [
    { "id": "TD-001", "description": "Valid registered credentials", "data": { "email": "user@example.com", "password": "Pass@1234" } },
    { "id": "TD-002", "description": "Wrong password for existing account", "data": { "email": "user@example.com", "password": "WrongPass!" } },
    { "id": "TD-003", "description": "SQL injection payload", "data": { "email": "' OR '1'='1' --", "password": "x" } },
    { "id": "TD-004", "description": "Account at lockout boundary (4 prior failures)", "data": { "email": "user@example.com", "password": "WrongAgain!" } },
    { "id": "TD-005", "description": "Empty email edge case", "data": { "email": "", "password": "AnyPass123" } }
  ]
}
━━━ END EXAMPLE ━━━
"""


# ────────────────────────────────────────────────────────────────────────────
# P1 – Basic Prompt
# Baseline tối giản: chỉ output schema, không có hướng dẫn gì thêm.
# Mục đích: đo năng lực cơ sở của LLM khi không có bất kỳ hướng dẫn nào.
# ────────────────────────────────────────────────────────────────────────────
def _p1(req: str, it: str, lang: str) -> str:
    return f"""Generate test cases for the following software requirement.

Language: {_LANG.get(lang, _LANG["English"])}

{_OUTPUT_SCHEMA}

Input Type : {it}
Requirement:
{req}

Output JSON:"""


# ────────────────────────────────────────────────────────────────────────────
# P2 – Role-based Prompt
# Thêm vai trò QA Expert. Không có hướng dẫn phân tích hay coverage checklist.
# Mục đích: đo xem role prompting đơn thuần có cải thiện so với P1 không.
# ────────────────────────────────────────────────────────────────────────────
def _p2(req: str, it: str, lang: str) -> str:
    return f"""You are an experienced Software Test Engineer with deep expertise in
software quality assurance and test case design.

Your job is to generate professional, thorough test cases from the given
software requirement. Apply your knowledge to cover the most important scenarios
— including happy paths, error paths, boundary values, and edge cases —
that users and testers would need to verify this feature works correctly.

Language: {_LANG.get(lang, _LANG["English"])}

{_OUTPUT_SCHEMA}

Input Type : {it}
Requirement:
{req}

Output JSON:"""


# ────────────────────────────────────────────────────────────────────────────
# P3 – Step-by-step Prompt (Chain-of-Thought)
# CoT 6 bước + BVA reference + EP reference + quality rules.
# Mục đích: đo xem CoT reasoning có cải thiện coverage và chất lượng TC không.
# ────────────────────────────────────────────────────────────────────────────
def _p3(req: str, it: str, lang: str) -> str:
    return f"""You are a Software Test Engineer. Before writing any test case,
analyze the requirement by following ALL 6 steps in order:

Step 1 — READ & UNDERSTAND
  • Read the requirement carefully. Identify every functional feature described.
  • Note all business rules, constraints, and acceptance criteria.

Step 2 — IDENTIFY FEATURES & ACTORS
  • List each distinct feature (F1, F2, ...).
  • For each feature: Who performs it? What inputs are involved?
    What outputs/state changes are expected?

Step 3 — EQUIVALENCE PARTITIONING (EP)
  • For each input field, divide into partitions: valid, invalid (each invalid type = own partition).
  • Test ONE representative value per partition — do not test 10 variations of the same error.
  • Combine EP with BVA to pinpoint exact boundaries between partitions.

{_EP_REFERENCE}

Step 4 — BOUNDARY VALUE ANALYSIS (BVA)
  • For EVERY numeric or length-limited field, generate ALL 6 boundary test points.
  • For string fields: boundary = character COUNT, not character value.

{_BVA_REFERENCE}

Step 5 — SECURITY & EDGE CASES
  • Does any text field accept free input? → must have SQLi AND XSS test cases.
  • Is any action restricted by role/auth? → must have auth-bypass test case.
  • Apply Error Guessing: empty string, "null" string, whitespace-only, emoji, Unicode,
    leading/trailing spaces, extremely long input (>255 chars).

Step 6 — WRITE TEST CASES
  • One condition = one test case. Steps must be atomic — one action per step.
  • Expected result must be specific and observable (not "system works correctly").
  • Fill ALL fields in the JSON schema below. actual_result and status_result = "".

{_QUALITY_RULES}

Language: {_LANG.get(lang, _LANG["English"])}

{_OUTPUT_SCHEMA}

Input Type : {it}
Requirement:
{req}

Output JSON:"""


# ────────────────────────────────────────────────────────────────────────────
# P4 – Structured Output Prompt
# Ràng buộc JSON chặt + coverage checklist đầy đủ + Decision Table awareness
# + BVA/EP/Error Guessing reference. Không có CoT step-by-step.
# Mục đích: đo xem output constraint + checklist có đủ để đảm bảo coverage không.
# ────────────────────────────────────────────────────────────────────────────
def _p4(req: str, it: str, lang: str) -> str:
    return f"""Generate test cases for the following software requirement.

════ OUTPUT STRUCTURE (MANDATORY) ════
Your output MUST be a valid JSON object. For EACH test case include ALL fields:

  id              : unique sequential identifier (TC-001, TC-002, …)
  title           : short imperative phrase — "Verify X when Y"
  coverage_type   : EXACTLY one of: P | N | B | E | S | U | DB | INT
  priority        : High | Medium | Low
  precondition    : specific system state before execution (never just "none")
  steps           : list of ATOMIC actions — ONE user action per step
  element_locator : snake_case UI element per step joined by \\n (N/A for non-UI)
  expected_result : specific observable outcome — not "system works"
  actual_result   : always ""
  status_result   : always ""
  db_query        : SQL to verify DB state (or "")
  db_expected     : expected DB result description (or "")
  test_data_ref   : TD reference (or "")

════ MANDATORY COVERAGE CHECKLIST ════
Your test suite MUST include at least one test case for EACH item:

  ☐ [P]   At least 1 Positive/Happy-path TC for EACH main feature flow
  ☐ [N]   At least 1 Negative TC per required field (empty input, wrong format)
  ☐ [B]   At least 1 Boundary TC per numeric/length field
            → test ALL 6 points: min-1(FAIL), min(PASS), min+1(PASS), max-1(PASS), max(PASS), max+1(FAIL)
            → for string fields: boundary = character COUNT
  ☐ [E]   At least 1 Edge Case TC: empty string, whitespace-only, "null" string, emoji, >255 chars
  ☐ [S]   At least 1 SQLi TC per free-text input field
  ☐ [S]   At least 1 XSS TC per free-text input field
  ☐ [S]   At least 1 Auth Bypass TC for every restricted action
  ☐ [DB]  At least 1 DB Integrity TC verifying correct persistence
  ☐ [DT]  If feature has multiple conditions: cover key combinations (Decision Table approach)

{_BVA_REFERENCE}

{_EP_REFERENCE}

{_ERROR_GUESSING}

{_DECISION_TABLE_REFERENCE}

════ COVERAGE TYPES ════
{_COVERAGE_MATRIX}

{_QUALITY_RULES}

════ TEST DATA ════
  • Include a test_data_set array. Each TD entry must have concrete real values.
  • NEVER use placeholders: "valid_email", "test_value", "your_input" are FORBIDDEN.
  • Use realistic values: "alice@company.com", "' OR '1'='1' --", "A" × 256.

Language: {_LANG.get(lang, _LANG["English"])}

{_OUTPUT_SCHEMA}

Input Type : {it}
Requirement:
{req}

Output JSON:"""


# ────────────────────────────────────────────────────────────────────────────
# P5 – Full Prompt Framework
# Role + CoT 4 bước + coverage matrix + BVA/EP/DT/ST/Error Guessing +
# few-shot example + self-check 10 điểm.
# Best practice prompt engineering — phản ánh đầy đủ lý thuyết kiểm thử.
# ────────────────────────────────────────────────────────────────────────────
def _p5(req: str, it: str, lang: str) -> str:
    return f"""You are a Senior QA Engineer with 10+ years of experience designing
test suites for web, mobile, and API systems across fintech, e-commerce,
and enterprise domains.

Your task: Generate a COMPLETE, PRODUCTION-QUALITY test suite from the requirement below.
Missing a Security, Boundary, or Decision Table test case is a DEFECT in your work.

{_FEW_SHOT_EXAMPLE}

━━━ MANDATORY ANALYSIS FRAMEWORK ━━━
Execute ALL 4 steps internally BEFORE writing any JSON.

STEP 1 — FEATURE DECOMPOSITION
  For each distinct functional feature, identify:
    • Actor            : who performs the action
    • Inputs           : fields, parameters, data types, constraints
    • Business rules   : validation rules, limits, workflow conditions
    • Success outcome  : what happens on the happy path
    • Failure outcomes : what happens on EACH distinct error path

STEP 2 — EXHAUSTIVE TEST CONDITIONS
  Apply ALL of the following techniques for each feature:

  ► POSITIVE (P)      : Every valid input combination → should succeed.
                        Source: EP valid partition + Use Case Basic Flow.

  ► NEGATIVE (N)      : Every required field blank → specific error message.
                        Every field with wrong format → specific error message.
                        Every business rule violated → specific rejection message.
                        Source: EP invalid partitions (one TC per invalid partition).

  ► BOUNDARY (BVA)    : For EVERY numeric or length-limited field, generate ALL 6 points:
                        min-1(FAIL) | min(PASS) | min+1(PASS) | max-1(PASS) | max(PASS) | max+1(FAIL)
                        For STRING fields: boundary = character COUNT.
                        For DATE fields: boundary = day before start, start date, end date, day after end.

  ► EDGE CASE (E)     : Apply Error Guessing — values that commonly trigger bugs:
                        "" (empty), " " (whitespace), "null" (string), "undefined",
                        "  abc  " (leading/trailing spaces), "A"×256 (very long),
                        emoji 😀🔥, Unicode Ñ ö ü, negative numbers, decimal for integer fields.

  ► SECURITY (S)      : For EVERY free-text input:
                          SQLi  : ' OR '1'='1' --   /   1; DROP TABLE users--
                          XSS   : <script>alert('XSS')</script>   /   <img src=x onerror=alert(1)>
                        For EVERY restricted action:
                          Auth Bypass : access URL directly without login → expect 401/redirect
                          IDOR        : change resource ID to another user's → expect 403
                          Priv. Esc.  : perform admin action as regular user → expect 403

  ► DECISION TABLE    : If feature outcome depends on ≥2 conditions simultaneously,
                        enumerate the key condition combinations (2^N rules, collapse equivalent).

  ► STATE TRANSITION  : If feature has a workflow (states + events), test:
                        every VALID transition AND every INVALID transition.

  ► DATABASE (DB)     : Verify data is correctly saved, updated, deleted.
                        Verify no duplicate records created on repeated submission.

  ► INTEGRATION (INT) : Verify interactions with email service, payment gateway, external APIs.

{_BVA_REFERENCE}

{_EP_REFERENCE}

{_DECISION_TABLE_REFERENCE}

{_STATE_TRANSITION_REFERENCE}

{_ERROR_GUESSING}

STEP 3 — TEST DATA ASSIGNMENT
  • Create one TD entry per distinct data scenario.
  • REAL values only — never placeholders:
      ✓ "alice.nguyen@company.com"   ✗ "valid_email"
      ✓ "' OR '1'='1' --"           ✗ "sql_injection"
      ✓ "A" × 256                   ✗ "very_long_string"

STEP 4 — MANDATORY SELF-CHECK (verify BEFORE writing JSON)
  □ Every feature has ≥1 Positive TC?
  □ Every required field has ≥1 Negative TC (empty + wrong format)?
  □ Every numeric/length field has BVA TCs for ALL 6 boundary points?
  □ Every free-text input has SQLi AND XSS Security TCs?
  □ Every restricted action has an Auth Bypass Security TC?
  □ Multi-condition features have Decision Table combinations covered?
  □ Workflow features have valid AND invalid State Transition TCs?
  □ Every TC has specific, observable expected_result (not "system works")?
  □ Every TC has concrete test data (no placeholders)?
  □ actual_result = "" and status_result = "" in every TC?
  □ element_locator line count = step count in every TC?
  □ No two TCs have identical steps?

━━━ COVERAGE MATRIX ━━━
{_COVERAGE_MATRIX}

━━━ QUALITY RULES ━━━
{_QUALITY_RULES}

━━━ FEATURE NAME RULE ━━━
  • feature_name = the MODULE or SCREEN name (e.g. "User Login", "Password Reset").
  • NEVER use outcome words: "Login Success", "Login Failure", "Positive Tests" are WRONG.

━━━ OUTPUT FORMAT ━━━
{_OUTPUT_SCHEMA}

Language: {_LANG.get(lang, _LANG["English"])}

Input Type : {it}
Requirement:
{req}

Now execute the 4-step analysis, then output the JSON:"""


# ────────────────────────────────────────────────────────────────────────────
# Registry
# ────────────────────────────────────────────────────────────────────────────

VARIANTS: list[PromptVariant] = [
    PromptVariant(
        id="p1_basic",
        name="P1 – Basic",
        description=(
            "Chỉ yêu cầu mô hình sinh test case từ yêu cầu phần mềm. "
            "Không có hướng dẫn vai trò, phân tích hay định dạng. "
            "Baseline tối giản nhất để đo mức độ cơ sở của LLM."
        ),
        tags=["basic", "baseline", "minimal", "no-guidance"],
        template_fn=_p1,
    ),
    PromptVariant(
        id="p2_role_based",
        name="P2 – Role-based",
        description=(
            "Xác định vai trò mô hình là chuyên gia kiểm thử phần mềm có kinh nghiệm. "
            "Không hướng dẫn thêm về phân tích hay coverage. "
            "Kiểm tra xem role prompting đơn thuần có cải thiện chất lượng TC không."
        ),
        tags=["role-based", "persona", "expert-role"],
        template_fn=_p2,
    ),
    PromptVariant(
        id="p3_step_by_step",
        name="P3 – Step-by-step",
        description=(
            "CoT 6 bước: đọc hiểu → feature → EP (Equivalence Partitioning) → "
            "BVA (Boundary Value Analysis) → Security + Error Guessing → viết TC. "
            "Inject đầy đủ BVA reference (6 điểm biên) và EP reference."
        ),
        tags=["step-by-step", "chain-of-thought", "bva", "ep", "security"],
        template_fn=_p3,
    ),
    PromptVariant(
        id="p4_structured_output",
        name="P4 – Structured Output",
        description=(
            "Ràng buộc chặt JSON đầu ra + coverage checklist bắt buộc "
            "(P/N/B/E/S/DB/DT) + inject BVA 6 điểm + EP + Decision Table + Error Guessing. "
            "Không có CoT step-by-step — chỉ ràng buộc đầu ra và checklist."
        ),
        tags=[
            "structured-output",
            "json-format",
            "coverage-checklist",
            "bva",
            "ep",
            "decision-table",
            "error-guessing",
        ],
        template_fn=_p4,
    ),
    PromptVariant(
        id="p5_full_framework",
        name="P5 – Full Framework",
        description=(
            "Kết hợp đầy đủ: vai trò Senior QA Engineer + CoT 4 bước "
            "(feature decomposition → test conditions → test data → self-check 12 điểm) "
            "+ BVA 6 điểm + EP + Decision Table + State Transition + Error Guessing "
            "+ few-shot example chất lượng cao + coverage matrix đầy đủ (P/N/B/E/S/U/DB/INT). "
            "Prompt hoàn chỉnh nhất, phản ánh đầy đủ lý thuyết kiểm thử phần mềm."
        ),
        tags=[
            "full-framework",
            "role",
            "chain-of-thought",
            "bva",
            "ep",
            "decision-table",
            "state-transition",
            "error-guessing",
            "security",
            "few-shot",
            "self-check",
        ],
        template_fn=_p5,
    ),
]

VARIANT_MAP: dict[str, PromptVariant] = {v.id: v for v in VARIANTS}

PRESET_GROUPS: dict[str, dict] = {
    "quick_3": {
        "name": "Quick Compare (3 variants)",
        "description": "P1 Basic + P3 Step-by-step + P5 Full — so sánh 3 mức độ cấu trúc đại diện",
        "variants": ["p1_basic", "p3_step_by_step", "p5_full_framework"],
    },
    "incremental_4": {
        "name": "Incremental (4 variants)",
        "description": "P1 → P2 → P3 → P5 — quan sát sự cải thiện dần theo mức độ cấu trúc",
        "variants": [
            "p1_basic",
            "p2_role_based",
            "p3_step_by_step",
            "p5_full_framework",
        ],
    },
    "output_focus": {
        "name": "Output Focus (3 variants)",
        "description": "P2 Role + P4 Structured Output + P5 Full — so sánh ảnh hưởng của định dạng đầu ra",
        "variants": ["p2_role_based", "p4_structured_output", "p5_full_framework"],
    },
    "all_5": {
        "name": "Full Lab (5 variants)",
        "description": "Chạy tất cả 5 variants P1→P5 — đầy đủ nhất cho nghiên cứu so sánh",
        "variants": [v.id for v in VARIANTS],
    },
}


def get_variant(vid: str) -> PromptVariant | None:
    """Trả về PromptVariant theo id, hoặc None nếu không tìm thấy."""
    return VARIANT_MAP.get(vid)


def build_prompt(
    variant_id: str,
    requirement: str,
    input_type: str = "User Story",
    language: str = "English",
) -> str:
    """Xây dựng prompt hoàn chỉnh từ variant id và requirement."""
    v = get_variant(variant_id)
    if v is None:
        valid = ", ".join(VARIANT_MAP.keys())
        raise ValueError(f"Unknown variant: '{variant_id}'. Valid options: {valid}")
    return v.template_fn(requirement, input_type, language)
