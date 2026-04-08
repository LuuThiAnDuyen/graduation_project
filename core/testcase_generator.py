"""
core/testcase_generator.py
---------------------------
Pipeline chính: requirement → LLM → validate → kết quả chuẩn.

FIX v3.1:
  • MIN_STEPS chuyển thành WARNING threshold, KHÔNG loại bỏ hay chặn TC
  • Các TC có ít steps (API/DB TC, redirect TC) là hợp lệ — không nên báo lỗi rác
  • Thêm _normalise_steps(): tách steps nếu LLM nhét nhiều actions vào 1 string
  • Cross-validate test_data_ref cải thiện: log rõ hơn, không crash
"""

from __future__ import annotations
import logging
from core.llm_client import call_llm
from core.prompt_builder import build_generate_prompt

logger = logging.getLogger(__name__)

VALID_PRIORITIES = {"High", "Medium", "Low"}
VALID_COVERAGE_TYPES = {"P", "N", "B", "E", "S", "U", "DB", "INT"}

# Ngưỡng log warning — không reject TC có ít hơn số này
_STEPS_WARN_THRESHOLD = 2


# ─────────────────────────────────────────────
# NORMALISE STEPS
# ─────────────────────────────────────────────
def _normalise_steps(steps_raw) -> list[str]:
    """
    LLM đôi khi nhét nhiều actions vào 1 string với dấu xuống dòng,
    hoặc trả steps dạng numbered string thay vì list.
    Hàm này chuẩn hoá thành list[str] sạch.
    """
    if not steps_raw:
        return []

    # Nếu LLM trả về string thay vì list
    if isinstance(steps_raw, str):
        # Thử split theo số thứ tự "1. xxx\n2. xxx"
        numbered = re.findall(r"\d+\.\s+(.+)", steps_raw)
        if numbered:
            return [s.strip() for s in numbered if s.strip()]
        # Fallback: split theo dòng
        return [s.strip() for s in steps_raw.splitlines() if s.strip()]

    if not isinstance(steps_raw, list):
        return [str(steps_raw)]

    result = []
    for item in steps_raw:
        item_str = str(item).strip()
        if not item_str:
            continue
        # Nếu 1 item chứa nhiều bước (LLM nhét \n vào)
        if "\n" in item_str:
            sub = [s.strip() for s in item_str.splitlines() if s.strip()]
            result.extend(sub)
        else:
            result.append(item_str)

    return result


import re  # noqa: E402 — import sau hàm để tránh vòng lặp


# ─────────────────────────────────────────────
# SANITISE TEST CASE
# ─────────────────────────────────────────────
def _sanitise_tc(raw: dict, idx: int) -> dict:
    tc_id = raw.get("id") or f"TC-{idx:03d}"

    steps = _normalise_steps(raw.get("steps"))

    # Log warning nếu ít steps — NHƯNG không reject TC
    if len(steps) < _STEPS_WARN_THRESHOLD:
        logger.warning(
            f"{tc_id}: chỉ có {len(steps)} step(s) sau normalise. "
            f"Kiểm tra lại chất lượng nếu đây không phải API/redirect TC."
        )

    priority = raw.get("priority", "Medium")
    if priority not in VALID_PRIORITIES:
        logger.warning(f"{tc_id}: priority='{priority}' không hợp lệ → dùng 'Medium'.")
        priority = "Medium"

    coverage_type = raw.get("coverage_type", "P")
    if coverage_type not in VALID_COVERAGE_TYPES:
        logger.warning(
            f"{tc_id}: coverage_type='{coverage_type}' không hợp lệ → dùng 'P'."
        )
        coverage_type = "P"

    return {
        "id": tc_id,
        "title": (raw.get("title") or f"Test case {idx}").strip(),
        "coverage_type": coverage_type,
        "priority": priority,
        "precondition": (raw.get("precondition") or "").strip(),
        "steps": steps,
        "steps_text": "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)),
        "expected_result": (raw.get("expected_result") or "").strip(),
        "actual_result": "",  # luôn trống — tester điền sau khi chạy
        "status_result": "",  # luôn trống — tester điền Pass/Fail
        "db_query": (raw.get("db_query") or "").strip(),
        "db_expected": (raw.get("db_expected") or "").strip(),
        "test_data_ref": (raw.get("test_data_ref") or "").strip(),
    }


# ─────────────────────────────────────────────
# SANITISE TEST DATA ENTRY
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# CROSS-VALIDATE REFS
# ─────────────────────────────────────────────
def _validate_refs(test_cases: list[dict], test_data_set: list[dict]) -> None:
    td_ids = {td["id"] for td in test_data_set}
    broken = []
    for tc in test_cases:
        ref = tc.get("test_data_ref")
        if ref and ref not in td_ids:
            broken.append(f"{tc['id']}→{ref}")
    if broken:
        logger.warning(
            f"test_data_ref không khớp ({len(broken)} TCs): {', '.join(broken)}"
        )


# ─────────────────────────────────────────────
# PUBLIC: MAIN PIPELINE
# ─────────────────────────────────────────────
def run_pipeline(
    requirement: str,
    input_type: str = "User Story",
    language: str = "English",
) -> dict:
    """
    Entry point duy nhất (Streamlit, FastAPI, CLI).
    Số TC được quyết định 100% bởi nội dung requirement.
    """

    def _empty(reason: str, status: str = "ERROR") -> dict:
        return {
            "status": status,
            "reason": reason,
            "feature_name": "",
            "test_cases": [],
            "test_data_set": [],
        }

    # 1. Client-side validation
    if not requirement or len(requirement.strip()) < 10:
        return _empty("Requirement quá ngắn hoặc trống.", "INPUT_AMBIGUOUS")

    # 2. Build prompt
    prompt = build_generate_prompt(
        requirement=requirement.strip(),
        input_type=input_type,
        language=language,
    )

    # 3. Call LLM
    raw_result = call_llm(prompt)
    if raw_result is None:
        return _empty(
            "LLM không trả về dữ liệu sau nhiều lần thử. "
            "Kiểm tra GEMINI_API_KEY và kết nối mạng."
        )

    # 4. Check LLM status field
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

    # 5. Validate test_cases
    raw_cases = raw_result.get("test_cases")
    if not isinstance(raw_cases, list) or len(raw_cases) == 0:
        return {
            **_empty("LLM trả về nhưng thiếu 'test_cases' hoặc rỗng."),
            "feature_name": raw_result.get("feature_name", ""),
        }

    sanitised_tc = [_sanitise_tc(tc, i + 1) for i, tc in enumerate(raw_cases)]
    logger.info(f"Sinh được {len(sanitised_tc)} test cases.")

    # 6. Validate test_data_set
    raw_td = raw_result.get("test_data_set")
    if not isinstance(raw_td, list):
        logger.warning("Không có 'test_data_set' hợp lệ — dùng danh sách rỗng.")
        raw_td = []
    sanitised_td = [_sanitise_td(td, i + 1) for i, td in enumerate(raw_td)]
    logger.info(f"Sinh được {len(sanitised_td)} test data entries.")

    # 7. Cross-validate refs
    _validate_refs(sanitised_tc, sanitised_td)

    return {
        "status": "SUCCESS",
        "reason": "",
        "feature_name": raw_result.get("feature_name", ""),
        "test_cases": sanitised_tc,
        "test_data_set": sanitised_td,
    }
