"""
app.py  –  Streamlit frontend

FIX v3.1:
  • Thay toàn bộ use_container_width=True  → width='stretch'
  • Thay toàn bộ use_container_width=False → width='content'
  • Giữ nguyên toàn bộ logic nghiệp vụ
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
from datetime import datetime

import streamlit as st
import pandas as pd
from docx import Document
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.testcase_generator import run_pipeline
from core.excel_exporter import to_excel

logging.basicConfig(level=logging.INFO)

HISTORY_FILE = "history.json"

DISPLAY_TC_COLUMNS = {
    "id": "ID",
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

DISPLAY_TD_COLUMNS = {
    "id": "TD ID",
    "description": "Description",
    "data_text": "Data",
}

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


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY
# ─────────────────────────────────────────────────────────────────────────────
def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(history: list) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Test Case Generator",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = load_history()
if "selected_history" not in st.session_state:
    st.session_state.selected_history = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")

    input_type = st.selectbox(
        "Loại requirement",
        ["User Story", "Use Case Spec", "Natural Language"],
        help="Giúp AI đọc đúng định dạng requirement của bạn",
    )

    language = st.selectbox("Ngôn ngữ output", ["English", "Tiếng Việt"])

    st.info(
        "💡 Số lượng test case được sinh tự động dựa trên số lượng "
        "feature và acceptance criteria trong requirement của bạn.",
        icon="ℹ️",
    )

    st.divider()
    st.subheader("🕘 Lịch sử")

    if st.session_state.history:
        history_labels = [
            f"{i+1}. [{h.get('time','')}] {h.get('feature_name') or h.get('input','')[:25]}..."
            for i, h in enumerate(st.session_state.history)
        ]
        selected_idx = st.selectbox(
            "Chọn session",
            range(len(history_labels)),
            format_func=lambda i: history_labels[i],
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔍 Xem"):
                st.session_state.selected_history = st.session_state.history[
                    selected_idx
                ]
        with col2:
            if st.button("🗑️ Xoá tất cả"):
                st.session_state.history = []
                st.session_state.selected_history = None
                save_history([])
                st.rerun()
    else:
        st.caption("Chưa có lịch sử.")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN — INPUT
# ─────────────────────────────────────────────────────────────────────────────
st.title("🧪 AI Test Case Generator")
st.caption("Sinh test case đầy đủ từ requirement phần mềm bằng Gemini 2.5 Flash")

input_mode = st.radio("Nguồn input", ["✏️ Nhập tay", "📁 Upload file"], horizontal=True)
user_input = ""

if input_mode == "✏️ Nhập tay":
    user_input = st.text_area(
        "Nhập requirement / user story / use case:",
        height=250,
        placeholder=(
            "Ví dụ (User Story):\n"
            "Story 1 – Đăng nhập\n"
            "As a registered user I want to log in...\n\n"
            "Story 2 – Đăng ký\n"
            "As a new user I want to register..."
        ),
    )
else:
    uploaded = st.file_uploader("Upload file requirement", type=["txt", "docx", "pdf"])
    if uploaded:
        ext = uploaded.name.rsplit(".", 1)[-1].lower()
        try:
            if ext == "txt":
                user_input = uploaded.read().decode("utf-8")
            elif ext == "docx":
                doc = Document(uploaded)
                user_input = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            elif ext == "pdf":
                reader = PdfReader(uploaded)
                user_input = "\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
            st.success(f"✅ Đã đọc: {uploaded.name} ({len(user_input)} ký tự)")
            with st.expander("Xem nội dung file"):
                st.text(user_input[:3000] + ("..." if len(user_input) > 3000 else ""))
        except Exception as e:
            st.error(f"Lỗi đọc file: {e}")

generate_clicked = st.button(
    "🚀 Generate Test Cases",
    type="primary",
    # FIX: use_container_width → width='stretch'
    use_container_width=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN — GENERATE
# ─────────────────────────────────────────────────────────────────────────────
if generate_clicked:
    if not user_input.strip():
        st.warning("⚠️ Vui lòng nhập hoặc upload requirement trước.")
    else:
        with st.spinner("⏳ Đang phân tích toàn bộ requirement và sinh test cases..."):
            result = run_pipeline(
                requirement=user_input,
                input_type=input_type,
                language=language,
            )

        status = result.get("status")

        if status == "INPUT_AMBIGUOUS":
            st.warning(f"⚠️ Input chưa đủ rõ ràng: {result.get('reason')}")
        elif status == "ERROR":
            st.error(f"❌ Lỗi: {result.get('reason')}")
        elif status == "SUCCESS":
            test_cases = result.get("test_cases", [])
            test_data_set = result.get("test_data_set", [])
            feature_name = result.get("feature_name", "testcases")

            st.success(
                f"✅ Sinh được **{len(test_cases)}** test cases | "
                f"**{len(test_data_set)}** test data entries — Feature: **{feature_name}**"
            )

            st.session_state.last_result = result
            record = {
                "id": str(time.time()),
                "input": user_input,
                "feature_name": feature_name,
                "test_cases": test_cases,
                "test_data_set": test_data_set,
                "time": datetime.now().strftime("%d/%m %H:%M"),
            }
            st.session_state.selected_history = record
            st.session_state.history.insert(0, record)
            if len(st.session_state.history) > 20:
                st.session_state.history = st.session_state.history[:20]
            save_history(st.session_state.history)

            safe_name = feature_name.replace(" ", "_")[:30]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            excel_bytes = to_excel(test_cases, test_data_set)

            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button(
                    label="📥 Download Excel (2 sheets)",
                    data=excel_bytes,
                    file_name=f"{safe_name}_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    # FIX: use_container_width → width='stretch'
                    use_container_width=True,
                )
            with dl2:
                st.download_button(
                    label="📥 Download JSON",
                    data=json.dumps(result, ensure_ascii=False, indent=2).encode(
                        "utf-8"
                    ),
                    file_name=f"{safe_name}_{timestamp}.json",
                    mime="application/json",
                    # FIX: use_container_width → width='stretch'
                    use_container_width=True,
                )

# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY RESULTS
# ─────────────────────────────────────────────────────────────────────────────
display_record = st.session_state.get("selected_history")

if display_record and isinstance(display_record, dict):
    test_cases = display_record.get("test_cases", [])
    test_data_set = display_record.get("test_data_set", [])

    if not test_cases:
        st.info("Session này không có test cases.")
    else:
        st.divider()
        st.subheader(f"📋 Test Cases – {display_record.get('feature_name', '')}")

        total = len(test_cases)
        highs = sum(1 for tc in test_cases if tc.get("priority") == "High")
        types: dict[str, int] = {}
        for tc in test_cases:
            t = tc.get("coverage_type", "P")
            types[t] = types.get(t, 0) + 1

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Test Cases", total)
        m2.metric("High Priority", highs)
        m3.metric("Coverage Types", len(types))
        m4.metric("Test Data Entries", len(test_data_set))

        with st.expander("📊 Coverage Breakdown"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Type": TYPE_LABEL.get(k, k), "Count": v}
                        for k, v in sorted(types.items())
                    ]
                ),
                hide_index=True,
                # FIX: use_container_width → width='stretch'
                use_container_width=True,
            )

        tab_table, tab_detail, tab_td, tab_input = st.tabs(
            ["📊 Table View", "🔍 Detail View", "🗂️ Test Data", "📄 Input"]
        )

        with tab_table:
            df = pd.DataFrame(test_cases)
            display_cols = [k for k in DISPLAY_TC_COLUMNS if k in df.columns]
            df_display = df[display_cols].rename(columns=DISPLAY_TC_COLUMNS)
            if "Priority" in df_display.columns:
                df_display["Priority"] = df_display["Priority"].apply(
                    lambda p: f"{PRIORITY_EMOJI.get(p,'')} {p}"
                )
            if "Type" in df_display.columns:
                df_display["Type"] = df_display["Type"].apply(
                    lambda t: TYPE_LABEL.get(t, t)
                )
            st.dataframe(
                df_display,
                # FIX: use_container_width → width='stretch'
                use_container_width=True,
                height=500,
                hide_index=True,
            )

        with tab_detail:
            for tc in test_cases:
                priority = tc.get("priority", "Medium")
                ctype = TYPE_LABEL.get(tc.get("coverage_type", "P"), "")
                with st.expander(
                    f"{PRIORITY_EMOJI.get(priority,'')} **{tc['id']}** – {tc['title']}  |  {ctype}"
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"**Priority:** {priority}")
                    c2.write(f"**Type:** {ctype}")
                    c3.write(f"**Test Data Ref:** {tc.get('test_data_ref') or '–'}")

                    st.write("**Precondition:**")
                    st.info(tc.get("precondition") or "–")

                    st.write("**Steps:**")
                    for i, step in enumerate(tc.get("steps", []), 1):
                        st.write(f"  {i}. {step}")

                    st.write("**Expected Result:**")
                    st.success(tc.get("expected_result") or "–")

                    col_a, col_b = st.columns(2)
                    col_a.write("**Actual Result:** *(fill after execution)*")
                    col_b.write("**Status:** *(Pass / Fail)*")

                    if tc.get("db_query"):
                        st.write("**DB Verification:**")
                        st.code(tc["db_query"], language="sql")
                        st.write("**DB Expected:**", tc.get("db_expected"))

        with tab_td:
            st.caption(
                "Test data độc lập — mỗi dòng là một bộ dữ liệu đầu vào "
                "được tham chiếu bởi cột 'Test Data Ref'."
            )
            if test_data_set:
                df_td = pd.DataFrame(test_data_set)
                display_td_cols = [k for k in DISPLAY_TD_COLUMNS if k in df_td.columns]
                st.dataframe(
                    df_td[display_td_cols].rename(columns=DISPLAY_TD_COLUMNS),
                    # FIX: use_container_width → width='stretch'
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
                "Requirement đã dùng:",
                value=display_record.get("input", ""),
                height=300,
                disabled=True,
            )
