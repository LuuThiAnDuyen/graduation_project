from fastapi import FastAPI, Query
from core.llm_client import generate_test_artifacts

app = FastAPI()


@app.get("/generate")
def generate(
    text: str = Query(..., description="User Story / Requirement"),
    input_type: str = Query(
        ..., description="Type of input (User Story / Requirement / Test Scenario)"
    ),
    language: str = Query(..., description="Output language (English / Vietnamese)"),
):
    result = generate_test_artifacts(text, input_type, language)
    return result


@app.get("/")
def root():
    return {"status": "API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
