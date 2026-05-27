"""
core/testcase_generator.py
---------------------------
Pipeline chính: requirement → LLM → validate → kết quả chuẩn.

Thay đổi so với v1:
  • run_pipeline() nhận thêm tham số weights: DimensionWeightConfig | None
    để truyền xuống evaluate() (dùng trong Generator tab)
"""

from __future__ import annotations
import re, logging
from typing import Optional

from core.llm_client import call_llm
from core.prompt_builder import build_generate_prompt
from core.tc_evaluator import DimensionWeightConfig

logger = logging.getLogger(__name__)

VALID_PRIORITIES = {"High", "Medium", "Low"}
VALID_COVERAGE_TYPES = {"P", "N", "B", "E", "S", "U", "DB", "INT"}
_STEPS_WARN_THRESHOLD = 2


def _normalise_steps(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        numbered = re.findall(r"\d+\.\s+(.+)", raw)
        if numbered:
            return [s.strip() for s in numbered if s.strip()]
        return [s.strip() for s in raw.splitlines() if s.strip()]
    if not isinstance(raw, list):
        return [str(raw)]
    result = []
    for item in raw:
        item_str = str(item).strip()
        if not item_str:
            continue
        if "\n" in item_str:
            result.extend(s.strip() for s in item_str.splitlines() if s.strip())
        else:
            result.append(item_str)
    return result


def _clean_element_name(line: str) -> str:
    line = line.strip()
    if not line or line.upper() == "N/A":
        return "N/A"
    if "=" in line:
        element_name = line.split("=")[0].strip()
        if element_name:
            return element_name
        parts = line.split("=")
        return parts[-1].strip() if parts[-1].strip() else "N/A"
    return line


def _normalise_element_locator(raw, steps: list[str]) -> str:
    if not raw:
        lines = ["N/A"] * len(steps)
    elif isinstance(raw, list):
        lines = [str(item).strip() for item in raw]
    else:
        lines = [line.strip() for line in str(raw).split("\n") if line.strip()]

    lines = [_clean_element_name(line) for line in lines]

    n = len(steps)
    if len(lines) < n:
        lines += ["N/A"] * (n - len(lines))
    elif len(lines) > n:
        lines = lines[:n]

    return "\n".join(lines)


def _sanitise_tc(raw: dict, idx: int) -> dict:
    if not isinstance(raw, dict):
        logger.warning(
            f"TC-{idx:03d}: expected dict, got {type(raw).__name__}: {str(raw)[:100]}"
        )
        raw = {"title": str(raw)} if raw else {}
    tc_id = raw.get("id") or f"TC-{idx:03d}"
    steps = _normalise_steps(raw.get("steps"))
    if len(steps) < _STEPS_WARN_THRESHOLD:
        logger.warning(f"{tc_id}: chỉ có {len(steps)} step(s).")
    priority = raw.get("priority", "Medium")
    if priority not in VALID_PRIORITIES:
        priority = "Medium"
    ctype = raw.get("coverage_type", "P")
    if ctype not in VALID_COVERAGE_TYPES:
        ctype = "P"

    element_locator = _normalise_element_locator(raw.get("element_locator"), steps)

    return {
        "id": tc_id,
        "feature_group": (raw.get("feature_group") or "General").strip(),
        "title": (raw.get("title") or f"Test case {idx}").strip(),
        "coverage_type": ctype,
        "priority": priority,
        "precondition": (raw.get("precondition") or "").strip(),
        "steps": steps,
        "steps_text": "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)),
        "element_locator": element_locator,
        "expected_result": (raw.get("expected_result") or "").strip(),
        "actual_result": "",
        "status_result": "",
        "db_query": (raw.get("db_query") or "").strip(),
        "db_expected": (raw.get("db_expected") or "").strip(),
        "test_data_ref": (raw.get("test_data_ref") or "").strip(),
    }


def _sanitise_td(raw: dict, idx: int) -> dict:
    td_id = raw.get("id") or f"TD-{idx:03d}"
    data = raw.get("data")
    if not isinstance(data, dict):
        data = {"value": str(data)} if data else {}
    return {
        "id": td_id,
        "description": (raw.get("description") or "").strip(),
        "data": data,
        "data_text": "\n".join(f"{k}: {v}" for k, v in data.items()),
    }


def _validate_refs(test_cases: list[dict], test_data_set: list[dict]) -> None:
    td_ids = {td["id"] for td in test_data_set}
    broken = [
        f"{tc['id']}→{tc.get('test_data_ref')}"
        for tc in test_cases
        if tc.get("test_data_ref") and tc["test_data_ref"] not in td_ids
    ]
    if broken:
        logger.warning(
            f"test_data_ref không khớp ({len(broken)} TCs): {', '.join(broken)}"
        )


def run_pipeline(
    requirement: str,
    input_type: str = "User Story",
    language: str = "English",
    weights: Optional[DimensionWeightConfig] = None,
    use_error_analysis: bool = False,
) -> dict:
    """
    Pipeline chính sinh test cases.

    Parameters
    ----------
    weights : DimensionWeightConfig | None
        Trọng số tuỳ chỉnh cho 6 chiều đánh giá.
        None → dùng DEFAULT_WEIGHTS (Balanced).
    use_error_analysis : bool
        True → chạy phân tích 7 loại lỗi rule-based sau generate.
    """

    def _empty(reason, status="ERROR"):
        return {
            "status": status,
            "reason": reason,
            "feature_name": "",
            "test_cases": [],
            "test_data_set": [],
        }

    if not requirement or len(requirement.strip()) < 10:
        return _empty("Requirement quá ngắn hoặc trống.", "INPUT_AMBIGUOUS")

    prompt = build_generate_prompt(requirement.strip(), input_type, language)
    raw_result = call_llm(prompt)

    if raw_result is None:
        return _empty(
            "LLM không trả về dữ liệu. Kiểm tra GEMINI_API_KEY và kết nối mạng."
        )

    if isinstance(raw_result, list):
        raw_result = {
            "status": "SUCCESS",
            "reason": "",
            "feature_name": "",
            "test_cases": raw_result,
            "test_data_set": [],
        }

    llm_status = raw_result.get("status", "SUCCESS")
    if llm_status == "INPUT_AMBIGUOUS":
        return {
            "status": "INPUT_AMBIGUOUS",
            "reason": raw_result.get("reason", "LLM đánh giá input chưa đủ rõ ràng."),
            "feature_name": raw_result.get("feature_name", ""),
            "test_cases": [],
            "test_data_set": [],
        }
    if llm_status == "ERROR":
        return _empty(raw_result.get("reason", "LLM báo lỗi không xác định."))

    raw_cases = raw_result.get("test_cases")
    if not isinstance(raw_cases, list) or len(raw_cases) == 0:
        return {
            **_empty("LLM trả về nhưng thiếu 'test_cases' hoặc rỗng."),
            "feature_name": raw_result.get("feature_name", ""),
        }

    valid_cases = [tc for tc in raw_cases if isinstance(tc, dict)]
    invalid_count = len(raw_cases) - len(valid_cases)
    if invalid_count > 0:
        logger.warning(
            f"Bỏ qua {invalid_count} test cases không hợp lệ (không phải dict)"
        )
    if not valid_cases:
        return {
            **_empty("LLM trả về test_cases nhưng không có entry nào hợp lệ."),
            "feature_name": raw_result.get("feature_name", ""),
        }

    sanitised_tc = [_sanitise_tc(tc, i + 1) for i, tc in enumerate(valid_cases)]
    logger.info(f"Sinh được {len(sanitised_tc)} test cases.")

    raw_td = raw_result.get("test_data_set")
    if not isinstance(raw_td, list):
        raw_td = []
    sanitised_td = [_sanitise_td(td, i + 1) for i, td in enumerate(raw_td)]
    _validate_refs(sanitised_tc, sanitised_td)

    result = {
        "status": "SUCCESS",
        "reason": "",
        "feature_name": raw_result.get("feature_name", ""),
        "test_cases": sanitised_tc,
        "test_data_set": sanitised_td,
        "_weights": weights,
    }

    # ── Error Analysis (optional) ──────────────────────────────────────────
    if use_error_analysis:
        try:
            from core.error_analyzer import analyze_errors

            error_report = analyze_errors(
                requirement=requirement,
                test_cases=sanitised_tc,
                test_data_set=sanitised_td,
                use_llm_judge=False,  # Generator không gọi LLM Judge
            )
            result["error_report"] = error_report
            logger.info(
                f"Error analysis: {error_report.total_errors} errors "
                f"({error_report.critical_count} critical)"
            )
        except Exception as exc:
            logger.error(f"Error analysis in pipeline failed: {exc}", exc_info=True)

    return result
