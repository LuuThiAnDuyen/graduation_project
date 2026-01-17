import os
import sys
import streamlit as st

# Add root project path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FEATURE_DIR = os.path.join(PROJECT_ROOT, "features")
os.makedirs(FEATURE_DIR, exist_ok=True)
from core.gherkin_generator import generate_gherkin

st.set_page_config(page_title="LLM Test Case Generator", layout="wide")

st.title("LLM-based Test Case Generator")
st.write("Sinh Gherkin Test Case tự động từ User Story bằng LLM")

# -------- Session State --------
if "gherkin_preview" not in st.session_state:
    st.session_state.gherkin_preview = None

# -------- Input --------
user_story = st.text_area(
    "Nhập User Story",
    height=150,
    placeholder="Ví dụ: User can login with valid username and password",
)

# -------- Generate Button --------
if st.button("Generate Test Cases"):
    if not user_story.strip():
        st.warning("Vui lòng nhập User Story.")
    else:
        with st.spinner("Đang gọi LLM và sinh Gherkin..."):
            gherkin_text = generate_gherkin(user_story)
            st.session_state.gherkin_preview = gherkin_text

# -------- Preview --------
if st.session_state.gherkin_preview:
    st.subheader("Preview Gherkin Feature File")
    st.code(st.session_state.gherkin_preview, language="gherkin")

    # -------- Save Button --------
    if st.button("Save to Project"):
        feature_dir = "features"
        os.makedirs(feature_dir, exist_ok=True)

        feature_path = os.path.join(feature_dir, "generated.feature")

        with open(feature_path, "w", encoding="utf-8") as f:
            f.write(st.session_state.gherkin_preview)

        st.success(f"Đã lưu file feature tại: {feature_path}")
