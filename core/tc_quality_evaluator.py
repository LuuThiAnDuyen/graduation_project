"""
core/tc_quality_evaluator.py
-----------------------------
Tính 6 chỉ số đánh giá chất lượng test case cho nghiên cứu so sánh P1–P5.

Chỉ số:
  1. Requirement Coverage  — Tỷ lệ điều kiện/yêu cầu được bao phủ bởi TC.
  2. Precision             — Tỷ lệ TC đúng / hợp lệ trên tổng TC sinh ra.
  3. Invalid TC Rate       — Tỷ lệ TC thiếu steps, thiếu data hoặc expected result mơ hồ.
  4. Omission Rate         — Tỷ lệ trường hợp kiểm thử quan trọng bị bỏ sót.
  5. Redundancy Rate       — Tỷ lệ TC trùng lặp hoặc nội dung tương tự nhau.
  6. Hallucination Rate    — Tỷ lệ TC chứa thông tin không có trong yêu cầu ban đầu.

Thiết kế:
  - Tất cả chỉ số tính được từ requirement text + danh sách TC (không cần ground truth).
  - Dùng heuristic NLP nhẹ (không cần model ngoài) để đảm bảo chạy offline.
  - Mỗi chỉ số trả về: giá trị % + danh sách TC vi phạm + giải thích ngắn.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MetricResult:
    name: str  # Tên chỉ số
    value: float  # Giá trị % (0–100)
    direction: str  # "high_good" hoặc "low_good"
    label: str  # Nhãn diễn giải (Tốt / Trung bình / Kém)
    color: str  # Màu hex để hiển thị
    explanation: str  # Giải thích ngắn gọn
    violation_ids: List[str] = field(default_factory=list)  # ID TC vi phạm
    detail_lines: List[str] = field(default_factory=list)  # Chi tiết từng vi phạm


@dataclass
class QualityReport:
    variant_id: str
    variant_name: str
    total_tc: int
    metrics: List[MetricResult]

    def get_metric(self, name: str) -> Optional[MetricResult]:
        return next((m for m in self.metrics if m.name == name), None)

    def summary_score(self) -> float:
        """
        Tổng hợp điểm nghiên cứu (0–100).
        Các chỉ số 'high_good' đóng góp thuận, 'low_good' đóng góp nghịch.
        Trọng số: Coverage(30) + Precision(25) - Invalid(15) - Omission(15)
                  - Redundancy(8) - Hallucination(7)
        """
        weights = {
            "Requirement Coverage": +0.30,
            "Precision": +0.25,
            "Invalid TC Rate": -0.15,
            "Omission Rate": -0.15,
            "Redundancy Rate": -0.08,
            "Hallucination Rate": -0.07,
        }
        score = 50.0  # baseline
        for m in self.metrics:
            w = weights.get(m.name, 0)
            score += w * m.value
        return round(max(0.0, min(100.0, score)), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase + remove diacritics + strip punctuation."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _keywords(text: str) -> set[str]:
    """Tách keyword có nghĩa (>=3 ký tự) từ text đã normalize."""
    stopwords = {
        "the",
        "and",
        "for",
        "are",
        "with",
        "that",
        "this",
        "from",
        "have",
        "will",
        "should",
        "must",
        "when",
        "then",
        "given",
        "user",
        "system",
        "page",
        "screen",
        "button",
        "field",
        "form",
        "click",
        "enter",
        "open",
        "can",
        "not",
        "all",
        "any",
        "one",
        "two",
        "has",
        "its",
        "than",
        "more",
        "sau",
        "khi",
        "vao",
        "cua",
        "mot",
        "cac",
        "hay",
        "hoac",
        "tren",
        "duoi",
        "theo",
        "trong",
        "ngoai",
        "biet",
        "duoc",
        "phai",
        "nen",
    }
    words = _normalize(text).split()
    return {w for w in words if len(w) >= 3 and w not in stopwords}


def _extract_conditions(requirement: str) -> list[str]:
    """
    Trích xuất các điều kiện kiểm thử tiềm năng từ requirement.
    Chiến lược:
      - Mỗi dòng bắt đầu bằng '-', '*', '•', số thứ tự → 1 condition
      - Câu chứa từ khoá condition ("if", "when", "must", "should",
        "nếu", "khi", "phải", "cần", "không được") → 1 condition
      - Mỗi acceptance criteria → 1 condition
    """
    conditions: list[str] = []
    lines = requirement.splitlines()

    bullet_pattern = re.compile(r"^\s*[-*•]\s+.{10,}")
    numbered_pattern = re.compile(r"^\s*\d+[.)]\s+.{10,}")
    condition_kw = re.compile(
        r"\b(if|when|must|should|shall|require|cannot|not allowed|"
        r"neu|khi|phai|can|khong duoc|bat buoc|yeu cau)\b",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 10:
            continue
        if bullet_pattern.match(line) or numbered_pattern.match(line):
            conditions.append(stripped)
        elif condition_kw.search(_normalize(stripped)):
            conditions.append(stripped)

    # Nếu không tìm được bullet/condition → chia theo câu
    if not conditions:
        sentences = re.split(r"[.!?]\s+", requirement)
        conditions = [s.strip() for s in sentences if len(s.strip()) > 20]

    return conditions


def _tc_text(tc: dict) -> str:
    """Gộp toàn bộ nội dung text của 1 TC thành chuỗi để so sánh."""
    parts = [
        tc.get("title", ""),
        tc.get("precondition", ""),
        " ".join(tc.get("steps", [])),
        tc.get("expected_result", ""),
    ]
    return " ".join(p for p in parts if p)


def _similarity(a: str, b: str) -> float:
    """SequenceMatcher similarity trên chuỗi đã normalize."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _label_and_color(value: float, direction: str) -> tuple[str, str]:
    """
    Trả về (label, color) dựa trên giá trị và chiều tốt của chỉ số.
    direction = "high_good": cao = tốt (Coverage, Precision)
    direction = "low_good" : thấp = tốt (Invalid, Omission, Redundancy, Hallucination)
    """
    if direction == "high_good":
        if value >= 75:
            return "Tốt", "#22c55e"
        elif value >= 50:
            return "Trung bình", "#f59e0b"
        else:
            return "Kém", "#ef4444"
    else:  # low_good
        if value <= 10:
            return "Tốt", "#22c55e"
        elif value <= 25:
            return "Trung bình", "#f59e0b"
        else:
            return "Kém", "#ef4444"


# ─────────────────────────────────────────────────────────────────────────────
# Metric 1: Requirement Coverage
# ─────────────────────────────────────────────────────────────────────────────


def _requirement_coverage(requirement: str, test_cases: list[dict]) -> MetricResult:
    """
    Tỷ lệ điều kiện trong requirement được ít nhất 1 TC bao phủ.
    Bao phủ = TC có keyword overlap >= 30% với điều kiện đó.
    """
    conditions = _extract_conditions(requirement)
    if not conditions:
        return MetricResult(
            name="Requirement Coverage",
            value=0.0,
            direction="high_good",
            label="Kém",
            color="#ef4444",
            explanation="Không trích xuất được điều kiện từ requirement.",
        )

    all_tc_text = [_tc_text(tc) for tc in test_cases]
    covered = []
    uncovered = []

    for cond in conditions:
        cond_kws = _keywords(cond)
        if not cond_kws:
            covered.append(cond)
            continue
        found = False
        for tc_text in all_tc_text:
            tc_kws = _keywords(tc_text)
            overlap = len(cond_kws & tc_kws) / len(cond_kws)
            if overlap >= 0.30:
                found = True
                break
        (covered if found else uncovered).append(cond)

    pct = round(len(covered) / len(conditions) * 100, 1)
    label, color = _label_and_color(pct, "high_good")

    detail = [f"❌ Chưa có TC bao phủ: {c[:80]}" for c in uncovered[:5]]
    explanation = f"{len(covered)}/{len(conditions)} điều kiện được bao phủ. " + (
        f"{len(uncovered)} điều kiện chưa có TC."
        if uncovered
        else "Tất cả điều kiện đã được bao phủ."
    )

    return MetricResult(
        name="Requirement Coverage",
        value=pct,
        direction="high_good",
        label=label,
        color=color,
        explanation=explanation,
        detail_lines=detail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric 2: Precision
# ─────────────────────────────────────────────────────────────────────────────


def _precision(test_cases: list[dict]) -> MetricResult:
    """
    Tỷ lệ TC hợp lệ = có đủ title + steps (>=1) + expected_result có nghĩa.
    TC không hợp lệ: title rỗng, steps rỗng, expected_result rỗng/mơ hồ.
    """
    vague_patterns = re.compile(
        r"^(n/a|tbd|todo|pass|fail|ok|yes|no|success|error|N/A|TBD|\-|\.)$",
        re.IGNORECASE,
    )
    valid_ids = []
    invalid_ids = []
    detail = []

    for tc in test_cases:
        tc_id = tc.get("id", "?")
        reasons = []

        title = (tc.get("title") or "").strip()
        steps = tc.get("steps") or []
        expected = (tc.get("expected_result") or "").strip()

        if not title:
            reasons.append("thiếu title")
        if not steps or len(steps) == 0:
            reasons.append("không có steps")
        if not expected or len(expected) < 5 or vague_patterns.match(expected):
            reasons.append("expected_result rỗng hoặc mơ hồ")

        if reasons:
            invalid_ids.append(tc_id)
            detail.append(f"❌ {tc_id}: {', '.join(reasons)}")
        else:
            valid_ids.append(tc_id)

    total = len(test_cases)
    if total == 0:
        return MetricResult(
            name="Precision",
            value=0.0,
            direction="high_good",
            label="Kém",
            color="#ef4444",
            explanation="Không có TC nào.",
        )

    pct = round(len(valid_ids) / total * 100, 1)
    label, color = _label_and_color(pct, "high_good")
    explanation = (
        f"{len(valid_ids)}/{total} TC hợp lệ (có đủ title, steps, expected_result). "
        + (f"{len(invalid_ids)} TC không hợp lệ." if invalid_ids else "")
    )

    return MetricResult(
        name="Precision",
        value=pct,
        direction="high_good",
        label=label,
        color=color,
        explanation=explanation,
        violation_ids=invalid_ids,
        detail_lines=detail[:8],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric 3: Invalid TC Rate
# ─────────────────────────────────────────────────────────────────────────────


def _invalid_tc_rate(test_cases: list[dict]) -> MetricResult:
    """
    Tỷ lệ TC không hợp lệ (ngược của Precision, nhưng phân tích sâu hơn).
    Bao gồm: thiếu steps, steps không atomic, thiếu precondition, expected_result mơ hồ.
    """
    vague_expected = re.compile(
        r"^(n/a|tbd|todo|pass|fail|ok|yes|no|success|error|\-|\.)$",
        re.IGNORECASE,
    )
    non_atomic = re.compile(
        r"\b(and then|sau do|va sau|then also|also|additionally)\b",
        re.IGNORECASE,
    )

    invalid_ids = []
    detail = []

    for tc in test_cases:
        tc_id = tc.get("id", "?")
        reasons = []

        steps = tc.get("steps") or []
        expected = (tc.get("expected_result") or "").strip()
        precondition = (tc.get("precondition") or "").strip()

        # Thiếu steps
        if not steps:
            reasons.append("không có steps")
        # Steps không atomic (gộp nhiều hành động)
        elif any(non_atomic.search(s) for s in steps):
            reasons.append("steps chứa nhiều hành động (không atomic)")

        # Thiếu precondition
        if not precondition or len(precondition) < 3:
            reasons.append("thiếu precondition")

        # Expected result mơ hồ
        if not expected or len(expected) < 5 or vague_expected.match(expected):
            reasons.append("expected_result mơ hồ hoặc rỗng")

        # Element locator không đồng bộ số dòng với steps
        el = tc.get("element_locator") or ""
        if steps and el:
            el_lines = [l for l in el.split("\\n") if l]
            if el_lines and len(el_lines) != len(steps):
                reasons.append(
                    f"element_locator ({len(el_lines)} dòng) ≠ steps ({len(steps)} dòng)"
                )

        if reasons:
            invalid_ids.append(tc_id)
            detail.append(f"⚠️ {tc_id}: {', '.join(reasons)}")

    total = len(test_cases)
    pct = round(len(invalid_ids) / total * 100, 1) if total else 0.0
    label, color = _label_and_color(pct, "low_good")
    explanation = (
        f"{len(invalid_ids)}/{total} TC không hợp lệ "
        "(thiếu steps, precondition, expected_result mơ hồ, hoặc element_locator sai)."
    )

    return MetricResult(
        name="Invalid TC Rate",
        value=pct,
        direction="low_good",
        label=label,
        color=color,
        explanation=explanation,
        violation_ids=invalid_ids,
        detail_lines=detail[:8],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric 4: Omission Rate
# ─────────────────────────────────────────────────────────────────────────────

# Nhóm kiểm thử quan trọng mà một test suite đầy đủ PHẢI có
_MANDATORY_GROUPS = {
    "Positive / Happy-path": {
        "coverage_types": {"P"},
        "keywords": {
            "valid",
            "success",
            "correct",
            "successfully",
            "hop le",
            "thanh cong",
        },
    },
    "Negative / Error-path": {
        "coverage_types": {"N"},
        "keywords": {
            "invalid",
            "error",
            "fail",
            "wrong",
            "reject",
            "khong hop le",
            "loi",
        },
    },
    "Boundary Value": {
        "coverage_types": {"B"},
        "keywords": {
            "min",
            "max",
            "minimum",
            "maximum",
            "boundary",
            "limit",
            "gioi han",
        },
    },
    "Security (SQLi/XSS)": {
        "coverage_types": {"S"},
        "keywords": {
            "sql",
            "injection",
            "xss",
            "script",
            "security",
            "bao mat",
            "or 1=1",
        },
    },
    "Empty / Null input": {
        "coverage_types": {"E"},
        "keywords": {"empty", "null", "blank", "whitespace", "rong", "trong"},
    },
}


def _omission_rate(requirement: str, test_cases: list[dict]) -> MetricResult:
    """
    Tỷ lệ nhóm kiểm thử quan trọng bị bỏ sót.
    Kiểm tra 5 nhóm bắt buộc; mỗi nhóm vắng mặt = 1 lần bỏ sót.
    Omission Rate = bỏ_sót / tổng_nhóm * 100.
    """
    missing_groups = []
    present_groups = []

    for group_name, criteria in _MANDATORY_GROUPS.items():
        covered_types = criteria["coverage_types"]
        covered_kws = criteria["keywords"]

        found = False
        for tc in test_cases:
            ct = tc.get("coverage_type", "")
            tc_text = _normalize(_tc_text(tc))
            # Khớp qua coverage_type
            if ct in covered_types:
                found = True
                break
            # Khớp qua keyword trong nội dung TC
            if any(kw in tc_text for kw in covered_kws):
                found = True
                break

        (present_groups if found else missing_groups).append(group_name)

    total_groups = len(_MANDATORY_GROUPS)
    pct = round(len(missing_groups) / total_groups * 100, 1)
    label, color = _label_and_color(pct, "low_good")

    detail = [f"❌ Thiếu nhóm TC: {g}" for g in missing_groups]
    explanation = (
        f"{len(missing_groups)}/{total_groups} nhóm kiểm thử bắt buộc bị bỏ sót. "
        + (
            f"Thiếu: {', '.join(missing_groups)}."
            if missing_groups
            else "Đã có đủ các nhóm kiểm thử cơ bản."
        )
    )

    return MetricResult(
        name="Omission Rate",
        value=pct,
        direction="low_good",
        label=label,
        color=color,
        explanation=explanation,
        detail_lines=detail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric 5: Redundancy Rate
# ─────────────────────────────────────────────────────────────────────────────


def _redundancy_rate(test_cases: list[dict]) -> MetricResult:
    """
    Tỷ lệ TC trùng lặp hoặc nội dung kiểm thử tương tự nhau.
    Hai TC coi là redundant nếu similarity(title+steps+expected) >= 0.75.
    """
    redundant_ids: set[str] = set()
    detail = []
    n = len(test_cases)

    texts = [_normalize(_tc_text(tc)) for tc in test_cases]
    ids = [tc.get("id", f"TC-{i+1}") for i, tc in enumerate(test_cases)]

    for i in range(n):
        for j in range(i + 1, n):
            sim = _similarity(texts[i], texts[j])
            if sim >= 0.75:
                redundant_ids.add(ids[i])
                redundant_ids.add(ids[j])
                if len(detail) < 8:
                    detail.append(f"🔁 {ids[i]} ↔ {ids[j]}: tương đồng {sim:.0%}")

    pct = round(len(redundant_ids) / n * 100, 1) if n else 0.0
    label, color = _label_and_color(pct, "low_good")
    explanation = (
        f"{len(redundant_ids)}/{n} TC có nội dung trùng lặp hoặc tương tự "
        f"(ngưỡng similarity ≥ 75%)."
    )

    return MetricResult(
        name="Redundancy Rate",
        value=pct,
        direction="low_good",
        label=label,
        color=color,
        explanation=explanation,
        violation_ids=list(redundant_ids),
        detail_lines=detail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric 6: Hallucination Rate
# ─────────────────────────────────────────────────────────────────────────────

# Từ khoá kỹ thuật "generic" — không tính là hallucination
_GENERIC_TECH_KWS = {
    "sql",
    "database",
    "db",
    "http",
    "https",
    "api",
    "url",
    "id",
    "uuid",
    "token",
    "session",
    "cookie",
    "email",
    "password",
    "username",
    "input",
    "button",
    "form",
    "page",
    "screen",
    "modal",
    "alert",
    "error",
    "success",
    "redirect",
    "login",
    "logout",
    "register",
    "submit",
    "cancel",
    "save",
    "delete",
    "update",
    "create",
    "search",
    "filter",
    "sort",
    "list",
    "table",
    "dashboard",
    "profile",
    "account",
    "user",
    "admin",
    "role",
    "permission",
    "auth",
    "otp",
    "verify",
    "confirm",
    "reset",
    "link",
    "click",
    "select",
    "checkbox",
    "radio",
    "dropdown",
    "upload",
    "download",
    "file",
    "image",
    "text",
    "number",
    "date",
    "time",
    "phone",
    "address",
    "name",
    "code",
    "null",
    "empty",
    "blank",
    "valid",
    "invalid",
    "max",
    "min",
    "limit",
    "timeout",
    "expire",
    "refresh",
    "back",
    "next",
    "previous",
    "home",
    "dang",
    "nhap",
    "kiem",
    "tra",
    "ket",
    "qua",
    "mong",
    "doi",
    "buoc",
    "dieu",
    "kien",
    "truoc",
    "sau",
    "he",
    "thong",
}

_HALLUCINATION_SIGNALS = re.compile(
    r"\b(\d{4,}|\$\d+|€\d+|\d+%|\d+\s*(usd|vnd|eur|gbp)|"
    r"[A-Z]{3,}_[A-Z_]+|"  # hằng số kiểu ENUM_VALUE_SPECIFIC
    r"v\d+\.\d+\.\d+|"  # version cụ thể
    r"(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+\d{4})\b",
    re.IGNORECASE,
)


def _hallucination_rate(requirement: str, test_cases: list[dict]) -> MetricResult:
    """
    Tỷ lệ TC chứa thông tin không xuất hiện trong requirement.
    Heuristic:
      1. Lấy keyword đặc trưng từ TC (loại bỏ generic tech words).
      2. Nếu keyword không xuất hiện trong requirement → flag hallucination.
      3. Kiểm tra thêm pattern số cụ thể, enum, version không có trong req.
    """
    req_normalized = _normalize(requirement)
    req_kws = _keywords(requirement)

    hallucinated_ids = []
    detail = []

    for tc in test_cases:
        tc_id = tc.get("id", "?")
        tc_text = _tc_text(tc)
        tc_kws = _keywords(tc_text) - _GENERIC_TECH_KWS

        # Keywords xuất hiện trong TC nhưng không có trong requirement
        novel_kws = {
            kw
            for kw in tc_kws
            if kw not in req_normalized and kw not in req_kws and len(kw) >= 4
        }

        # Pattern cụ thể (số, version) trong TC nhưng không trong requirement
        tc_signals = _HALLUCINATION_SIGNALS.findall(tc_text)
        req_signals = _HALLUCINATION_SIGNALS.findall(requirement)
        novel_signals = [
            s[0] for s in tc_signals if s[0].lower() not in requirement.lower()
        ]

        issues = list(novel_kws)[:3] + novel_signals[:2]
        if len(issues) >= 2:  # Cần >=2 dấu hiệu để tránh false positive
            hallucinated_ids.append(tc_id)
            if len(detail) < 8:
                detail.append(
                    f"🔮 {tc_id}: có thông tin lạ — {', '.join(str(x) for x in issues[:3])}"
                )

    total = len(test_cases)
    pct = round(len(hallucinated_ids) / total * 100, 1) if total else 0.0
    label, color = _label_and_color(pct, "low_good")
    explanation = (
        f"{len(hallucinated_ids)}/{total} TC chứa thông tin "
        "không xuất hiện trong requirement ban đầu."
    )

    return MetricResult(
        name="Hallucination Rate",
        value=pct,
        direction="low_good",
        label=label,
        color=color,
        explanation=explanation,
        violation_ids=hallucinated_ids,
        detail_lines=detail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_quality(
    requirement: str,
    test_cases: list[dict],
    variant_id: str = "",
    variant_name: str = "",
) -> QualityReport:
    """
    Tính đầy đủ 6 chỉ số chất lượng cho một bộ TC.

    Args:
        requirement : Văn bản requirement gốc.
        test_cases  : Danh sách TC dict (đã sanitise).
        variant_id  : ID variant prompt (để gắn vào report).
        variant_name: Tên variant prompt.

    Returns:
        QualityReport chứa 6 MetricResult + summary_score.
    """
    metrics = [
        _requirement_coverage(requirement, test_cases),
        _precision(test_cases),
        _invalid_tc_rate(test_cases),
        _omission_rate(requirement, test_cases),
        _redundancy_rate(test_cases),
        _hallucination_rate(requirement, test_cases),
    ]

    return QualityReport(
        variant_id=variant_id,
        variant_name=variant_name,
        total_tc=len(test_cases),
        metrics=metrics,
    )


def evaluate_all_variants(
    requirement: str,
    variant_runs: list,  # list of LabVariantRun (duck-typed)
) -> list[QualityReport]:
    """
    Tính QualityReport cho tất cả variant đã chạy thành công.
    Dùng trong Prompt Lab sau khi có kết quả.
    """
    reports = []
    for run in variant_runs:
        if not run.success:
            continue
        tcs = run.evaluation.raw_tc_list if run.evaluation else []
        report = evaluate_quality(
            requirement=requirement,
            test_cases=tcs,
            variant_id=run.variant_id,
            variant_name=run.variant_name,
        )
        reports.append(report)
    return reports
