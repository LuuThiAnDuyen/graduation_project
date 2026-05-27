"""
core/error_analyzer.py
-----------------------
Phân tích lỗi test case theo 7 loại — 2 layer:

  Layer 1 — Rule-based (luôn chạy, miễn phí, nhanh):
    Detect các lỗi có thể xác định qua heuristic/regex từ nội dung TC.

  Layer 2 — LLM Judge (chạy khi use_llm_judge=True, ~1 API call):
    Detect các lỗi cần hiểu ngữ nghĩa mà rule không làm được.

7 loại lỗi:
  E1 — Bỏ sót yêu cầu hoặc điều kiện kiểm thử quan trọng
  E2 — Sinh test case không có dữ liệu đầu vào rõ ràng
  E3 — Sinh kết quả mong đợi không chính xác
  E4 — Suy diễn thêm chức năng không có trong yêu cầu
  E5 — Thiếu test case âm tính hoặc test case biên
  E6 — Trùng lặp test case
  E7 — Mâu thuẫn giữa bước thực hiện và kết quả mong đợi

Tích hợp:
  • EvaluationResult (tc_evaluator.py) thêm field error_report: ErrorReport | None
  • evaluate() nhận thêm use_error_analysis: bool = False
  • app.py thêm tab "⚠️ Error Analysis" trong render_tc_results()
"""

from __future__ import annotations

import re
import logging
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ERROR_TYPES = {
    "E1": "Bỏ sót yêu cầu / điều kiện quan trọng",
    "E2": "Thiếu dữ liệu đầu vào rõ ràng",
    "E3": "Kết quả mong đợi không chính xác",
    "E4": "Suy diễn chức năng ngoài yêu cầu",
    "E5": "Thiếu test case âm tính hoặc biên",
    "E6": "Trùng lặp test case",
    "E7": "Mâu thuẫn steps ↔ expected result",
}

ERROR_SEVERITY = {
    "E1": "Critical",
    "E2": "Warning",
    "E3": "Critical",
    "E4": "Warning",
    "E5": "Critical",
    "E6": "Info",
    "E7": "Critical",
}

ERROR_COLORS = {
    "Critical": "#ef4444",
    "Warning": "#f59e0b",
    "Info": "#3b82f6",
}

# Layer detection: rule = rule-based, llm = LLM Judge, both = cả hai
ERROR_DETECTION_LAYER = {
    "E1": "both",  # rule: count coverage types / llm: semantic gap
    "E2": "rule",  # rule: placeholder + missing test_data_ref
    "E3": "llm",  # llm: expected result có hợp lý với steps không
    "E4": "llm",  # llm: TC đề cập feature ngoài requirement
    "E5": "rule",  # rule: đếm coverage_type N/B/E
    "E6": "rule",  # rule: similarity steps fingerprint
    "E7": "llm",  # llm: steps dẫn đến kết quả A nhưng expected lại là B
}

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ErrorItem:
    error_type: str  # E1–E7
    tc_id: str  # TC-001 hoặc "suite" cho lỗi toàn bộ suite
    severity: str  # Critical / Warning / Info
    description: str  # mô tả cụ thể
    suggestion: str  # gợi ý sửa
    source: str = "rule"  # "rule" hoặc "llm"


@dataclass
class ErrorReport:
    total_errors: int = 0
    by_type: dict[str, list[ErrorItem]] = field(default_factory=dict)
    rule_errors: list[ErrorItem] = field(default_factory=list)
    llm_errors: list[ErrorItem] = field(default_factory=list)
    llm_available: bool = False
    llm_raw_summary: str = ""  # verdict từ LLM Judge nếu có

    @property
    def all_errors(self) -> list[ErrorItem]:
        return self.rule_errors + self.llm_errors

    @property
    def critical_count(self) -> int:
        return sum(1 for e in self.all_errors if e.severity == "Critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.all_errors if e.severity == "Warning")

    def group_by_type(self) -> dict[str, list[ErrorItem]]:
        grouped: dict[str, list[ErrorItem]] = {}
        for e in self.all_errors:
            grouped.setdefault(e.error_type, []).append(e)
        return grouped

    def group_by_tc(self) -> dict[str, list[ErrorItem]]:
        grouped: dict[str, list[ErrorItem]] = {}
        for e in self.all_errors:
            grouped.setdefault(e.tc_id, []).append(e)
        return grouped


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_PLACEHOLDER = re.compile(
    r"\b(your[_\s]?\w+|placeholder|example\.com|foo@bar|test@test|"
    r"<\w+>|xxx|abc123|123456|password123|admin123|user123|"
    r"enter\s+\w+\s+here|fill\s+in|tbd|n/a)\b",
    re.IGNORECASE,
)

_VAGUE_EXPECTED = re.compile(
    r"^(test pass(es)?|system works?( correctly)?|success|ok|"
    r"everything works?|no error(s)?|works? as expected|"
    r"(the )?system (should )?(work|function|respond) correctly|"
    r"pass|fail|done|completed|verified|checked)$",
    re.IGNORECASE,
)

_VAGUE_STEP = re.compile(
    r"^(submit form|fill form|fill in|enter data|test the|verify that|"
    r"check if|click button|perform action|do the test|run test|"
    r"test (?:login|register|feature|functionality)|validate input|"
    r"navigate to page|go to website)$",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def _steps_fingerprint(tc: dict) -> str:
    steps = tc.get("steps", [])
    return "|".join(sorted(s.lower().strip() for s in steps))


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _tc_full_text(tc: dict) -> str:
    return " ".join(
        [
            tc.get("title", ""),
            tc.get("precondition", ""),
            " ".join(tc.get("steps", [])),
            tc.get("expected_result", ""),
        ]
    )


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: Rule-based detectors
# ─────────────────────────────────────────────────────────────────────────────


def _detect_e1_rule(requirement: str, test_cases: list[dict]) -> list[ErrorItem]:
    """
    E1 — Bỏ sót yêu cầu: kiểm tra coverage_type thiếu
    và các keyword quan trọng trong requirement không được bao phủ.
    """
    errors: list[ErrorItem] = []
    found_types = {tc.get("coverage_type", "") for tc in test_cases}

    # E1a: thiếu loại coverage cốt lõi → Critical
    missing_types = []
    if "N" not in found_types:
        missing_types.append("Negative (N)")
    if "B" not in found_types:
        missing_types.append("Boundary (B)")
    if "S" not in found_types:
        missing_types.append("Security (S)")

    if missing_types:
        errors.append(
            ErrorItem(
                error_type="E1",
                tc_id="suite",
                severity="Critical",
                description=f"Test suite thiếu hoàn toàn các loại TC: {', '.join(missing_types)}.",
                suggestion="Thêm TC âm tính, biên, và bảo mật cho từng trường nhập liệu.",
                source="rule",
            )
        )

    # E1b: từ khoá AC/điều kiện trong requirement không có TC nào bao phủ → Warning
    ac_pattern = re.compile(
        r"(?:^|\n)\s*[-•*]\s+(.{15,})|" r"(?:AC|acceptance criteria?)[:\s]+(.{15,})",
        re.IGNORECASE | re.MULTILINE,
    )
    all_tc_text = " ".join(_tc_full_text(tc) for tc in test_cases).lower()
    uncovered: list[str] = []

    for m in ac_pattern.finditer(requirement):
        cond = (m.group(1) or m.group(2) or "").strip()
        if not cond:
            continue
        kws = [w for w in _norm(cond).split() if len(w) >= 4][:4]
        if kws and not any(kw in all_tc_text for kw in kws):
            uncovered.append(cond[:80])

    for cond in uncovered[:5]:
        errors.append(
            ErrorItem(
                error_type="E1",
                tc_id="suite",
                severity="Warning",
                description=f"Không tìm thấy TC bao phủ điều kiện: [{cond}]",
                suggestion="Thêm TC kiểm thử điều kiện chấp nhận này.",
                source="rule",
            )
        )

    return errors


def _detect_e2_rule(
    test_cases: list[dict], test_data_set: list[dict]
) -> list[ErrorItem]:
    """
    E2 — Thiếu dữ liệu đầu vào: placeholder values, thiếu test_data_ref,
    steps có 'enter X' nhưng không có giá trị cụ thể.
    """
    errors: list[ErrorItem] = []
    td_ids = {td.get("id", "") for td in test_data_set}

    for tc in test_cases:
        tc_id = tc.get("id", "?")
        ct = tc.get("coverage_type", "P")
        issues: list[str] = []

        # TC loại P/N/B/S mà không có test_data_ref
        if ct in ("P", "N", "B", "S") and not tc.get("test_data_ref"):
            issues.append("không có test_data_ref")

        # test_data_ref trỏ đến TD không tồn tại
        ref = tc.get("test_data_ref", "")
        if ref and ref not in td_ids:
            issues.append(f"test_data_ref '{ref}' không tồn tại trong test_data_set")

        # Steps chứa placeholder
        for step in tc.get("steps", []):
            if _PLACEHOLDER.search(step):
                issues.append(f"step chứa placeholder: [{step[:60]}]")
                break

        # Expected result chứa placeholder
        exp = tc.get("expected_result", "")
        if _PLACEHOLDER.search(exp):
            issues.append("expected_result chứa placeholder")

        if issues:
            errors.append(
                ErrorItem(
                    error_type="E2",
                    tc_id=tc_id,
                    severity="Warning",
                    description=f"{tc_id}: {'; '.join(issues)}.",
                    suggestion="Thay placeholder bằng giá trị cụ thể và tạo TD entry tương ứng.",
                    source="rule",
                )
            )

    return errors


def _detect_e5_rule(test_cases: list[dict]) -> list[ErrorItem]:
    """
    E5 — Thiếu TC âm tính hoặc biên:
    Theo dõi theo feature_group — nếu 1 feature chỉ có TC positive thì flag.
    """
    errors: list[ErrorItem] = []

    feature_types: dict[str, set[str]] = {}
    for tc in test_cases:
        fg = tc.get("feature_group", "General")
        ct = tc.get("coverage_type", "P")
        feature_types.setdefault(fg, set()).add(ct)

    for fg, types in feature_types.items():
        missing: list[str] = []
        if "N" not in types and "E" not in types:
            missing.append("Negative/Edge (N/E)")
        if "B" not in types:
            missing.append("Boundary (B)")

        if missing:
            errors.append(
                ErrorItem(
                    error_type="E5",
                    tc_id="suite",
                    severity="Critical",
                    description=f"Feature '{fg}' thiếu loại TC: {', '.join(missing)}.",
                    suggestion=f"Thêm TC kiểm thử giá trị không hợp lệ và giá trị biên cho '{fg}'.",
                    source="rule",
                )
            )

    return errors


def _detect_e6_rule(test_cases: list[dict]) -> list[ErrorItem]:
    """
    E6 — Trùng lặp: exact title duplicate + steps fingerprint duplicate
    + high similarity (>=0.80).
    """
    errors: list[ErrorItem] = []

    # E6a: trùng title
    titles: dict[str, list[str]] = {}
    for tc in test_cases:
        t = tc.get("title", "").lower().strip()
        titles.setdefault(t, []).append(tc.get("id", "?"))
    for title, ids in titles.items():
        if len(ids) > 1 and title:
            errors.append(
                ErrorItem(
                    error_type="E6",
                    tc_id=", ".join(ids),
                    severity="Info",
                    description=f"TC có title giống nhau: {', '.join(ids)} — {title[:60]}",
                    suggestion="Xoá hoặc gộp TC trùng lặp, đảm bảo mỗi TC kiểm thử 1 điều kiện riêng.",
                    source="rule",
                )
            )

    # E6b: trùng steps fingerprint
    fp_seen: dict[str, str] = {}
    for tc in test_cases:
        tc_id = tc.get("id", "?")
        fp = _steps_fingerprint(tc)
        if fp and fp in fp_seen:
            errors.append(
                ErrorItem(
                    error_type="E6",
                    tc_id=tc_id,
                    severity="Info",
                    description=f"{tc_id} có steps giống hệt {fp_seen[fp]}.",
                    suggestion="Xoá TC trùng hoặc phân biệt rõ điều kiện kiểm thử khác nhau.",
                    source="rule",
                )
            )
        else:
            fp_seen[fp] = tc_id

    # E6c: high similarity pairs (tối đa 5 cặp)
    n = len(test_cases)
    pairs_found = 0
    for i in range(min(n, 30)):
        for j in range(i + 1, min(n, 30)):
            if pairs_found >= 5:
                break
            a = test_cases[i]
            b = test_cases[j]
            sim = _sim(_tc_full_text(a), _tc_full_text(b))
            if sim >= 0.80:
                id_a = a.get("id", f"TC-{i+1}")
                id_b = b.get("id", f"TC-{j+1}")
                errors.append(
                    ErrorItem(
                        error_type="E6",
                        tc_id=f"{id_a}, {id_b}",
                        severity="Info",
                        description=f"{id_a} và {id_b} có nội dung tương đồng {sim:.0%}.",
                        suggestion="Xem xét gộp hoặc tách rõ 2 TC này.",
                        source="rule",
                    )
                )
                pairs_found += 1

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: LLM Judge prompt
# ─────────────────────────────────────────────────────────────────────────────

_LLM_ERROR_PROMPT = """You are a senior QA auditor reviewing an AI-generated test suite.

REQUIREMENT:
{requirement}

TEST CASES (sample up to 15):
{tc_sample}

Analyze the test suite for these 4 error types that require semantic understanding:

E1 — Missing requirements: Are there important acceptance criteria or business rules
     from the requirement that NO test case covers?

E3 — Incorrect expected results: Do any TCs have expected results that are
     logically inconsistent with their steps? (e.g., steps perform action A
     but expected result describes outcome of action B)

E4 — Hallucinated functionality: Do any TCs test features or behaviors that are
     NOT mentioned in the requirement?

E7 — Step vs expected contradiction: Are there TCs where the steps clearly lead
     to outcome X, but the expected result states outcome Y?

For each error found, identify the specific TC ID and explain concisely.

Return ONLY valid JSON:
{{
  "E1": [
    {{"tc_id": "suite", "description": "<what is missing>", "suggestion": "<how to fix>"}}
  ],
  "E3": [
    {{"tc_id": "TC-001", "description": "<what is wrong with expected result>", "suggestion": "<correct expected result>"}}
  ],
  "E4": [
    {{"tc_id": "TC-005", "description": "<what feature is not in requirement>", "suggestion": "<remove or align with requirement>"}}
  ],
  "E7": [
    {{"tc_id": "TC-003", "description": "<contradiction description>", "suggestion": "<how to fix>"}}
  ],
  "summary": "<1-2 sentence overall verdict>",
  "overall_severity": "High|Medium|Low"
}}

Return empty arrays [] for error types with no issues found.
Be specific — cite TC IDs and exact problems. Do not fabricate errors."""


def _build_tc_sample_for_error(test_cases: list[dict], max_tc: int = 15) -> str:
    """Build compact TC representation for LLM error analysis."""
    selected = test_cases[:max_tc]
    lines = []
    for tc in selected:
        steps_str = " → ".join(tc.get("steps", [])[:5])
        lines.append(
            f"[{tc.get('id')}|{tc.get('coverage_type','?')}] {tc.get('title','')}\n"
            f"  Steps: {steps_str[:200]}\n"
            f"  Expected: {(tc.get('expected_result',''))[:150]}\n"
            f"  Data ref: {tc.get('test_data_ref','–')}"
        )
    return "\n---\n".join(lines)


def _run_llm_error_analysis(
    requirement: str,
    test_cases: list[dict],
    call_llm_fn,
) -> tuple[list[ErrorItem], str]:
    """
    Gọi LLM để detect E1 (semantic), E3, E4, E7.
    Trả về (list[ErrorItem], summary_str).
    """
    tc_sample = _build_tc_sample_for_error(test_cases, max_tc=15)
    prompt = _LLM_ERROR_PROMPT.format(
        requirement=requirement[:2500],
        tc_sample=tc_sample,
    )

    try:
        raw = call_llm_fn(prompt)
        if not isinstance(raw, dict):
            logger.warning("LLM error analysis returned non-dict")
            return [], ""

        errors: list[ErrorItem] = []

        for etype in ("E1", "E3", "E4", "E7"):
            items = raw.get(etype, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                tc_id = str(item.get("tc_id", "suite")).strip()
                desc = str(item.get("description", "")).strip()
                sugg = str(item.get("suggestion", "")).strip()
                if not desc:
                    continue
                errors.append(
                    ErrorItem(
                        error_type=etype,
                        tc_id=tc_id,
                        severity=ERROR_SEVERITY.get(etype, "Warning"),
                        description=desc,
                        suggestion=sugg,
                        source="llm",
                    )
                )

        summary = str(raw.get("summary", "")).strip()
        logger.info(
            f"LLM error analysis found {len(errors)} errors. "
            f"Severity: {raw.get('overall_severity','?')}"
        )
        return errors, summary

    except Exception as exc:
        logger.error(f"LLM error analysis failed: {exc}", exc_info=True)
        return [], ""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def analyze_errors(
    requirement: str,
    test_cases: list[dict],
    test_data_set: list[dict],
    use_llm_judge: bool = False,
    call_llm_fn=None,
) -> ErrorReport:
    """
    Phân tích lỗi test suite theo 7 loại.

    Parameters
    ----------
    requirement    : Văn bản requirement gốc.
    test_cases     : Danh sách TC dict đã sanitise.
    test_data_set  : Danh sách TD dict đã sanitise.
    use_llm_judge  : True → gọi thêm LLM để detect E1/E3/E4/E7 (semantic).
    call_llm_fn    : Hàm gọi LLM (default: core.llm_client.call_llm).

    Returns
    -------
    ErrorReport chứa tất cả lỗi phân loại theo type và source.
    """
    if not test_cases:
        return ErrorReport(total_errors=0)

    # ── Layer 1: Rule-based ──────────────────────────────────────────────
    rule_errors: list[ErrorItem] = []
    rule_errors += _detect_e1_rule(requirement, test_cases)
    rule_errors += _detect_e2_rule(test_cases, test_data_set)
    rule_errors += _detect_e5_rule(test_cases)
    rule_errors += _detect_e6_rule(test_cases)

    # ── Layer 2: LLM Judge ───────────────────────────────────────────────
    llm_errors: list[ErrorItem] = []
    llm_summary = ""
    llm_available = False

    if use_llm_judge:
        if call_llm_fn is None:
            try:
                from core.llm_client import call_llm

                call_llm_fn = call_llm
            except ImportError:
                logger.error("llm_client not available for error analysis")

        if call_llm_fn is not None:
            llm_errors, llm_summary = _run_llm_error_analysis(
                requirement, test_cases, call_llm_fn
            )
            llm_available = True

    # ── Tổng hợp ────────────────────────────────────────────────────────
    all_errors = rule_errors + llm_errors
    report = ErrorReport(
        total_errors=len(all_errors),
        rule_errors=rule_errors,
        llm_errors=llm_errors,
        llm_available=llm_available,
        llm_raw_summary=llm_summary,
    )

    return report


def render_error_report_streamlit(report: ErrorReport) -> None:
    """
    Render ErrorReport trong Streamlit.
    Gọi trong app.py bên trong tab "⚠️ Error Analysis".
    """
    import streamlit as st

    if report.total_errors == 0:
        st.success("✅ Không phát hiện lỗi nào qua rule-based analysis.")
        if not report.llm_available:
            st.caption(
                "💡 Bật **LLM Judge** để phát hiện thêm lỗi ngữ nghĩa "
                "(E3 – Kết quả mong đợi sai, E4 – Suy diễn ngoài yêu cầu, E7 – Mâu thuẫn)."
            )
        return

    # ── Summary metrics ──────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tổng lỗi", report.total_errors)
    col2.metric("🔴 Critical", report.critical_count)
    col3.metric("🟡 Warning", report.warning_count)
    col4.metric(
        "Nguồn",
        f"Rule{' + LLM' if report.llm_available else ''}",
    )

    if report.llm_raw_summary:
        st.info(f"🧠 **LLM Verdict:** {report.llm_raw_summary}")

    if not report.llm_available:
        st.caption(
            "💡 Bật **LLM Judge** để phát hiện thêm: "
            "E3 (Kết quả mong đợi sai), E4 (Suy diễn ngoài yêu cầu), "
            "E7 (Mâu thuẫn steps ↔ expected)."
        )

    st.divider()

    # ── Group by error type ──────────────────────────────────────────────
    grouped = report.group_by_type()

    for etype, label in ERROR_TYPES.items():
        items = grouped.get(etype, [])
        if not items:
            continue

        # ── Đếm severity THỰC TẾ từ các item, không dùng ERROR_SEVERITY mặc định ──
        actual_critical = sum(1 for i in items if i.severity == "Critical")
        actual_warning = sum(1 for i in items if i.severity == "Warning")
        actual_info = sum(1 for i in items if i.severity == "Info")

        # Dominant severity = severity cao nhất có mặt trong items
        if actual_critical > 0:
            dominant_severity = "Critical"
        elif actual_warning > 0:
            dominant_severity = "Warning"
        else:
            dominant_severity = "Info"

        color = ERROR_COLORS.get(dominant_severity, "#6b7280")
        icon = (
            "🔴"
            if dominant_severity == "Critical"
            else "🟡" if dominant_severity == "Warning" else "🔵"
        )

        # Source counts
        source_counts = {
            "rule": sum(1 for i in items if i.source == "rule"),
            "llm": sum(1 for i in items if i.source == "llm"),
        }
        source_str = []
        if source_counts["rule"]:
            source_str.append(f"📏 {source_counts['rule']} rule")
        if source_counts["llm"]:
            source_str.append(f"🤖 {source_counts['llm']} LLM")

        # Severity breakdown string cho expander title
        severity_parts = []
        if actual_critical:
            severity_parts.append(f"🔴 {actual_critical} critical")
        if actual_warning:
            severity_parts.append(f"🟡 {actual_warning} warning")
        if actual_info:
            severity_parts.append(f"🔵 {actual_info} info")
        severity_str = "  ·  ".join(severity_parts)

        # Header markdown bên trong expander
        header = (
            f"**{etype}** — {label}  "
            f"<span style='color:{color};font-weight:600;'>"
            f"{icon} {dominant_severity}</span>  "
            f"· {len(items)} lỗi  ·  {severity_str}  ·  {', '.join(source_str)}"
        )

        with st.expander(
            f"{icon} {etype} — {label}  ({len(items)} lỗi  ·  {severity_str})",
            expanded=(actual_critical > 0),
        ):
            st.markdown(
                f'<div style="color:#1a1a1a;">' + header + "</div>",
                unsafe_allow_html=True,
            )
            for item in items:
                source_icon = "🤖" if item.source == "llm" else "📏"
                # Màu nền và border theo severity THỰC TẾ của từng item
                item_color = ERROR_COLORS.get(item.severity, "#6b7280")
                item_bg = (
                    "#fef2f2"
                    if item.severity == "Critical"
                    else "#fffbeb" if item.severity == "Warning" else "#eff6ff"
                )
                st.markdown(
                    f"""<div style="border-left:3px solid {item_color};
                    padding:8px 12px;margin:6px 0;border-radius:0 4px 4px 0;
                    background:{item_bg};
                    color:#1a1a1a;">
                    <b style="color:#111111;">{source_icon} [{item.tc_id}]</b>
                    <span style="color:#1a1a1a;"> {item.description}</span><br>
                    <small style="color:#374151;">💡 {item.suggestion}</small>
                    </div>""",
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── Group by TC ──────────────────────────────────────────────────────
    tc_grouped = report.group_by_tc()
    tc_ids = [tid for tid in tc_grouped if tid != "suite"]

    if tc_ids:
        with st.expander(f"🔍 Xem theo TC ({len(tc_ids)} TC có lỗi)", expanded=False):
            for tc_id in sorted(tc_ids):
                items = tc_grouped[tc_id]
                badges = " ".join(
                    f"<span style='background:{'#fef2f2' if i.severity=='Critical' else '#fffbeb' if i.severity=='Warning' else '#eff6ff'}"
                    f";padding:1px 6px;border-radius:4px;font-size:0.8em;color:#111111;font-weight:600;'>"
                    f"{i.error_type}</span>"
                    for i in items
                )
                st.markdown(
                    f"**{tc_id}** — {len(items)} lỗi: {badges}",
                    unsafe_allow_html=True,
                )
                for item in items:
                    item_color = ERROR_COLORS.get(item.severity, "#6b7280")
                    st.caption(f"  • [{item.error_type}] {item.description}")
