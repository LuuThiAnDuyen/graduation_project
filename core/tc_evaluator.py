"""
core/tc_evaluator.py
---------------------
Đánh giá chất lượng test cases theo 6 chiều rule-based + LLM Judge tuỳ chọn.

Thay đổi so với v2:
  • Thêm DimensionWeightConfig — user có thể tuỳ chỉnh trọng số 6 chiều
  • DEFAULT_WEIGHTS và WEIGHT_PRESETS cho các use-case phổ biến
  • evaluate() nhận weights: DimensionWeightConfig | None
  • Tên dimension đổi: "Step Specificity" → "Clarity", "Completeness (Heuristic)" → "Requirement Traceability"
"""

from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── Dimension weight config ────────────────────────────────────────────────────

DIMENSION_KEYS = [
    "coverage_breadth",
    "clarity",
    "test_data_quality",
    "security_coverage",
    "boundary_edge_coverage",
    "requirement_traceability",
]

DIMENSION_LABELS = {
    "coverage_breadth": "Coverage Breadth",
    "clarity": "Clarity",
    "test_data_quality": "Test Data Quality",
    "security_coverage": "Security Coverage",
    "boundary_edge_coverage": "Boundary & Edge Coverage",
    "requirement_traceability": "Requirement Traceability",
}

DIMENSION_DESCRIPTIONS = {
    "coverage_breadth": "Đủ scenarios và coverage types chưa? (P/N/B/E/S)",
    "clarity": "TC có rõ ràng, dễ đọc, dễ thực thi không?",
    "test_data_quality": "Test data đủ, cụ thể, không có placeholder?",
    "security_coverage": "Đã cover SQL Injection, XSS, Auth-bypass?",
    "boundary_edge_coverage": "Đã xét boundary và edge case?",
    "requirement_traceability": "TC có link về requirement/ticket/AC không?",
}


@dataclass
class DimensionWeightConfig:
    """
    Trọng số cho 6 chiều đánh giá. Tổng phải = 1.0 (tự động normalize).

    Attributes
    ----------
    coverage_breadth         : float
    clarity                  : float
    test_data_quality        : float
    security_coverage        : float
    boundary_edge_coverage   : float
    requirement_traceability : float
    """

    coverage_breadth: float = 0.20
    clarity: float = 0.20
    test_data_quality: float = 0.15
    security_coverage: float = 0.20
    boundary_edge_coverage: float = 0.15
    requirement_traceability: float = 0.10

    def normalize(self) -> "DimensionWeightConfig":
        """Normalize sao cho tổng = 1.0"""
        total = (
            self.coverage_breadth
            + self.clarity
            + self.test_data_quality
            + self.security_coverage
            + self.boundary_edge_coverage
            + self.requirement_traceability
        )
        if total <= 0:
            return DimensionWeightConfig()
        factor = 1.0 / total
        return DimensionWeightConfig(
            coverage_breadth=self.coverage_breadth * factor,
            clarity=self.clarity * factor,
            test_data_quality=self.test_data_quality * factor,
            security_coverage=self.security_coverage * factor,
            boundary_edge_coverage=self.boundary_edge_coverage * factor,
            requirement_traceability=self.requirement_traceability * factor,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            DIMENSION_LABELS["coverage_breadth"]: self.coverage_breadth,
            DIMENSION_LABELS["clarity"]: self.clarity,
            DIMENSION_LABELS["test_data_quality"]: self.test_data_quality,
            DIMENSION_LABELS["security_coverage"]: self.security_coverage,
            DIMENSION_LABELS["boundary_edge_coverage"]: self.boundary_edge_coverage,
            DIMENSION_LABELS["requirement_traceability"]: self.requirement_traceability,
        }


# ── Preset weight profiles ─────────────────────────────────────────────────────

WEIGHT_PRESETS: dict[str, dict] = {
    "balanced": {
        "label": "Balanced",
        "description": "Phân bổ đều — phù hợp hầu hết project",
        "icon": "ti-scale",
        "config": DimensionWeightConfig(
            coverage_breadth=0.20,
            clarity=0.20,
            test_data_quality=0.15,
            security_coverage=0.20,
            boundary_edge_coverage=0.15,
            requirement_traceability=0.10,
        ),
    },
    "security_first": {
        "label": "Security-first",
        "description": "Fintech, Healthcare, Banking",
        "icon": "ti-shield-lock",
        "config": DimensionWeightConfig(
            coverage_breadth=0.15,
            clarity=0.10,
            test_data_quality=0.10,
            security_coverage=0.40,
            boundary_edge_coverage=0.15,
            requirement_traceability=0.10,
        ),
    },
    "startup_speed": {
        "label": "Startup / Speed",
        "description": "MVP, startup — tập trung coverage & clarity",
        "icon": "ti-rocket",
        "config": DimensionWeightConfig(
            coverage_breadth=0.30,
            clarity=0.30,
            test_data_quality=0.10,
            security_coverage=0.10,
            boundary_edge_coverage=0.10,
            requirement_traceability=0.10,
        ),
    },
    "compliance": {
        "label": "Compliance / Enterprise",
        "description": "Audit, ISO, enterprise — traceability cao",
        "icon": "ti-certificate",
        "config": DimensionWeightConfig(
            coverage_breadth=0.15,
            clarity=0.15,
            test_data_quality=0.15,
            security_coverage=0.15,
            boundary_edge_coverage=0.10,
            requirement_traceability=0.30,
        ),
    },
}

DEFAULT_WEIGHTS = WEIGHT_PRESETS["balanced"]["config"]


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class DimensionScore:
    name: str
    score: float  # 0.0 – 1.0
    max_score: float = 1.0
    details: str = ""
    issues: list[str] = field(default_factory=list)

    @property
    def percentage(self) -> int:
        return int(self.score * 100)


@dataclass
class EvaluationResult:
    variant_id: str
    variant_name: str
    total_tc: int
    total_td: int
    dimensions: list[DimensionScore]
    overall_score: float
    grade: str
    strengths: list[str]
    weaknesses: list[str]
    recommendation: str
    weights_used: DimensionWeightConfig = field(default_factory=lambda: DEFAULT_WEIGHTS)
    raw_tc_list: list[dict] = field(default_factory=list)

    # LLM Judge (optional — chỉ có nếu use_llm_judge=True)
    llm_judge_score: object | None = None
    hybrid_score: float | None = None
    hybrid_grade: str | None = None

    # Error Analysis (optional — chỉ có nếu use_error_analysis=True)
    error_report: object | None = None  # ErrorReport | None

    @property
    def score_display(self) -> str:
        if self.hybrid_score is not None:
            return f"{self.hybrid_score:.1f}/100 (hybrid)"
        return f"{self.overall_score:.1f}/100"

    @property
    def grade_color(self) -> str:
        g = self.hybrid_grade or self.grade
        return {
            "A": "#22c55e",
            "B": "#84cc16",
            "C": "#f59e0b",
            "D": "#f97316",
            "F": "#ef4444",
        }.get(g, "#6b7280")


# ── Regex patterns ────────────────────────────────────────────────────────────

_PLACEHOLDER = re.compile(
    r"<[a-zA-Z_]+>|YOUR_VALUE|PLACEHOLDER|example\.com|foo@bar|test@test",
    re.IGNORECASE,
)

_VAGUE_STEP = re.compile(
    r"^(submit form|fill form|fill in|enter data|test the|verify that|"
    r"check if|click button|perform action|do the test|run test|"
    r"test (?:login|register|feature|functionality)|validate input|"
    r"navigate to page|go to website)$",
    re.IGNORECASE,
)

_GENERIC_EXPECTED = re.compile(
    r"^(test pass(es)?|system works?( correctly)?|success|ok|"
    r"everything works?|no error(s)?|works? as expected|"
    r"(the )?system (should )?(work|function|respond) correctly)$",
    re.IGNORECASE,
)

# Patterns để detect requirement traceability
_TRACE_REF = re.compile(
    r"(?:"
    r"[A-Z]+-\d+"  # Jira: PROJECT-123
    r"|#\d+"  # GitHub: #456
    r"|AC[-\s]?\d+"  # AC-1, AC 2
    r"|TC[-\s]?\d+"  # TC-001
    r"|REQ[-\s]?\d+"  # REQ-001
    r"|US[-\s]?\d+"  # US-01
    r"|Story\s*#?\d+"  # Story 1
    r"|https?://\S+"  # URL link to ticket
    r")",
    re.IGNORECASE,
)


# ── Dimension scorers ─────────────────────────────────────────────────────────


def _score_coverage(tcs: list[dict]) -> DimensionScore:
    required = {"P", "N", "B", "E", "S"}
    found = {tc.get("coverage_type", "").upper() for tc in tcs}
    present = required & found
    missing = required - found
    score = len(present) / len(required)
    bonus_types = {"DB", "INT", "U"} & found
    score = min(score + 0.1 * len(bonus_types), 1.0)
    issues = [f"Thiếu coverage type: {t}" for t in sorted(missing)]
    details = (
        f"Có: {', '.join(sorted(present)) or 'không'}  |  "
        f"Thiếu: {', '.join(sorted(missing)) or 'không'}  |  "
        f"Bonus: {', '.join(sorted(bonus_types)) or 'không'}"
    )
    return DimensionScore(
        DIMENSION_LABELS["coverage_breadth"],
        score,
        details=details,
        issues=issues,
    )


def _score_clarity(tcs: list[dict]) -> DimensionScore:
    """
    Đánh giá tính rõ ràng và dễ thực thi của TC.
    Bao gồm: độ cụ thể của steps, chất lượng expected result,
    tính đầy đủ của precondition và title.
    """
    issues = []
    vague = short = generic_exp = no_precondition = unclear_title = total = 0

    for tc in tcs:
        steps = tc.get("steps", [])
        if not steps:
            issues.append(f"{tc.get('id')}: không có steps")
            continue
        for s in steps:
            total += 1
            stripped = s.strip()
            if len(stripped) < 15:
                short += 1
            if _VAGUE_STEP.match(stripped):
                vague += 1

        exp = (tc.get("expected_result") or "").strip()
        if _GENERIC_EXPECTED.match(exp):
            generic_exp += 1

        # Precondition check
        pre = (tc.get("precondition") or "").strip()
        if not pre or pre.lower() in ("n/a", "none", "–", "-", ""):
            no_precondition += 1

        # Title clarity: quá ngắn hoặc generic
        title = (tc.get("title") or "").strip()
        if len(title) < 10 or title.lower().startswith("test "):
            unclear_title += 1

    if total == 0:
        return DimensionScore(
            DIMENSION_LABELS["clarity"],
            0.0,
            issues=["Không có steps nào"],
        )

    n = max(len(tcs), 1)
    step_ratio = (vague + short) / total
    exp_penalty = generic_exp / n * 0.20
    pre_penalty = no_precondition / n * 0.10
    title_penalty = unclear_title / n * 0.10

    score = max(0.0, 1.0 - step_ratio * 1.5 - exp_penalty - pre_penalty - title_penalty)

    too_few = sum(1 for tc in tcs if len(tc.get("steps", [])) < 2)
    score = max(0.0, min(1.0, score - 0.1 * (too_few / n)))

    if vague:
        issues.append(f"{vague} steps quá mơ hồ (e.g. 'Fill form', 'Submit')")
    if generic_exp:
        issues.append(
            f"{generic_exp} expected results quá chung chung (e.g. 'System works correctly')"
        )
    if no_precondition > n * 0.5:
        issues.append(f"{no_precondition} TC thiếu precondition")
    if unclear_title:
        issues.append(f"{unclear_title} TC có title ngắn hoặc generic")

    details = (
        f"Total steps: {total}  |  Vague/short: {vague + short}  |  "
        f"TCs <2 steps: {too_few}  |  Generic expected: {generic_exp}  |  "
        f"No precondition: {no_precondition}  |  Unclear title: {unclear_title}"
    )
    return DimensionScore(
        DIMENSION_LABELS["clarity"],
        score,
        details=details,
        issues=issues,
    )


def _score_data_quality(tcs: list[dict], tds: list[dict]) -> DimensionScore:
    issues = []
    tc_need = [
        tc
        for tc in tcs
        if tc.get("coverage_type") in ("P", "N", "B", "S")
        and not tc.get("test_data_ref")
    ]
    missing_ratio = len(tc_need) / max(len(tcs), 1)
    placeholder_n = sum(1 for td in tds if _PLACEHOLDER.search(str(td.get("data", {}))))
    for td in tds:
        if _PLACEHOLDER.search(str(td.get("data", {}))):
            issues.append(f"{td.get('id')}: chứa placeholder values")
    placeholder_ratio = placeholder_n / max(len(tds), 1)
    td_coverage = min(len(tds) / max(len(tcs) * 0.5, 1), 1.0)
    score = (
        0.4 * (1 - missing_ratio) + 0.4 * (1 - placeholder_ratio) + 0.2 * td_coverage
    )
    if missing_ratio > 0.3:
        issues.append(f"{len(tc_need)} TC cần data nhưng không có test_data_ref")
    details = (
        f"TD entries: {len(tds)}  |  TC thiếu ref: {len(tc_need)}  |  "
        f"TD có placeholder: {placeholder_n}"
    )
    return DimensionScore(
        DIMENSION_LABELS["test_data_quality"],
        score,
        details=details,
        issues=issues,
    )


def _score_security(tcs: list[dict]) -> DimensionScore:
    sec = [tc for tc in tcs if tc.get("coverage_type") == "S"]
    if not sec:
        return DimensionScore(
            DIMENSION_LABELS["security_coverage"],
            0.0,
            details="Không có TC nào loại S",
            issues=["Thiếu hoàn toàn security TCs"],
        )
    has_sqli = any(
        "sql" in str(tc).lower() or "inject" in str(tc).lower() for tc in sec
    )
    has_xss = any("xss" in str(tc).lower() or "script" in str(tc).lower() for tc in sec)
    has_auth = any(
        "auth" in str(tc).lower()
        or "bypass" in str(tc).lower()
        or "unauthorized" in str(tc).lower()
        for tc in sec
    )
    variety = sum([has_sqli, has_xss, has_auth]) / 3.0
    quantity = min(len(sec) / max(len(tcs), 1) / 0.15, 1.0)
    score = 0.5 * quantity + 0.5 * variety
    issues = (
        (["Thiếu SQL Injection TC"] if not has_sqli else [])
        + (["Thiếu XSS TC"] if not has_xss else [])
        + (["Thiếu auth-bypass TC"] if not has_auth else [])
    )
    details = (
        f"Security TCs: {len(sec)}  |  "
        f"SQLi: {'✓' if has_sqli else '✗'}  "
        f"XSS: {'✓' if has_xss else '✗'}  "
        f"Auth-bypass: {'✓' if has_auth else '✗'}"
    )
    return DimensionScore(
        DIMENSION_LABELS["security_coverage"],
        score,
        details=details,
        issues=issues,
    )


def _score_boundary(tcs: list[dict]) -> DimensionScore:
    b = [tc for tc in tcs if tc.get("coverage_type") == "B"]
    e = [tc for tc in tcs if tc.get("coverage_type") == "E"]
    be_count = len(b) + len(e)
    ratio = be_count / max(len(tcs), 1)
    score = min(ratio / 0.20, 1.0)
    issues = (
        ["Không có Boundary hoặc Edge TCs"]
        if be_count == 0
        else ([f"Ít boundary/edge TCs ({be_count}/{len(tcs)})"] if ratio < 0.10 else [])
    )
    details = f"Boundary TCs: {len(b)}  |  Edge TCs: {len(e)}  |  Tỉ lệ: {ratio:.0%}"
    return DimensionScore(
        DIMENSION_LABELS["boundary_edge_coverage"],
        score,
        details=details,
        issues=issues,
    )


def _score_traceability(tcs: list[dict], requirement: str) -> DimensionScore:
    """
    Đánh giá Requirement Traceability:
    - TC có reference về ticket/AC/story ID không?
    - Estimate coverage dựa trên AC/criteria trong requirement
    - Phát hiện duplicate (title + content)
    """
    issues = []

    # --- Traceability: TC có ref về requirement không ---
    traced = sum(
        1
        for tc in tcs
        if _TRACE_REF.search(str(tc.get("test_data_ref") or ""))
        or _TRACE_REF.search(str(tc.get("title") or ""))
        or _TRACE_REF.search(str(tc.get("id") or ""))
        or any(_TRACE_REF.search(s) for s in tc.get("steps", []))
    )
    trace_ratio = traced / max(len(tcs), 1)

    # --- Quantity estimation vs requirement ---
    criterion_hints = len(
        re.findall(
            r"(?:^|\n)\s*[-•*]|\b(?:AC|acceptance criteria|criterion|requirement)\b|\d+\.",
            requirement,
            re.IGNORECASE,
        )
    )
    story_hints = len(
        re.findall(
            r"\b(?:as a|i want|use case|feature|story)\b",
            requirement,
            re.IGNORECASE,
        )
    )
    estimated_features = max(story_hints, 1)
    estimated_criteria = max(criterion_hints, estimated_features * 3)
    expected_min_tc = estimated_criteria * 2
    tc_count = len(tcs)
    quantity_ratio = min(tc_count / max(expected_min_tc, 5), 1.0)

    if tc_count < 5:
        issues.append(f"Chỉ có {tc_count} TCs — có vẻ thiếu")
    elif quantity_ratio < 0.5:
        issues.append(f"Có thể thiếu TCs: {tc_count} vs ~{expected_min_tc} ước lượng")

    # --- Duplicate title ---
    titles = [tc.get("title", "").lower() for tc in tcs]
    dup_titles = len(titles) - len(set(titles))
    if dup_titles:
        issues.append(f"{dup_titles} TC có title trùng nhau")

    # --- Duplicate content (steps fingerprint) ---
    steps_fingerprints: list[str] = []
    dup_content = 0
    for tc in tcs:
        steps = tc.get("steps", [])
        fp = "|".join(sorted(s.lower().strip() for s in steps))
        if fp and fp in steps_fingerprints:
            dup_content += 1
        else:
            steps_fingerprints.append(fp)
    if dup_content > 0:
        issues.append(f"{dup_content} TC có nội dung steps trùng nhau")

    # --- Traceability penalty nếu không có ref ---
    if trace_ratio < 0.3:
        issues.append(
            f"Chỉ {traced}/{tc_count} TC có reference về ticket/AC/story. "
            "Thêm ID như JIRA-123, AC-1, Story #2 vào title hoặc test_data_ref."
        )

    # --- Tổng hợp score ---
    # 50% từ traceability refs, 30% từ quantity, 20% trừ duplicates
    dup_penalty = (dup_titles * 0.10 + dup_content * 0.15) / max(tc_count, 1)
    score = max(
        0.0,
        min(
            1.0,
            0.50 * trace_ratio + 0.30 * quantity_ratio + 0.20 - dup_penalty,
        ),
    )

    details = (
        f"TC count: {tc_count}  |  Traced: {traced}  |  "
        f"Estimated min: {expected_min_tc}  |  "
        f"Dup titles: {dup_titles}  |  Dup content: {dup_content}"
    )
    return DimensionScore(
        DIMENSION_LABELS["requirement_traceability"],
        score,
        details=details,
        issues=issues,
    )


# ── Weights & grading ──────────────────────────────────────────────────────────

_HYBRID_RULE_WEIGHT = 0.55
_HYBRID_JUDGE_WEIGHT = 0.45


def _grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _compute_overall(
    dims: list[DimensionScore], weights: DimensionWeightConfig
) -> float:
    """Tính overall score dựa trên weights đã normalize."""
    w = weights.normalize()
    w_map = w.as_dict()
    total = 0.0
    for d in dims:
        total += d.score * w_map.get(d.name, 0.0) * 100
    return min(100.0, max(0.0, total))


# ── Public API ─────────────────────────────────────────────────────────────────


def evaluate(
    variant_id: str,
    variant_name: str,
    result: dict,
    requirement: str,
    call_llm_fn=None,
    use_llm_judge: bool = False,
    weights: Optional[DimensionWeightConfig] = None,
    use_error_analysis: bool = False,
) -> EvaluationResult:
    """
    Đánh giá chất lượng test suite.

    Parameters
    ----------
    weights : DimensionWeightConfig | None
        Trọng số tuỳ chỉnh cho 6 chiều. None → dùng DEFAULT_WEIGHTS (Balanced).
    use_llm_judge : bool
        True  → gọi thêm LLM Judge, tính hybrid_score
        False → chỉ dùng rule-based (nhanh, miễn phí)
    use_error_analysis : bool
        True  → chạy phân tích 7 loại lỗi (rule-based luôn chạy,
                LLM layer chạy nếu use_llm_judge=True)
        False → bỏ qua error analysis (nhanh hơn)
    """
    tcs = result.get("test_cases", [])
    tds = result.get("test_data_set", [])

    effective_weights = (weights or DEFAULT_WEIGHTS).normalize()

    dims = [
        _score_coverage(tcs),
        _score_clarity(tcs),
        _score_data_quality(tcs, tds),
        _score_security(tcs),
        _score_boundary(tcs),
        _score_traceability(tcs, requirement),
    ]

    overall = _compute_overall(dims, effective_weights)
    strengths = [d.name for d in dims if d.score >= 0.75]
    weaknesses = [d.name for d in dims if d.score < 0.50]

    if overall >= 85:
        rec = "Prompt này hoạt động tốt. Có thể dùng làm default."
    elif overall >= 70:
        rec = "Prompt khá tốt nhưng cần cải thiện các điểm yếu đã chỉ ra."
    elif overall >= 55:
        rec = "Prompt tạm được nhưng có lỗ hổng coverage đáng kể."
    else:
        rec = "Prompt này sinh TC kém chất lượng. Nên dùng variant khác."

    ev = EvaluationResult(
        variant_id=variant_id,
        variant_name=variant_name,
        total_tc=len(tcs),
        total_td=len(tds),
        dimensions=dims,
        overall_score=overall,
        grade=_grade(overall),
        strengths=strengths,
        weaknesses=weaknesses,
        recommendation=rec,
        weights_used=effective_weights,
        raw_tc_list=tcs,
    )

    # ── LLM Judge (optional) ──────────────────────────────────────────────────
    if use_llm_judge:
        try:
            from core.llm_judge import judge_test_cases

            judge_score = judge_test_cases(tcs, requirement, call_llm_fn)
            ev.llm_judge_score = judge_score

            if judge_score.judge_available and judge_score.composite_score > 0:
                ev.hybrid_score = (
                    overall * _HYBRID_RULE_WEIGHT
                    + judge_score.composite_score * _HYBRID_JUDGE_WEIGHT
                )
                ev.hybrid_grade = _grade(ev.hybrid_score)

                for s in judge_score.strengths:
                    if s not in ev.strengths:
                        ev.strengths.append(f"[Judge] {s}")
                for w in judge_score.weaknesses:
                    if w not in ev.weaknesses:
                        ev.weaknesses.append(f"[Judge] {w}")

                logger.info(
                    f"Hybrid score for {variant_id}: "
                    f"rule={overall:.1f} judge={judge_score.composite_score:.1f} "
                    f"hybrid={ev.hybrid_score:.1f}"
                )
        except Exception as exc:
            logger.error(f"LLM Judge integration error: {exc}", exc_info=True)

    # ── Error Analysis (optional) ─────────────────────────────────────────────
    if use_error_analysis:
        try:
            from core.error_analyzer import analyze_errors

            ev.error_report = analyze_errors(
                requirement=requirement,
                test_cases=tcs,
                test_data_set=tds,
                use_llm_judge=use_llm_judge,
                call_llm_fn=call_llm_fn,
            )
            logger.info(
                f"Error analysis for {variant_id}: "
                f"{ev.error_report.total_errors} errors found "
                f"({ev.error_report.critical_count} critical)"
            )
        except Exception as exc:
            logger.error(f"Error analysis integration error: {exc}", exc_info=True)

    return ev
