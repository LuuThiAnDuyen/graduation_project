# core/llm_client.py

import os
from dotenv import load_dotenv
import google.generativeai as genai
from google import genai

load_dotenv()


def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY in .env")

    return genai.Client(api_key=api_key)
