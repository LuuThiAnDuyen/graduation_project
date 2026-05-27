"""
core/llm_judge.py
------------------
LLM-as-a-Judge: dùng Gemini để đánh giá SEMANTIC quality của test cases.

Tại sao cần LLM Judge?
  Rule-based evaluator (tc_evaluator.py) chỉ đếm coverage_type labels —
  không phân biệt được:
    • TC "SQL injection in email" (tốt) vs TC chỉ có title "Security test" (kém)
    • Steps "Click Login button" (rõ) vs "Test login" (mơ hồ)
    • Expected result cụ thể vs expected result generic
  LLM Judge đọc nội dung thực tế và cho điểm có semantic.

Điểm quan trọng về chi phí:
  - Judge chỉ được gọi khi user explicitly bật (use_llm_judge=True)
  - Mặc định: rule-based (miễn phí, nhanh)
  - Judge mode: gọi thêm 1 Gemini call per variant (~2s)
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are an expert QA auditor. Evaluate the quality of the test suite below.

REQUIREMENT:
{requirement}

TEST CASES (sample of up to 15):
{tc_sample}

Evaluate on these 5 dimensions (0-100 each):

1. **semantic_coverage** (0-100):
   - Do TCs actually test what the requirement asks?
   - Are business rules properly covered?
   - Are edge cases SPECIFIC to this domain (not just generic)?

2. **step_clarity** (0-100):
   - Are steps atomic, concrete, executable by a human tester?
   - Penalize: "Fill in the form", "Test the feature", "Verify functionality"
   - Reward: "Enter 'admin@test.com' in the Email field", "Click the blue 'Submit' button"

3. **expected_result_quality** (0-100):
   - Are expected results observable and verifiable?
   - Penalize: "System works correctly", "Test passes"
   - Reward: "Error message 'Invalid email format' appears below the email field"

4. **test_data_realism** (0-100):
   - Are test data values realistic and domain-appropriate?
   - Penalize: "test@test.com", "password123", "abc", "foo"
   - Reward: "john.doe@company.vn", "P@ssw0rd!2024", "' OR 1=1--" for injection

5. **negative_case_quality** (0-100):
   - Do negative TCs test SPECIFIC failure modes or just "wrong input"?
   - Are error conditions precise? (e.g., "email missing @" vs just "invalid email")

Also provide:
- `strengths`: list of 2-3 specific strong points
- `weaknesses`: list of 2-3 specific weak points  
- `verdict`: 1-sentence summary recommendation

Return ONLY valid JSON:
{{
  "semantic_coverage": <int 0-100>,
  "step_clarity": <int 0-100>,
  "expected_result_quality": <int 0-100>,
  "test_data_realism": <int 0-100>,
  "negative_case_quality": <int 0-100>,
  "strengths": ["<point 1>", "<point 2>"],
  "weaknesses": ["<point 1>", "<point 2>"],
  "verdict": "<one sentence>"
}}"""


@dataclass
class LLMJudgeScore:
    semantic_coverage: int = 0
    step_clarity: int = 0
    expected_result_quality: int = 0
    test_data_realism: int = 0
    negative_case_quality: int = 0
    composite_score: float = 0.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    verdict: str = ""
    judge_available: bool = False

    def to_dict(self) -> dict:
        return {
            "semantic_coverage": self.semantic_coverage,
            "step_clarity": self.step_clarity,
            "expected_result_quality": self.expected_result_quality,
            "test_data_realism": self.test_data_realism,
            "negative_case_quality": self.negative_case_quality,
            "composite_score": round(self.composite_score, 1),
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "verdict": self.verdict,
        }


def _build_tc_sample(test_cases: list[dict], max_tc: int = 15) -> str:
    """Lấy sample TC đại diện: ưu tiên diversity về coverage_type."""
    if not test_cases:
        return "[]"

    seen_types: set[str] = set()
    selected: list[dict] = []

    # Round 1: lấy 1 TC đại diện mỗi type
    for tc in test_cases:
        ct = tc.get("coverage_type", "P")
        if ct not in seen_types:
            seen_types.add(ct)
            selected.append(tc)
        if len(selected) >= max_tc:
            break

    # Round 2: fill up
    for tc in test_cases:
        if len(selected) >= max_tc:
            break
        if tc not in selected:
            selected.append(tc)

    # Format cho judge
    lines = []
    for tc in selected:
        steps_str = "\n    ".join(
            f"{i+1}. {s}" for i, s in enumerate(tc.get("steps", []))
        )
        lines.append(
            f"[{tc.get('id')}] ({tc.get('coverage_type', '?')}/{tc.get('priority', '?')}) "
            f"{tc.get('title', '')}\n"
            f"  Precondition: {tc.get('precondition', '')[:100]}\n"
            f"  Steps:\n    {steps_str}\n"
            f"  Expected: {tc.get('expected_result', '')[:120]}\n"
            f"  TestData: {tc.get('test_data_ref', '')}\n"
        )
    return "\n---\n".join(lines)


def judge_test_cases(
    test_cases: list[dict],
    requirement: str,
    call_llm_fn=None,
) -> LLMJudgeScore:
    """
    Gọi LLM để đánh giá semantic quality của test cases.

    Parameters
    ----------
    test_cases   : danh sách TC đã sanitise
    requirement  : requirement gốc
    call_llm_fn  : function gọi LLM (mặc định dùng core.llm_client.call_llm)

    Returns
    -------
    LLMJudgeScore — nếu LLM không available, trả về score rỗng với judge_available=False
    """
    if not test_cases:
        return LLMJudgeScore(judge_available=False, verdict="No test cases to evaluate")

    if call_llm_fn is None:
        try:
            from core.llm_client import call_llm

            call_llm_fn = call_llm
        except ImportError:
            logger.error("llm_client not available")
            return LLMJudgeScore(judge_available=False)

    tc_sample = _build_tc_sample(test_cases, max_tc=15)
    prompt = _JUDGE_PROMPT.format(
        requirement=requirement[:2000],  # cap để tránh token overflow
        tc_sample=tc_sample,
    )

    try:
        raw = call_llm_fn(prompt)
        if raw is None or not isinstance(raw, dict):
            logger.warning("LLM Judge returned None or non-dict")
            return LLMJudgeScore(judge_available=False)

        scores = LLMJudgeScore(
            semantic_coverage=int(raw.get("semantic_coverage", 0)),
            step_clarity=int(raw.get("step_clarity", 0)),
            expected_result_quality=int(raw.get("expected_result_quality", 0)),
            test_data_realism=int(raw.get("test_data_realism", 0)),
            negative_case_quality=int(raw.get("negative_case_quality", 0)),
            strengths=raw.get("strengths", []),
            weaknesses=raw.get("weaknesses", []),
            verdict=raw.get("verdict", ""),
            judge_available=True,
        )
        # Weighted composite: semantic & step clarity quan trọng hơn
        scores.composite_score = (
            scores.semantic_coverage * 0.30
            + scores.step_clarity * 0.25
            + scores.expected_result_quality * 0.20
            + scores.test_data_realism * 0.15
            + scores.negative_case_quality * 0.10
        )
        logger.info(
            f"LLM Judge composite score: {scores.composite_score:.1f} "
            f"(sem={scores.semantic_coverage}, clarity={scores.step_clarity})"
        )
        return scores

    except Exception as exc:
        logger.error(f"LLM Judge failed: {exc}", exc_info=True)
        return LLMJudgeScore(judge_available=False)
