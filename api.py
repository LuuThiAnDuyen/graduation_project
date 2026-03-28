# api.py

from fastapi import FastAPI
from pydantic import BaseModel
from core.testcase_generator import generate_full_testcase
from fastapi import HTTPException

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
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool


@app.post("/generate")
async def generate(req: GenerateRequest):
    try:
        print(">>> START GENERATE")

        result = await run_in_threadpool(
            generate_full_testcase, req.text, req.input_type, req.language
        )

        print(">>> DONE GENERATE")
        return result

    except Exception as e:
        print(">>> ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))


# ===============================
# GET API (DEMO)
# ===============================
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool


@app.get("/generate")
async def generate_get(
    text: str,
    input_type: str = "User Story",
    language: str = "English",
):
    try:
        print(">>> START GENERATE (GET)")

        result = await run_in_threadpool(
            generate_full_testcase, text, input_type, language
        )

        print(">>> DONE GENERATE (GET)")
        return result

    except Exception as e:
        print(">>> ERROR (GET):", e)
        raise HTTPException(status_code=500, detail=str(e))
