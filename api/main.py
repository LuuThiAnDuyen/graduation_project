"""
api/main.py  –  FastAPI backend
--------------------------------
Thay đổi so với v1:
  • GenerateResponse bổ sung test_data_set
  • Endpoint POST /export/excel  trả file .xlsx gồm 2 sheet:
      Sheet 1 "Test Cases"   – toàn bộ test cases
      Sheet 2 "Test Data"    – toàn bộ test data entries
  • Endpoint POST /export/json   trả raw JSON (tiện tích hợp CI/CD)
  • Health endpoint trả thêm version metadata
"""

from __future__ import annotations

from io import BytesIO
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.testcase_generator import run_pipeline
from core.excel_exporter import to_excel  # tách logic export ra module riêng

app = FastAPI(
    title="AI Test Case Generator API",
    description="Tự động sinh test case và test data từ requirement phần mềm bằng Gemini LLM",
    version="3.0.0",
)


# ─────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────


class GenerateRequest(BaseModel):
    requirement: str = Field(
        ...,
        min_length=10,
        description="Nội dung requirement (User Story / Use Case Spec / Natural Language)",
    )
    input_type: str = Field(
        "User Story",
        description="User Story | Use Case Spec | Natural Language",
    )
    language: str = Field(
        "English",
        description="Ngôn ngữ output: English | Tiếng Việt",
    )


class TestDataEntry(BaseModel):
    id: str
    description: str
    data: dict
    data_text: str


class TestCase(BaseModel):
    id: str
    title: str
    coverage_type: str
    priority: str
    precondition: str
    steps: list[str]
    steps_text: str
    expected_result: str
    actual_result: str  # luôn "" từ pipeline
    status_result: str  # luôn "" từ pipeline
    db_query: str
    db_expected: str
    test_data_ref: str


class GenerateResponse(BaseModel):
    status: str
    reason: str
    feature_name: str
    test_cases: list[TestCase]
    test_data_set: list[TestDataEntry]


# ─────────────────────────────────────────────
# ROUTES — HEALTH
# ─────────────────────────────────────────────


@app.get("/", tags=["Health"])
def root():
    return {
        "status": "AI Test Case Generator API is running",
        "version": "3.0.0",
        "endpoints": [
            "POST /generate          – sinh test cases (JSON response)",
            "POST /export/excel      – sinh test cases + download .xlsx",
            "POST /export/json       – sinh test cases + download .json",
        ],
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}


# ─────────────────────────────────────────────
# ROUTES — GENERATE (JSON)
# ─────────────────────────────────────────────


@app.post("/generate", response_model=GenerateResponse, tags=["Generate"])
def generate(body: GenerateRequest):
    """
    Nhận requirement → gọi LLM → trả JSON gồm:
    - `test_cases`    : danh sách test case đầy đủ
    - `test_data_set` : danh sách test data entry độc lập
    """
    try:
        result = run_pipeline(
            requirement=body.requirement,
            input_type=body.input_type,
            language=body.language,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────
# ROUTES — EXPORT EXCEL
# ─────────────────────────────────────────────


@app.post("/export/excel", tags=["Export"])
def export_excel(body: GenerateRequest):
    """
    Chạy pipeline rồi trả về file .xlsx với 2 sheet:
    - Sheet "Test Cases"  : id, title, type, priority, precondition, steps,
                            expected_result, actual_result, status_result, db_query, db_expected
    - Sheet "Test Data"   : id, description, data (flattened key:value)
    """
    try:
        result = run_pipeline(
            requirement=body.requirement,
            input_type=body.input_type,
            language=body.language,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if result["status"] != "SUCCESS":
        raise HTTPException(
            status_code=422,
            detail={"status": result["status"], "reason": result["reason"]},
        )

    excel_bytes = to_excel(
        test_cases=result["test_cases"],
        test_data_set=result["test_data_set"],
    )

    safe_name = result["feature_name"].replace(" ", "_")[:30] or "testcases"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{safe_name}_{timestamp}.xlsx"

    return StreamingResponse(
        BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────
# ROUTES — EXPORT JSON
# ─────────────────────────────────────────────


@app.post("/export/json", tags=["Export"])
def export_json(body: GenerateRequest):
    """
    Chạy pipeline rồi trả về file .json thuần — tiện tích hợp CI/CD pipeline.
    """
    import json as _json

    try:
        result = run_pipeline(
            requirement=body.requirement,
            input_type=body.input_type,
            language=body.language,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if result["status"] != "SUCCESS":
        raise HTTPException(
            status_code=422,
            detail={"status": result["status"], "reason": result["reason"]},
        )

    safe_name = result["feature_name"].replace(" ", "_")[:30] or "testcases"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{safe_name}_{timestamp}.json"

    json_bytes = _json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")

    return StreamingResponse(
        BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
