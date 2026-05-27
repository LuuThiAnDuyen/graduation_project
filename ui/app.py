"""
app.py  –  Streamlit frontend
================================
Pages:
  1. 🧪 Generator   — sinh TC từ requirement (prompt có thể được override từ Lab)
  2. 🔬 Prompt Lab  — chạy N prompt variants P1–P5, so sánh, export Excel

Prompt Strategy (tăng dần mức độ cấu trúc):
  P1 – Basic Prompt          : Chỉ yêu cầu sinh test case, không hướng dẫn thêm.
  P2 – Role-based Prompt     : Xác định vai trò chuyên gia kiểm thử.
  P3 – Step-by-step Prompt   : Hướng dẫn phân tích từng bước.
  P4 – Structured Output     : Yêu cầu đầu ra JSON có cấu trúc cụ thể.
  P5 – Full Prompt Framework : Kết hợp vai trò + phân tích + coverage + định dạng.

6 chiều đánh giá:
  Coverage Breadth · Clarity · Test Data Quality
  Security Coverage · Boundary & Edge Coverage · Requirement Traceability
"""

from __future__ import annotations

from builtins import list
import os, sys, json, time, logging
from datetime import datetime
from io import BytesIO

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.testcase_generator import run_pipeline
from core.excel_exporter import to_excel
from core.input_validator import validate_input, IssueSeverity
from core.prompt_variants import VARIANTS, PRESET_GROUPS, get_variant, build_prompt
from core.prompt_lab import run_prompt_lab
from core.lab_exporter import lab_to_excel
from core.llm_client import call_llm
from core.testcase_generator import _sanitise_tc, _sanitise_td
from core.tc_evaluator import (
    DimensionWeightConfig,
    DIMENSION_KEYS,
    DIMENSION_LABELS,
    WEIGHT_PRESETS,
    DEFAULT_WEIGHTS,
)

logging.basicConfig(level=logging.INFO)
HISTORY_FILE = "history.json"

PRIORITY_EMOJI = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}
TYPE_LABEL = {
    "P": "✅ Positive",
    "N": "❌ Negative",
    "B": "🔢 Boundary",
    "E": "⚠️ Edge",
    "S": "🔒 Security",
    "U": "🖥️ UX",
    "DB": "🗄️ Database",
    "INT": "🔗 Integration",
}
DISPLAY_TC_COLUMNS = {
    "id": "ID",
    "feature_group": "Feature",
    "title": "Title",
    "coverage_type": "Type",
    "priority": "Priority",
    "precondition": "Precondition",
    "steps_text": "Steps",
    "expected_result": "Expected Result",
    "actual_result": "Actual Result",
    "status_result": "Status",
    "db_query": "DB Query",
    "db_expected": "DB Expected",
    "test_data_ref": "Test Data Ref",
}

VARIANT_LEVEL_COLOR = {
    "p1_basic": "#94a3b8",
    "p2_role_based": "#60a5fa",
    "p3_step_by_step": "#34d399",
    "p4_structured_output": "#f59e0b",
    "p5_full_framework": "#8b5cf6",
}

# Icon + màu cho 6 chiều đánh giá
_DIM_ICONS = {
    "coverage_breadth": "🗂️",
    "clarity": "🔍",
    "test_data_quality": "📦",
    "security_coverage": "🔒",
    "boundary_edge_coverage": "🔢",
    "requirement_traceability": "🔗",
}
_DIM_COLORS = {
    "coverage_breadth": "#378ADD",
    "clarity": "#34d399",
    "test_data_quality": "#f59e0b",
    "security_coverage": "#ef4444",
    "boundary_edge_coverage": "#8b5cf6",
    "requirement_traceability": "#ec4899",
}
_DIM_SHORT = {
    "coverage_breadth": "Coverage",
    "clarity": "Clarity",
    "test_data_quality": "Test Data",
    "security_coverage": "Security",
    "boundary_edge_coverage": "Boundary",
    "requirement_traceability": "Traceability",
}


# ─────────────────────────────────────────────
# HISTORY helpers
# ─────────────────────────────────────────────
def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(h: list) -> None:
    def default_serializer(obj):
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2, default=default_serializer)


# ─────────────────────────────────────────────
# WEIGHT PICKER helpers
# ─────────────────────────────────────────────
def _config_to_sliders(cfg: DimensionWeightConfig) -> dict[str, int]:
    norm = cfg.normalize()
    return {k: round(getattr(norm, k) * 100) for k in DIMENSION_KEYS}


def _sliders_to_config(values: dict[str, int]) -> DimensionWeightConfig:
    return DimensionWeightConfig(
        **{k: values[k] / 100.0 for k in DIMENSION_KEYS}
    ).normalize()


def render_weight_picker(key: str = "default") -> DimensionWeightConfig:
    """
    Render UI tuỳ chỉnh trọng số 6 chiều đánh giá.
    Trả về DimensionWeightConfig đã normalize.
    """
    ss_key = f"weights_{key}"
    ss_preset_key = f"weights_preset_{key}"

    if ss_key not in st.session_state:
        st.session_state[ss_key] = _config_to_sliders(DEFAULT_WEIGHTS)
    if ss_preset_key not in st.session_state:
        st.session_state[ss_preset_key] = "balanced"

    with st.expander("⚖️ Tuỳ chỉnh trọng số đánh giá", expanded=False):
        st.caption(
            "Điều chỉnh mức độ quan trọng của từng chiều. "
            "Tổng sẽ tự động được chuẩn hoá về 100%."
        )

        # ── Preset buttons ──
        st.markdown("**Chọn profile nhanh:**")
        preset_cols = st.columns(len(WEIGHT_PRESETS))
        for col, (pid, pinfo) in zip(preset_cols, WEIGHT_PRESETS.items()):
            with col:
                is_active = st.session_state[ss_preset_key] == pid
                if st.button(
                    f"**{pinfo['label']}**",
                    key=f"preset_{key}_{pid}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                    help=pinfo["description"],
                ):
                    st.session_state[ss_preset_key] = pid
                    st.session_state[ss_key] = _config_to_sliders(pinfo["config"])
                    st.rerun()
                st.caption(pinfo["description"])

        st.divider()
        st.markdown("**Tuỳ chỉnh chi tiết:**")

        current_values: dict[str, int] = dict(st.session_state[ss_key])
        total_raw = sum(current_values.values())
        changed = False

        for i in range(0, len(DIMENSION_KEYS), 2):
            pair = DIMENSION_KEYS[i : i + 2]
            cols = st.columns(len(pair))
            for col, dim_key in zip(cols, pair):
                with col:
                    icon = _DIM_ICONS[dim_key]
                    short = _DIM_SHORT[dim_key]
                    color = _DIM_COLORS[dim_key]
                    norm_pct = (
                        round(current_values[dim_key] / total_raw * 100)
                        if total_raw > 0
                        else 0
                    )
                    st.markdown(
                        f"**{icon} {short}** "
                        f"<span style='color:{color};font-weight:600;'>→ {norm_pct}%</span>",
                        unsafe_allow_html=True,
                    )
                    new_val = st.slider(
                        label=short,
                        min_value=0,
                        max_value=100,
                        value=current_values[dim_key],
                        step=5,
                        key=f"slider_{key}_{dim_key}",
                        label_visibility="collapsed",
                    )
                    if new_val != current_values[dim_key]:
                        current_values[dim_key] = new_val
                        changed = True

        if changed:
            st.session_state[ss_key] = current_values
            st.session_state[ss_preset_key] = "custom"
            st.rerun()

        # ── Visual weight bar ──
        st.divider()
        total_check = sum(current_values.values())

        if total_check == 0:
            st.error("⚠️ Tất cả trọng số = 0. Vui lòng điều chỉnh.")
            return DEFAULT_WEIGHTS

        bar_html = '<div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin:8px 0;">'
        for dim_key in DIMENSION_KEYS:
            pct = current_values[dim_key] / total_check * 100
            if pct > 0:
                color = _DIM_COLORS[dim_key]
                bar_html += (
                    f'<div style="width:{pct:.1f}%;background:{color};" '
                    f'title="{_DIM_SHORT[dim_key]}: {pct:.0f}%"></div>'
                )
        bar_html += "</div>"
        st.markdown(bar_html, unsafe_allow_html=True)

        summary_parts = []
        for dim_key in DIMENSION_KEYS:
            norm_pct = round(current_values[dim_key] / total_check * 100)
            icon = _DIM_ICONS[dim_key]
            color = _DIM_COLORS[dim_key]
            summary_parts.append(
                f'<span style="margin-right:12px;">'
                f"{icon} <b>{_DIM_SHORT[dim_key]}</b>: "
                f'<span style="color:{color};font-weight:600;">{norm_pct}%</span>'
                f"</span>"
            )
        st.markdown(
            '<div style="font-size:0.85em;line-height:2;">'
            + "".join(summary_parts)
            + "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("")
        if st.button("↩️ Reset về Balanced", key=f"reset_weights_{key}"):
            st.session_state[ss_key] = _config_to_sliders(DEFAULT_WEIGHTS)
            st.session_state[ss_preset_key] = "balanced"
            st.rerun()

    return _sliders_to_config(st.session_state[ss_key])


# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AI Test Case Generator",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

_defaults = {
    "history": load_history(),
    "selected_history": None,
    "last_result": None,
    "lab_result": None,
    "active_variant_id": None,
    "active_variant_name": None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    input_type = st.selectbox(
        "Loại requirement",
        ["User Story", "Use Case Spec", "Natural Language"],
        help="Giúp AI đọc đúng định dạng requirement của bạn",
    )
    language = st.selectbox("Ngôn ngữ output", ["English", "Tiếng Việt"])

    st.divider()
    if st.session_state.active_variant_id:
        vid = st.session_state.active_variant_id
        vcolor = VARIANT_LEVEL_COLOR.get(vid, "#1e40af")
        st.markdown(
            f"""<div style="background:{vcolor};color:white;border-radius:8px;
            padding:10px 12px;font-size:0.9em;">
            🎯 <b>Active Prompt</b><br>
            <span style="font-size:1em;">{st.session_state.active_variant_name}</span>
            </div>""",
            unsafe_allow_html=True,
        )
        if st.button("↩️ Reset về Default", use_container_width=True):
            st.session_state.active_variant_id = None
            st.session_state.active_variant_name = None
            st.rerun()
    else:
        st.caption("🎯 **Active Prompt:** Default")

    st.divider()
    st.caption("📊 **Mức độ cấu trúc prompt:**")
    for v in VARIANTS:
        color = VARIANT_LEVEL_COLOR.get(v.id, "#888")
        st.markdown(
            f"""<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <div style="width:12px;height:12px;border-radius:50%;background:{color};
            flex-shrink:0;"></div>
            <span style="font-size:0.82em;">{v.name}</span></div>""",
            unsafe_allow_html=True,
        )

    st.divider()
    st.subheader("🕘 Lịch sử Generator")
    if st.session_state.history:
        labels = [
            f"{i+1}. [{h.get('time','')}] {(h.get('feature_name') or h.get('input',''))[:25]}..."
            for i, h in enumerate(st.session_state.history)
        ]
        idx = st.selectbox(
            "Chọn session", range(len(labels)), format_func=lambda i: labels[i]
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Xem"):
                st.session_state.selected_history = st.session_state.history[idx]
        with c2:
            if st.button("🗑️ Xoá tất cả"):
                st.session_state.history = []
                st.session_state.selected_history = None
                save_history([])
                st.rerun()
    else:
        st.caption("Chưa có lịch sử.")


# ─────────────────────────────────────────────
# SHARED: INPUT PANEL
# ─────────────────────────────────────────────
def render_input_panel(key_prefix: str = "") -> str:
    mode = st.radio(
        "Nguồn input",
        ["✏️ Nhập tay", "📁 Upload file"],
        horizontal=True,
        key=f"{key_prefix}_mode",
    )
    user_input = ""
    if mode == "✏️ Nhập tay":
        user_input = st.text_area(
            "Nhập requirement / user story / use case:",
            height=220,
            placeholder=(
                "Ví dụ (User Story):\n"
                "Story 1 – Đăng nhập\n"
                "As a registered user I want to log in with email and password "
                "so that I can access my account.\n"
                "Acceptance Criteria:\n"
                "- Email and password are required\n"
                "- Wrong credentials: show 'Invalid email or password'\n"
                "- Lock after 5 failed attempts\n\n"
                "Story 2 – Đặt lại mật khẩu\n"
                "As a user I want to reset my password via email...\n\n"
                "Gợi ý chức năng thực nghiệm: đăng nhập, đăng ký tài khoản, "
                "tìm kiếm, đặt hàng, thanh toán, quản lý sản phẩm, quản lý người dùng."
            ),
            key=f"{key_prefix}_text",
        )
    else:
        uploaded = st.file_uploader(
            "Upload file", type=["txt", "docx", "pdf"], key=f"{key_prefix}_file"
        )
        if uploaded:
            ext = uploaded.name.rsplit(".", 1)[-1].lower()
            try:
                if ext == "txt":
                    user_input = uploaded.read().decode("utf-8")
                elif ext == "docx":
                    from docx import Document

                    doc = Document(uploaded)
                    user_input = "\n".join(
                        p.text for p in doc.paragraphs if p.text.strip()
                    )
                elif ext == "pdf":
                    from pypdf import PdfReader

                    reader = PdfReader(uploaded)
                    user_input = "\n".join(
                        page.extract_text() or "" for page in reader.pages
                    )
                st.success(f"✅ Đã đọc: {uploaded.name} ({len(user_input)} ký tự)")
                with st.expander("Xem nội dung file"):
                    st.text(
                        user_input[:3000] + ("..." if len(user_input) > 3000 else "")
                    )
            except Exception as e:
                st.error(f"Lỗi đọc file: {e}")
    return user_input


# ─────────────────────────────────────────────
# SHARED: INPUT VALIDATOR UI
# ─────────────────────────────────────────────
def render_validation_panel(user_input: str, input_type: str) -> bool:
    if not user_input.strip():
        return False

    vr = validate_input(user_input, input_type)

    col_score, col_summary = st.columns([1, 5])
    with col_score:
        st.markdown(
            f"""<div style="background:{vr.quality_color};color:white;border-radius:8px;
            padding:10px;text-align:center;font-weight:bold;font-size:1.1em;">
            {vr.quality_score}/100<br><small>{vr.quality_label}</small></div>""",
            unsafe_allow_html=True,
        )
    with col_summary:
        if vr.detected_features:
            unique_features = list(dict.fromkeys(vr.detected_features))
            st.caption(f"📌 Features phát hiện: {', '.join(unique_features)}")
        if vr.estimated_tc_count and vr.estimated_tc_count != "N/A":
            st.caption(f"📊 Ước lượng: {vr.estimated_tc_count}")

        if vr.quality_score < 100 and vr.issues:
            tips = []
            for issue in vr.issues:
                if issue.severity == IssueSeverity.CRITICAL:
                    tips.append(f"🔴 **{issue.title}** — {issue.suggestion}")
                elif issue.severity == IssueSeverity.WARNING:
                    tips.append(f"🟡 **{issue.title}** — {issue.suggestion}")
                else:
                    tips.append(f"💡 **{issue.title}** — {issue.suggestion}")
            with st.expander("✏️ Gợi ý để cải thiện requirement", expanded=False):
                for tip in tips:
                    st.markdown(tip)

    return vr.can_generate


# ─────────────────────────────────────────────
# SHARED: DISPLAY RESULTS
# ─────────────────────────────────────────────
def render_tc_results(
    test_cases: list,
    test_data_set: list,
    feature_name: str,
    user_input: str = "",
    error_report=None,
):
    total = len(test_cases)
    highs = sum(1 for tc in test_cases if tc.get("priority") == "High")
    types: dict = {}
    for tc in test_cases:
        t = tc.get("coverage_type", "P")
        types[t] = types.get(t, 0) + 1

    groups: dict = {}
    for tc in test_cases:
        fg = tc.get("feature_group", "General")
        groups[fg] = groups.get(fg, 0) + 1

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Test Cases", total)
    m2.metric("High Priority", highs)
    m3.metric("Coverage Types", len(types))
    m4.metric("Test Data Entries", len(test_data_set))
    m5.metric("Features / Modules", len(groups))

    if len(groups) > 1:
        with st.expander(f"📁 {len(groups)} Features/Modules được phát hiện"):
            for fg, count in sorted(groups.items()):
                st.write(f"  • **{fg}**: {count} test cases")

    with st.expander("📊 Coverage Breakdown"):
        st.dataframe(
            pd.DataFrame(
                [
                    {"Type": TYPE_LABEL.get(k, k), "Count": v}
                    for k, v in sorted(types.items())
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    tab_table, tab_detail, tab_td, tab_input, tab_errors = st.tabs(
        [
            "📊 Table View",
            "🔍 Detail View",
            "🗂️ Test Data",
            "📄 Input",
            "⚠️ Error Analysis",
        ]
    )

    with tab_table:
        df = pd.DataFrame(test_cases)
        display_cols = [k for k in DISPLAY_TC_COLUMNS if k in df.columns]
        df2 = df[display_cols].rename(columns=DISPLAY_TC_COLUMNS).copy()
        if "Priority" in df2.columns:
            df2["Priority"] = df2["Priority"].apply(
                lambda p: f"{PRIORITY_EMOJI.get(p,'')} {p}"
            )
        if "Type" in df2.columns:
            df2["Type"] = df2["Type"].apply(lambda t: TYPE_LABEL.get(t, t))
        st.dataframe(df2, use_container_width=True, height=500, hide_index=True)

    with tab_detail:
        grouped: dict[str, list] = {}
        for tc in test_cases:
            fg = tc.get("feature_group", "General")
            grouped.setdefault(fg, []).append(tc)

        for fg, tcs in grouped.items():
            if len(grouped) > 1:
                st.markdown(
                    f"### 📁 {fg}  <small style='color:#666;font-size:0.8em;'>({len(tcs)} TCs)</small>",
                    unsafe_allow_html=True,
                )
            for tc in tcs:
                p = tc.get("priority", "Medium")
                ct = TYPE_LABEL.get(tc.get("coverage_type", "P"), "")
                with st.expander(
                    f"{PRIORITY_EMOJI.get(p,'')} **{tc['id']}** – {tc['title']}  |  {ct}"
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"**Priority:** {p}")
                    c2.write(f"**Type:** {ct}")
                    c3.write(f"**Test Data Ref:** {tc.get('test_data_ref') or '–'}")
                    st.write("**Precondition:**")
                    st.info(tc.get("precondition") or "–")
                    st.write("**Steps:**")
                    for i, step in enumerate(tc.get("steps", []), 1):
                        st.write(f"  {i}. {step}")
                    st.write("**Expected Result:**")
                    st.success(tc.get("expected_result") or "–")
                    ca, cb = st.columns(2)
                    ca.write("**Actual Result:** *(fill after execution)*")
                    cb.write("**Status:** *(Pass / Fail)*")
                    if tc.get("db_query"):
                        st.write("**DB Verification:**")
                        st.code(tc["db_query"], language="sql")
                        st.write("**DB Expected:**", tc.get("db_expected"))

    with tab_td:
        if test_data_set:
            df_td = pd.DataFrame(test_data_set)
            st.dataframe(
                df_td[["id", "description", "data_text"]].rename(
                    columns={
                        "id": "TD ID",
                        "description": "Description",
                        "data_text": "Data",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
            for td in test_data_set:
                with st.expander(f"**{td['id']}** – {td.get('description','')}"):
                    st.json(td.get("data", {}))
        else:
            st.info("Không có test data entry.")

    with tab_input:
        st.text_area(
            "Requirement đã dùng:", value=user_input, height=300, disabled=True
        )

    with tab_errors:
        if error_report is not None:
            from core.error_analyzer import render_error_report_streamlit

            render_error_report_streamlit(error_report)
        else:
            st.info(
                "⚠️ Error Analysis chưa được chạy.\n\n"
                "Bật toggle **🔍 Error Analysis** trong phần tuỳ chọn nâng cao "
                "rồi Generate lại để xem báo cáo lỗi chi tiết."
            )
            st.caption(
                "Error Analysis phát hiện 7 loại lỗi:\n"
                "E1 Bỏ sót yêu cầu · E2 Thiếu dữ liệu · E3 Expected result sai · "
                "E4 Suy diễn ngoài yêu cầu · E5 Thiếu TC âm tính/biên · "
                "E6 Trùng lặp · E7 Mâu thuẫn steps↔expected"
            )


# ─────────────────────────────────────────────
# GENERATOR: run with active variant or default
# ─────────────────────────────────────────────
def _run_with_active_variant(
    requirement: str,
    input_type: str,
    language: str,
    weights: DimensionWeightConfig | None = None,
    use_error_analysis: bool = False,
) -> dict:
    variant_id = st.session_state.get("active_variant_id")
    if not variant_id:
        return run_pipeline(
            requirement=requirement,
            input_type=input_type,
            language=language,
            weights=weights,
            use_error_analysis=use_error_analysis,
        )

    try:
        prompt = build_prompt(variant_id, requirement, input_type, language)
    except ValueError:
        st.session_state.active_variant_id = None
        return run_pipeline(
            requirement=requirement,
            input_type=input_type,
            language=language,
            weights=weights,
            use_error_analysis=use_error_analysis,
        )

    raw_result = call_llm(prompt)
    if raw_result is None:
        return {
            "status": "ERROR",
            "reason": "LLM không trả về dữ liệu. Kiểm tra API key.",
            "feature_name": "",
            "test_cases": [],
            "test_data_set": [],
        }

    if isinstance(raw_result, list):
        raw_result = {
            "status": "SUCCESS",
            "reason": "",
            "feature_name": "",
            "test_cases": raw_result,
            "test_data_set": [],
        }

    llm_status = raw_result.get("status", "SUCCESS")
    if llm_status != "SUCCESS":
        return {
            "status": llm_status,
            "reason": raw_result.get("reason", ""),
            "feature_name": raw_result.get("feature_name", ""),
            "test_cases": [],
            "test_data_set": [],
        }

    raw_cases = raw_result.get("test_cases", [])
    raw_td = raw_result.get("test_data_set", [])
    if not isinstance(raw_cases, list):
        raw_cases = []
    if not isinstance(raw_td, list):
        raw_td = []

    return {
        "status": "SUCCESS",
        "reason": "",
        "feature_name": raw_result.get("feature_name", ""),
        "test_cases": [_sanitise_tc(tc, i + 1) for i, tc in enumerate(raw_cases)],
        "test_data_set": [_sanitise_td(td, i + 1) for i, td in enumerate(raw_td)],
    }


# ─────────────────────────────────────────────
# HELPER: render active weights badge
# ─────────────────────────────────────────────
def render_weights_badge(weights: DimensionWeightConfig, key: str) -> None:
    """Hiển thị compact badge tóm tắt weights đang active."""
    preset_key = f"weights_preset_{key}"
    preset_id = st.session_state.get(preset_key, "balanced")
    preset_label = WEIGHT_PRESETS.get(preset_id, {}).get("label", "Custom")

    norm = weights.normalize()
    parts = []
    for dim_key in DIMENSION_KEYS:
        pct = round(getattr(norm, dim_key) * 100)
        color = _DIM_COLORS[dim_key]
        parts.append(
            f'<span style="margin-right:10px;font-size:0.82em;">'
            f"{_DIM_ICONS[dim_key]} "
            f'<span style="color:{color};font-weight:600;">{pct}%</span>'
            f"</span>"
        )
    st.markdown(
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;'
        f'padding:6px 12px;margin-bottom:8px;">'
        f'⚖️ <b>Weights ({preset_label}):</b> {"".join(parts)}'
        f"</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# TAB LAYOUT
# ─────────────────────────────────────────────
tab_gen, tab_lab = st.tabs(["🧪 Generator", "🔬 Prompt Lab"])


# ═══════════════════════════════════════════════════════════════
# TAB 1: GENERATOR
# ═══════════════════════════════════════════════════════════════
with tab_gen:
    st.title("🧪 AI Test Case Generator")

    if st.session_state.active_variant_id:
        v = get_variant(st.session_state.active_variant_id)
        if v:
            vcolor = VARIANT_LEVEL_COLOR.get(v.id, "#1e40af")
            st.markdown(
                f"""<div style="background:{vcolor}22;border-left:4px solid {vcolor};
                padding:10px 14px;border-radius:4px;margin-bottom:8px;">
                🎯 <b>Đang dùng prompt từ Lab:</b> <b>{v.name}</b> — {v.description[:80]}…
                <i>(Reset về Default trong sidebar)</i></div>""",
                unsafe_allow_html=True,
            )
    else:
        st.caption(
            "Sinh test cases từ requirement — nhanh, 1 lần gọi API. "
            "Dùng **Prompt Lab** để so sánh 5 prompt strategy P1→P5."
        )

    user_input = render_input_panel("gen")

    can_gen = False
    if user_input.strip():
        st.divider()
        st.subheader("🔎 Đánh giá chất lượng requirement")
        can_gen = render_validation_panel(user_input, input_type)
        st.divider()

    # ── Error Analysis toggle (Generator) ──
    gen_error_analysis = st.toggle(
        "🔍 Error Analysis (7 loại lỗi)",
        value=False,
        key="gen_error_analysis",
        help=(
            "Phân tích 7 loại lỗi sau khi generate: "
            "E1 Bỏ sót · E2 Thiếu dữ liệu · E3 Expected result sai · "
            "E4 Suy diễn · E5 Thiếu âm tính/biên · E6 Trùng lặp · E7 Mâu thuẫn. "
            "Rule-based miễn phí. Kết hợp LLM Judge để detect E3/E4/E7."
        ),
    )

    # ── Weight picker (Generator) ──
    gen_weights = render_weight_picker(key="gen")
    render_weights_badge(gen_weights, key="gen")

    gen_clicked = st.button(
        "🚀 Generate Test Cases",
        type="primary",
        use_container_width=True,
        key="btn_gen",
        disabled=(not user_input.strip()),
    )

    if gen_clicked:
        if not user_input.strip():
            st.warning("⚠️ Vui lòng nhập requirement trước.")
        else:
            variant_label = (
                f"variant **{st.session_state.active_variant_name}**"
                if st.session_state.active_variant_id
                else "prompt mặc định"
            )
            with st.spinner(f"⏳ Đang sinh test cases với {variant_label}..."):
                result = _run_with_active_variant(
                    requirement=user_input,
                    input_type=input_type,
                    language=language,
                    weights=gen_weights,
                    use_error_analysis=gen_error_analysis,
                )

            status = result.get("status")
            if status == "INPUT_AMBIGUOUS":
                st.warning(f"⚠️ Input chưa đủ rõ ràng: {result.get('reason')}")
            elif status == "ERROR":
                st.error(f"❌ Lỗi: {result.get('reason')}")
            elif status == "SUCCESS":
                tcs = result.get("test_cases", [])
                tds = result.get("test_data_set", [])
                fname = result.get("feature_name", "testcases")

                groups = {}
                for tc in tcs:
                    fg = tc.get("feature_group", "General")
                    groups[fg] = groups.get(fg, 0) + 1
                group_str = ", ".join(f"{k} ({v})" for k, v in groups.items())

                st.success(
                    f"✅ Sinh được **{len(tcs)}** test cases | **{len(tds)}** test data "
                    f"| **{len(groups)} feature(s)** — _{group_str}_"
                )

                st.session_state.last_result = result
                record = {
                    "id": str(time.time()),
                    "input": user_input,
                    "feature_name": fname,
                    "test_cases": tcs,
                    "test_data_set": tds,
                    "time": datetime.now().strftime("%d/%m %H:%M"),
                    "variant_used": st.session_state.active_variant_name or "Default",
                    "error_report": result.get("error_report"),
                }
                st.session_state.selected_history = record
                st.session_state.history.insert(0, record)
                if len(st.session_state.history) > 20:
                    st.session_state.history = st.session_state.history[:20]
                save_history(st.session_state.history)

                safe_name = fname.replace(" ", "_")[:30]
                ts = datetime.now().strftime("%Y%m%d_%H%M")

                excel_bytes = to_excel(tcs, tds)
                sheet_info = (
                    f" ({len(groups)} sheets chức năng)" if len(groups) > 1 else ""
                )
                st.download_button(
                    f"📥 Download Excel{sheet_info}",
                    data=excel_bytes,
                    file_name=f"{safe_name}_{ts}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

                if len(groups) > 1:
                    st.caption(
                        f"📁 File Excel gồm: **{len(groups)} sheet feature** "
                        f"+ sheet **Test Data** riêng cho từng feature"
                    )

    rec = st.session_state.get("selected_history")
    if rec and isinstance(rec, dict) and rec.get("test_cases"):
        st.divider()
        variant_badge = rec.get("variant_used", "Default")
        st.subheader(
            f"📋 Test Cases – {rec.get('feature_name','')}  ·  _{variant_badge}_"
        )
        render_tc_results(
            rec["test_cases"],
            rec.get("test_data_set", []),
            rec.get("feature_name", ""),
            rec.get("input", ""),
            error_report=rec.get("error_report"),
        )


# ═══════════════════════════════════════════════════════════════
# TAB 2: PROMPT LAB
# ═══════════════════════════════════════════════════════════════
with tab_lab:
    st.title("🔬 Prompt Lab — P1 → P5")

    st.markdown("""
So sánh **5 prompt strategy** được thiết kế theo hướng **tăng dần mức độ cấu trúc**
để đánh giá ảnh hưởng của prompt engineering đến chất lượng test case sinh tự động.
""")

    level_cols = st.columns(5)
    level_descs = [
        ("P1", "Basic", "Chỉ yêu cầu sinh TC", "#94a3b8"),
        ("P2", "Role-based", "Thêm vai trò QA expert", "#60a5fa"),
        ("P3", "Step-by-step", "Hướng dẫn phân tích 6 bước", "#34d399"),
        ("P4", "Structured Output", "Ràng buộc định dạng JSON", "#f59e0b"),
        ("P5", "Full Framework", "Kết hợp tất cả", "#8b5cf6"),
    ]
    for col, (pid, pname, pdesc, pcolor) in zip(level_cols, level_descs):
        with col:
            st.markdown(
                f"""<div style="background:{pcolor}22;border:2px solid {pcolor};
                border-radius:10px;padding:10px;text-align:center;min-height:110px;">
                <div style="font-size:1.4em;font-weight:bold;color:{pcolor};">{pid}</div>
                <div style="font-weight:600;font-size:0.9em;">{pname}</div>
                <div style="font-size:0.78em;color:#666;margin-top:4px;">{pdesc}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("""
**Cách hoạt động:**
1. Nhập requirement → gửi cho N prompt variants (P1–P5)
2. Mỗi variant gọi LLM API độc lập với cùng requirement
3. Evaluator chấm điểm **6 chiều** (Coverage · Clarity · Test Data · Security · Boundary · Traceability)
4. _(Tuỳ chọn)_ LLM Judge chấm điểm semantic → tính **Hybrid Score**
5. Hiển thị kết quả theo thứ tự điểm + export Excel so sánh

**Mục tiêu nghiên cứu:** Xác định mức độ cấu trúc prompt tối ưu cho sinh test case tự động.
""")

    st.divider()

    lab_input = render_input_panel("lab")

    if lab_input.strip():
        st.subheader("🔎 Đánh giá chất lượng requirement")
        render_validation_panel(lab_input, input_type)
        st.divider()

    # ── Weight picker (Lab) ────────────────────────────────────────────────────
    lab_weights = render_weight_picker(key="lab")
    render_weights_badge(lab_weights, key="lab")

    # ── Variant selection ──────────────────────────────────────────────────────
    st.subheader("⚙️ Chọn Variants để chạy")

    preset_mode = st.radio(
        "Chế độ chọn", ["🎯 Preset", "🔧 Tùy chỉnh"], horizontal=True
    )
    selected_variant_ids: list[str] = []

    if preset_mode == "🎯 Preset":
        cols = st.columns(len(PRESET_GROUPS))
        for i, (pid, pinfo) in enumerate(PRESET_GROUPS.items()):
            with cols[i]:
                if st.button(
                    f"**{pinfo['name']}**\n\n{pinfo['description']}",
                    use_container_width=True,
                    key=f"preset_{pid}",
                ):
                    st.session_state["lab_preset"] = pid
        chosen_preset = st.session_state.get("lab_preset", "quick_3")
        selected_variant_ids = PRESET_GROUPS[chosen_preset]["variants"]
        preset_info = PRESET_GROUPS[chosen_preset]
        st.info(
            f"✅ Preset: **{preset_info['name']}** — "
            f"{len(selected_variant_ids)} variants: "
            f"{', '.join(selected_variant_ids)}"
        )
    else:
        st.write("Chọn các variants muốn so sánh:")
        cols = st.columns(5)
        custom_selected = []
        for i, v in enumerate(VARIANTS):
            with cols[i]:
                if st.checkbox(
                    f"**{v.name}**",
                    key=f"lab_v_{v.id}",
                    value=True,
                    help=v.description,
                ):
                    custom_selected.append(v.id)
        selected_variant_ids = custom_selected
        if selected_variant_ids:
            st.info(
                f"✅ Đã chọn {len(selected_variant_ids)} variants: "
                f"{', '.join(selected_variant_ids)}"
            )
        else:
            st.warning("⚠️ Chọn ít nhất 1 variant")

    # ── Lab Options ────────────────────────────────────────────────────────────
    st.subheader("🔧 Tuỳ chọn nâng cao")
    opt_col1, opt_col2, opt_col3 = st.columns(3)

    with opt_col1:
        use_parallel = st.toggle(
            "⚡ Parallel Execution",
            value=False,
            help=(
                "Chạy các variants song song → nhanh hơn ~2-3x. "
                "Tắt nếu API của bạn có rate limit chặt."
            ),
        )
        if use_parallel:
            max_workers = st.slider("Max Workers", min_value=2, max_value=5, value=3)
        else:
            max_workers = 1

    with opt_col2:
        use_llm_judge = st.toggle(
            "🧠 LLM Judge (Semantic Scoring)",
            value=False,
            help=(
                "Gọi thêm LLM để đánh giá NGỮ NGHĨA của TC: "
                "độ cụ thể của steps, chất lượng expected results, "
                "tính realistic của test data. "
                "Tốn thêm ~1 API call/variant (~2s). "
                "Điểm cuối = 55% rule-based + 45% judge."
            ),
        )
        if use_llm_judge:
            st.caption(
                "💡 **Hybrid Score** = 55% Rule-based + 45% LLM Judge  \n"
                "Kết quả sẽ sort theo Hybrid Score khi Judge bật."
            )

    with opt_col3:
        use_error_analysis = st.toggle(
            "🔍 Error Analysis (7 loại lỗi)",
            value=False,
            help=(
                "Phân tích 7 loại lỗi của test suite:\n"
                "E1 Bỏ sót yêu cầu · E2 Thiếu dữ liệu · "
                "E3 Expected result sai · E4 Suy diễn ngoài yêu cầu · "
                "E5 Thiếu TC âm tính/biên · E6 Trùng lặp · "
                "E7 Mâu thuẫn steps↔expected.\n"
                "Rule-based miễn phí. Bật LLM Judge để detect thêm E3/E4/E7 (semantic)."
            ),
        )
        if use_error_analysis:
            st.caption(
                "📏 **Rule-based**: E1, E2, E5, E6 (luôn chạy, miễn phí)\n"
                "🤖 **LLM Judge**: E1, E3, E4, E7 (cần bật LLM Judge)"
            )

    n_variants = len(selected_variant_ids)
    judge_extra = n_variants * 2 if use_llm_judge else 0
    error_extra = n_variants * 1 if (use_error_analysis and use_llm_judge) else 0
    if use_parallel and n_variants > 1:
        est_secs = (
            max(30, n_variants * 20 // max(max_workers, 1)) + judge_extra + error_extra
        )
        mode_label = f"parallel (max_workers={max_workers})"
    else:
        est_secs = n_variants * 20 + judge_extra + error_extra
        mode_label = "sequential"

    est_min = est_secs // 60
    est_sec_r = est_secs % 60
    extras = []
    if use_llm_judge:
        extras.append("Judge ~2s/variant")
    if use_error_analysis:
        extras.append("Error Analysis")
    extra_str = (" + " + " + ".join(extras)) if extras else ""
    st.caption(
        f"⏱️ Ước lượng: ~{est_secs}s ({est_min}m {est_sec_r}s) — "
        f"Mode: {mode_label}{extra_str}"
    )

    run_lab = st.button(
        "🚀 Chạy Prompt Lab",
        type="primary",
        use_container_width=True,
        key="btn_lab",
        disabled=(not lab_input.strip() or not selected_variant_ids),
    )

    if run_lab:
        if not lab_input.strip():
            st.warning("⚠️ Vui lòng nhập requirement.")
        elif not selected_variant_ids:
            st.warning("⚠️ Chọn ít nhất 1 variant.")
        else:
            progress_bar = st.progress(0, text="Đang khởi động...")
            log_container = st.container()

            def update_progress(vname, vstatus, done, total):
                pct = int(done / total * 100)
                icon = (
                    "⏳"
                    if vstatus == "running"
                    else ("✅" if vstatus == "done" else "❌")
                )
                progress_bar.progress(pct, text=f"{icon} {vname} ({done}/{total})")
                with log_container:
                    if vstatus == "running":
                        st.caption(f"🔄 Đang chạy: **{vname}**...")

            judge_spinner = " + LLM Judge" if use_llm_judge else ""
            parallel_spinner = " (parallel)" if use_parallel else ""
            with st.spinner(
                f"⏳ Đang chạy {len(selected_variant_ids)} variants"
                f"{parallel_spinner}{judge_spinner}..."
            ):
                lab_result = run_prompt_lab(
                    requirement=lab_input,
                    input_type=input_type,
                    language=language,
                    variant_ids=selected_variant_ids,
                    progress_callback=update_progress,
                    use_llm_judge=use_llm_judge,
                    parallel=use_parallel,
                    max_workers=max_workers,
                    weights=lab_weights,
                    use_error_analysis=use_error_analysis,
                )

            progress_bar.progress(100, text="✅ Hoàn thành!")
            st.session_state.lab_result = lab_result
            st.rerun()

    # ── DISPLAY LAB RESULTS ────────────────────────────────────────────────────
    lab_result = st.session_state.get("lab_result")

    if lab_result and lab_result.variants_run:
        st.divider()
        st.subheader("📊 Kết quả Prompt Lab — P1 → P5")

        meta_cols = st.columns(4)
        with meta_cols[0]:
            st.metric("Variants chạy", len(lab_result.variants_run))
        with meta_cols[1]:
            st.metric("Thành công", len(lab_result.successful_runs))
        with meta_cols[2]:
            delta = lab_result.get_score_delta()
            st.metric(
                "Score Delta (best−worst)",
                f"{delta:.1f}",
                help=(
                    "Khoảng cách điểm giữa variant tốt nhất và tệ nhất. "
                    "Delta lớn → mức độ cấu trúc prompt ảnh hưởng đáng kể."
                ),
            )
        with meta_cols[3]:
            judge_label = "✅ Bật" if lab_result.used_llm_judge else "⬜ Tắt"
            st.metric("LLM Judge", judge_label)

        successful = lab_result.successful_runs
        failed = [r for r in lab_result.variants_run if not r.success]

        if failed:
            with st.expander(f"⚠️ {len(failed)} variant(s) thất bại"):
                for r in failed:
                    st.error(f"**{r.variant_name}**: {r.error_message}")

        if not successful:
            st.error("Không có variant nào thành công.")
        else:
            # ── Download Excel ──
            excel_bytes = lab_to_excel(lab_result)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            sheet_count = (
                3
                + (1 if lab_result.used_llm_judge else 0)
                + (
                    1
                    if any(
                        r.evaluation and r.evaluation.error_report
                        for r in lab_result.successful_runs
                    )
                    else 0
                )
            )
            st.download_button(
                f"📥 Download Excel So Sánh ({sheet_count} sheets)",
                data=excel_bytes,
                file_name=f"prompt_lab_P1_P5_{ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            # ── Winner callout + Apply button ──
            best = lab_result.leaderboard[0]
            col_best, col_apply = st.columns([4, 2])
            with col_best:
                score_str = (
                    f"Hybrid {best.evaluation.hybrid_score:.1f}/100"
                    if best.evaluation.hybrid_score is not None
                    else f"Score {best.evaluation.overall_score:.1f}/100"
                )
                best_color = VARIANT_LEVEL_COLOR.get(best.variant_id, "#22c55e")
                st.markdown(
                    f"""<div style="background:{best_color}22;border-left:4px solid {best_color};
                    padding:10px 14px;border-radius:4px;">
                    🥇 <b>Best prompt: {best.variant_name}</b> — {score_str}  |
                    {best.evaluation.total_tc} TCs  |  Grade {best.evaluation.grade}
                    </div>""",
                    unsafe_allow_html=True,
                )
            with col_apply:
                is_active = st.session_state.active_variant_id == best.variant_id
                btn_label = (
                    f"✅ Đang dùng: {best.variant_name}"
                    if is_active
                    else f"🎯 Apply to Generator: {best.variant_name}"
                )
                if st.button(
                    btn_label,
                    type="primary" if not is_active else "secondary",
                    use_container_width=True,
                    key="btn_apply_best",
                    disabled=is_active,
                ):
                    st.session_state.active_variant_id = best.variant_id
                    st.session_state.active_variant_name = best.variant_name
                    st.success(
                        f"✅ Đã áp dụng **{best.variant_name}** cho Generator! "
                        "Chuyển sang tab 🧪 Generator để dùng."
                    )
                    st.rerun()

            if len(lab_result.leaderboard) > 1:
                worst = lab_result.leaderboard[-1]
                st.warning(
                    f"⚠️ **Worst prompt: {worst.variant_name}** — "
                    f"Score {worst.evaluation.overall_score:.1f}/100  |  "
                    f"{worst.evaluation.total_tc} TCs"
                )

            # ── LLM Judge detail ───────────────────────────────────────────
            if lab_result.used_llm_judge:
                st.subheader("🧠 LLM Judge – Semantic Scores")
                judge_rows = []
                for run in lab_result.leaderboard:
                    ev = run.evaluation
                    js = ev.llm_judge_score
                    if js and js.judge_available:
                        judge_rows.append(
                            {
                                "Variant": run.variant_name,
                                "Semantic Coverage": js.semantic_coverage,
                                "Step Clarity": js.step_clarity,
                                "Expected Result Quality": js.expected_result_quality,
                                "Test Data Realism": js.test_data_realism,
                                "Negative Case Quality": js.negative_case_quality,
                                "Composite": round(js.composite_score, 1),
                                "Verdict": js.verdict[:80],
                            }
                        )
                if judge_rows:
                    st.dataframe(
                        pd.DataFrame(judge_rows),
                        hide_index=True,
                        use_container_width=True,
                    )
                    st.caption(
                        "🔬 Judge dimensions: **Semantic Coverage** (30%) · "
                        "**Step Clarity** (25%) · **Expected Result Quality** (20%) · "
                        "**Test Data Realism** (15%) · **Negative Case Quality** (10%)"
                    )
                else:
                    st.info("Judge không available cho tất cả variants.")

            # ── Per-variant detail ─────────────────────────────────────────
            st.subheader("🔍 Chi tiết từng Variant")
            for run in lab_result.leaderboard:
                ev = run.evaluation
                grade_color = {
                    "A": "🟢",
                    "B": "🟡",
                    "C": "🟠",
                    "D": "🔴",
                    "F": "⛔",
                }.get(ev.grade, "⚪")
                is_curr = st.session_state.active_variant_id == run.variant_id
                vcolor = VARIANT_LEVEL_COLOR.get(run.variant_id, "#888")

                hybrid_str = (
                    f"  |  Hybrid {ev.hybrid_score:.1f}"
                    if ev.hybrid_score is not None
                    else ""
                )
                with st.expander(
                    f"{grade_color} **{run.variant_name}** — Rule {ev.overall_score:.1f}/100"
                    f"{hybrid_str}  |  Grade {ev.grade}  |  {ev.total_tc} TCs  |  "
                    f"{run.duration_seconds:.1f}s"
                    + ("  ·  🎯 *Active*" if is_curr else "")
                ):
                    st.markdown(f"*{run.variant_description}*")
                    st.caption(f"Tags: {', '.join(run.variant_tags)}")

                    cols3 = st.columns(3)
                    for i, d in enumerate(ev.dimensions):
                        with cols3[i % 3]:
                            color = (
                                "#22c55e"
                                if d.percentage >= 75
                                else "#f59e0b" if d.percentage >= 50 else "#ef4444"
                            )
                            # Lấy weight của chiều này
                            dim_key = next(
                                (k for k, v in DIMENSION_LABELS.items() if v == d.name),
                                None,
                            )
                            weight_pct = (
                                round(getattr(ev.weights_used, dim_key) * 100)
                                if dim_key
                                else 0
                            )
                            st.markdown(
                                f"""<div style="border:1px solid {color};border-radius:6px;
                                padding:8px;margin:4px;text-align:center;">
                                <b style="font-size:0.85em;">{d.name}</b><br>
                                <span style="font-size:1.3em;color:{color};font-weight:bold;">{d.percentage}%</span>
                                <br><small style="color:#888;">weight: {weight_pct}%</small>
                                <br><small style="color:#666;">{d.details[:55]}</small>
                                </div>""",
                                unsafe_allow_html=True,
                            )

                    js = ev.llm_judge_score
                    if js and js.judge_available:
                        st.divider()
                        st.markdown(
                            f"**🧠 LLM Judge Composite:** {js.composite_score:.1f}/100  "
                            f"→  *{js.verdict}*"
                        )

                    st.markdown(f"**💡 Khuyến nghị:** {ev.recommendation}")

                    col_s, col_w = st.columns(2)
                    with col_s:
                        if ev.strengths:
                            st.write("**✅ Điểm mạnh:**")
                            for s in ev.strengths:
                                st.write(f"  • {s}")
                    with col_w:
                        if ev.weaknesses:
                            st.write("**❌ Điểm yếu:**")
                            for w in ev.weaknesses:
                                st.write(f"  • {w}")

                    all_issues = []
                    for d in ev.dimensions:
                        all_issues.extend(d.issues)
                    if all_issues:
                        with st.expander(f"⚠️ {len(all_issues)} issue(s) chi tiết"):
                            for iss in all_issues:
                                st.caption(f"• {iss}")

                    with st.expander(
                        f"📋 Sample Test Cases ({min(5, len(ev.raw_tc_list))} đầu)"
                    ):
                        for tc in ev.raw_tc_list[:5]:
                            st.markdown(
                                f"**{tc.get('id')}** [{tc.get('coverage_type','?')}] "
                                f"[{tc.get('priority','?')}] — {tc.get('title','')}"
                            )
                            if tc.get("steps"):
                                for i, s in enumerate(tc["steps"][:3], 1):
                                    st.caption(f"  {i}. {s}")

                    # ── Error Analysis in per-variant detail ────────────────
                    if ev.error_report is not None:
                        er = ev.error_report
                        if er.total_errors > 0:
                            st.divider()
                            crit = er.critical_count
                            warn = er.warning_count
                            st.markdown(
                                f"**⚠️ Error Analysis:** {er.total_errors} lỗi — "
                                f"🔴 {crit} critical · 🟡 {warn} warning"
                            )
                            with st.expander("Xem chi tiết lỗi", expanded=False):
                                from core.error_analyzer import (
                                    render_error_report_streamlit,
                                )

                                render_error_report_streamlit(er)
                        else:
                            st.success("✅ Error Analysis: không phát hiện lỗi.")

                    if not is_curr:
                        if st.button(
                            f"🎯 Apply {run.variant_name} to Generator",
                            key=f"apply_detail_{run.variant_id}",
                            use_container_width=True,
                        ):
                            st.session_state.active_variant_id = run.variant_id
                            st.session_state.active_variant_name = run.variant_name
                            st.rerun()
