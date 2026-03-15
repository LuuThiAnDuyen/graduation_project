import streamlit as st
from docx import Document
from pypdf import PdfReader
from core.gherkin_generator import generate_gherkin

st.set_page_config(page_title="User Story → Gherkin Generator")

st.title("User Story → Gherkin Generator")

# Session history
if "history" not in st.session_state:
    st.session_state.history = []

option = st.radio(
    "Chọn cách nhập User Story:", ["Nhập trực tiếp", "Upload file (.txt/.docx/.pdf)"]
)

user_story_text = ""

# ===============================
# OPTION 1 – NHẬP TRỰC TIẾP
# ===============================
if option == "Nhập trực tiếp":
    user_story_text = st.text_area("Nhập User Story", height=300)

# ===============================
# OPTION 2 – UPLOAD FILE
# ===============================
else:
    uploaded_file = st.file_uploader("Upload file", type=["txt", "docx", "pdf"])

    if uploaded_file:
        file_type = uploaded_file.name.split(".")[-1].lower()

        try:
            if file_type == "txt":
                user_story_text = uploaded_file.read().decode("utf-8")

            elif file_type == "docx":
                doc = Document(uploaded_file)
                user_story_text = "\n".join([p.text for p in doc.paragraphs])

            elif file_type == "pdf":
                reader = PdfReader(uploaded_file)
                user_story_text = "\n".join(
                    [page.extract_text() or "" for page in reader.pages]
                )

            st.subheader("Nội dung đọc được:")
            st.text_area(
                "User Story Input",
                user_story_text,
                height=300,
                label_visibility="collapsed",
            )

        except Exception as e:
            st.error(f"Lỗi đọc file: {e}")

# ===============================
# GENERATE BUTTON
# ===============================
if st.button("Generate Gherkin"):

    if not user_story_text.strip():
        st.warning("Vui lòng nhập hoặc upload User Story.")
    else:
        with st.spinner("Đang generate..."):
            result = generate_gherkin(user_story_text)

        st.subheader("Kết quả:")
        st.code(result, language="gherkin")

        # Lưu vào history
        st.session_state.history.append(
            {"input": user_story_text[:300], "output": result}
        )

# ===============================
# HISTORY
# ===============================
if st.session_state.history:
    st.divider()
    st.subheader("Lịch sử generate")

    for idx, item in enumerate(reversed(st.session_state.history)):
        with st.expander(f"Result {idx+1}"):
            st.write("Input preview:")
            st.text(item["input"])
            st.write("Output:")
            st.code(item["output"], language="gherkin")
