# api.py

from fastapi import FastAPI
from pydantic import BaseModel
from core.testcase_generator import generate_full_testcase
import httpx

app = FastAPI(title="AI TestCase Generator API")


# ===============================
# REQUEST MODEL
# ===============================
class GenerateRequest(BaseModel):
    text: str
    input_type: str = "User Story"
    language: str = "English"


# ===============================
# HEALTH CHECK
# ===============================
@app.get("/")
def root():
    return {"message": "API is running"}


# ===============================
# POST API (MAIN)
# ===============================
@app.post("/generate")
def generate(req: GenerateRequest):
    try:
        result = generate_full_testcase(req.text, req.input_type, req.language)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===============================
# GET API (DEMO)
# ===============================
@app.get("/generate")
def generate_get(
    text: str,
    input_type: str = "User Story",
    language: str = "English",
):
    try:
        return generate_full_testcase(text, input_type, language)
    except Exception as e:
        return {"status": "error", "message": str(e)}
