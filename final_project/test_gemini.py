import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Khởi tạo client với API Key
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

try:
    # Thử dùng tên model đầy đủ có tiền tố 'models/'
    response = client.models.generate_content(
        #model="gemini-3-flash-preview",
        model="gemini-flash-latest",
        contents= """
You are a senior QA engineer.
From the following user story, generate Gherkin scenarios
including positive, negative, and boundary cases.

User Story:
User can login with valid username and password
""",
    )
    print(f"Trả lời: {response.text}")

except Exception as e:
    print(f"Vẫn còn lỗi: {e}")
