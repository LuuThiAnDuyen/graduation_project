import os
import sys
import streamlit as st
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.gherkin_generator import generate_gherkin

st.set_page_config(page_title="LLM Test Case Generator", layout="wide")

st.title("LLM-based Test Case Generator")
st.write("Sinh Gherkin Test Case tự động từ User Story")

user_story = st.text_area(
    "Nhập User Story",
    height=150,
    placeholder="Ví dụ: User can login with valid username and password",
)

if st.button("Generate Test Cases"):
    with st.spinner("Đang gọi LLM..."):
        result = generate_gherkin(user_story)

    st.subheader("Generated Gherkin")
    st.code(result, language="gherkin")

    st.download_button(
        label="Download .feature file",
        data=result,
        file_name="generated_test_cases.feature",
        mime="text/plain",
    )
