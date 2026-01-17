import os
from dotenv import load_dotenv
from google import genai

load_dotenv()


def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Chưa cấu hình GEMINI_API_KEY trong .env")

    return genai.Client(api_key=api_key)
