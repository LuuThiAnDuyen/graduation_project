import streamlit as st
import pandas as pd
import json
import os
import sys
import time
from datetime import datetime
from io import BytesIO
from openpyxl import Workbook
from docx import Document
from pypdf import PdfReader
from google import genai
from dotenv import load_dotenv
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

load_dotenv()

# ================= FIX PATH =================
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ================= IMPORT CORE =================
from core.testcase_generator import run_pipeline

# ================= HISTORY =================
HISTORY_FILE = "history.json"


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ================= EXCEL EXPORT =================
def to_excel(test_cases):
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Cases"

    headers = [
        "ID",
        "Title",
        "Precondition",
        "Steps",
        "Expected Result",
        "Priority",
        "Type",
        "DB Query",
        "DB Expected",
    ]

    ws.append(headers)

    # ===== STYLE =====
    header_fill = PatternFill(
        start_color="D9EAF7", end_color="D9EAF7", fill_type="solid"
    )  # xanh pastel
    header_font = Font(bold=True)
    align = Alignment(vertical="top", wrap_text=True)

    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # ===== HEADER STYLE =====
    for col_num, _ in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align
        cell.border = thin_border

    # ===== DATA =====
    for row_idx, tc in enumerate(test_cases, start=2):
        steps = "\n".join(tc.get("steps", []))

        row_data = [
            tc.get("id"),
            tc.get("title"),
            tc.get("precondition"),
            steps,
            tc.get("expected"),
            tc.get("priority"),
            tc.get("type"),
            tc.get("db_check"),
            tc.get("db_expected"),
        ]

        ws.append(row_data)

        # Apply style từng cell
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.alignment = align
            cell.border = thin_border

    # ===== AUTO WIDTH =====
    for col in ws.columns:
        max_length = 0
        col_letter = col[0].column_letter

        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass

        ws.column_dimensions[col_letter].width = min(max_length + 5, 50)

    output = BytesIO()
    wb.save(output)
    return output.getvalue()

# ================= UI CONFIG =================
st.set_page_config(page_title="AI Test Case Generator", layout="wide")

st.title("🚀 AI Test Case Generator")

# ================= SESSION =================
if "history" not in st.session_state:
    st.session_state.history = load_history()

if "selected_history" not in st.session_state:
    st.session_state.selected_history = None


# ================= SIDEBAR =================
st.sidebar.header("⚙️ Config")

input_type = st.sidebar.selectbox(
    "Loại input", ["User Story", "Use Case Spec", "Natural Language"]
)

language = st.sidebar.selectbox("Ngôn ngữ", ["Tiếng Việt", "English"])

option = st.sidebar.radio("Input", ["Text", "Upload File"])


# ================= HISTORY =================
st.sidebar.subheader("🕘 History")

if st.session_state.history:
    idx = st.sidebar.selectbox(
        "Chọn lịch sử",
        range(len(st.session_state.history)),
        format_func=lambda i: f"{i+1}. {st.session_state.history[i]['time']} - {st.session_state.history[i]['input'][:30]}...",
    )

    if st.sidebar.button("🔍 Xem lại"):
        st.session_state.selected_history = st.session_state.history[idx]

    if st.sidebar.button("🗑️ Xoá lịch sử"):
        st.session_state.history = []
        save_history([])
        st.sidebar.success("Đã xoá!")


# ================= INPUT =================
user_input = ""

if option == "Text":
    user_input = st.text_area("Requirement", height=250)

else:
    file = st.file_uploader("Upload file", type=["txt", "docx", "pdf"])

    if file:
        ext = file.name.split(".")[-1]

        if ext == "txt":
            user_input = file.read().decode("utf-8")

        elif ext == "docx":
            user_input = "\n".join([p.text for p in Document(file).paragraphs])

        elif ext == "pdf":
            user_input = "\n".join(
                [p.extract_text() or "" for p in PdfReader(file).pages]
            )


# ================= EXECUTE =================
if st.button("🔥 Generate Now"):

    if not user_input.strip():
        st.warning("❗ Không được bỏ trống input")
        st.stop()

    try:
        with st.spinner("Đang xử lý..."):
            # ✅ GỌI PIPELINE (ĐÃ FIX)
            result = run_pipeline(user_input)

            if not result:
                st.error("❌ Không nhận được kết quả từ LLM")
                st.stop()

            status = result.get("status")

            # ❌ INPUT KHÔNG ĐỦ RÕ
            if status == "INPUT_AMBIGUOUS":
                st.error("❗ Input chưa đủ rõ")

            # ❌ ERROR
            elif status == "ERROR":
                st.error("❗ Có lỗi xảy ra khi xử lý")

            # ✅ SUCCESS
            elif status == "SUCCESS":
                st.success("✅ Done!")

                record = {
                    "id": str(time.time()),
                    "input": user_input,
                    "test_cases": result.get("test_cases", []),
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
                st.session_state.selected_history = record
                st.session_state.history.append(record)
                save_history(st.session_state.history)

                excel = to_excel(result.get("test_cases", []))
                # Lấy title test case đầu tiên làm tên feature
                feature_name = "testcase"

                if result.get("test_cases"):
                    feature_name = result["test_cases"][0].get("title", "testcase")

                    # Clean tên file
                    feature_name = feature_name.replace(" ", "_")[:30]

                    # Ngày giờ
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

                    file_name = f"{feature_name}_{timestamp}.xlsx"
                st.download_button(
                    "📥 Download Excel",
                    excel,
                    file_name,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    except Exception as e:
        # ❗ KHÔNG show lỗi chi tiết ra UI
        st.error("❗ Lỗi xử lý. Vui lòng kiểm tra lại input.")
        print(f"DEBUG ERROR: {e}")


# ================= DISPLAY =================
if st.session_state.history:
    res = st.session_state.get("selected_history")

    if not isinstance(res, dict):
        st.info("Please select a history item to view.")
    else:
        t1, t2 = st.tabs(["Test Cases", "Input"])

        with t1:
            if "test_cases" in res and res["test_cases"]:
                df = pd.DataFrame(res["test_cases"])
                st.dataframe(df)
            else:
                st.warning("No test cases available")

        with t2:
            st.write(res.get("input", "No input data"))
