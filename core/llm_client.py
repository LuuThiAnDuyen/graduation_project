"""
core/llm_client.py
------------------
Single source of truth cho mọi thứ liên quan đến Gemini API.

FIX v3.1:
  • Gemini 2.5 Flash trả về thinking/reasoning blocks TRƯỚC JSON
    → _extract_json phải bỏ qua phần thinking đó
  • Thêm strategy: tìm JSON bắt đầu từ ký tự '{' / '[' CUỐI CÙNG trong response
    (thinking thường đứng trước, JSON thật đứng sau)
  • Thêm GenerationConfig: response_mime_type="application/json" để force JSON output
  • Giữ toàn bộ fallback chain cũ phòng model cũ hơn
"""

import os
import time
import json
import re
import logging
from google import genai
from google.genai import types
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MODEL_NAME = "models/gemini-2.5-flash"
MAX_RETRIES = 3
BASE_DELAY = 2  # giây – sẽ nhân đôi theo exponential backoff

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CLIENT
# ─────────────────────────────────────────────
def get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY chưa được set. Kiểm tra file .env tại: " + BASE_DIR
        )
    return genai.Client(api_key=api_key)


# ─────────────────────────────────────────────
# JSON PARSER  (robust – handle Gemini 2.5 Flash thinking output)
# ─────────────────────────────────────────────
def _strip_thinking(text: str) -> str:
    """
    Gemini 2.5 Flash (extended thinking) đôi khi trả về:
      <thinking>...</thinking>
      { ...actual JSON... }
    hoặc chỉ một khối text reasoning rồi mới đến JSON.
    Strip toàn bộ phần trước JSON thật.
    """
    # Strip XML-style thinking tags
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _try_parse(candidate: str) -> dict | list | None:
    """Parse một string JSON, fix trailing commas nếu cần."""
    candidate = candidate.strip()
    if not candidate:
        return None
    # Fix trailing commas before } or ] — LLM hay sinh ra lỗi này
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _extract_json(raw: str) -> dict | list | None:
    """
    Cố gắng parse JSON từ raw text của LLM.

    Thứ tự ưu tiên:
      1. Strip thinking tags rồi parse thẳng
      2. Bóc markdown ```json ... ```
      3. Tìm JSON object/array bắt đầu từ VỊ TRÍ CUỐI CÙNG của '{' hoặc '['
         (JSON thật thường đứng sau phần reasoning)
      4. Greedy regex tìm object/array DÀI NHẤT
      5. Tìm từ vị trí ĐẦUTIÊN của '{' / '[' (fallback)
    """
    if not raw:
        return None

    # Step 1: strip thinking, parse thẳng
    text = _strip_thinking(raw)
    result = _try_parse(text)
    if result is not None:
        return result

    # Step 2: markdown fence ```json ... ``` hoặc ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        result = _try_parse(fence_match.group(1))
        if result is not None:
            return result

    # Step 3: Tìm block JSON từ vị trí { / [ cuối cùng trở đi
    # Gemini 2.5 Flash thinking mode: reasoning ở đầu, JSON ở cuối
    for open_char, close_char in [("{", "}"), ("[", "]")]:
        last_pos = text.rfind(open_char)
        if last_pos != -1:
            candidate = text[last_pos:]
            # Tìm close tương ứng (cân bằng ngoặc)
            balanced = _extract_balanced(candidate, open_char, close_char)
            if balanced:
                result = _try_parse(balanced)
                if result is not None:
                    return result

    # Step 4: Greedy regex – tìm object/array DÀI NHẤT
    for pattern in (r"(\{[\s\S]*\})", r"(\[[\s\S]*\])"):
        match = re.search(pattern, text)
        if match:
            result = _try_parse(match.group(1))
            if result is not None:
                return result

    # Step 5: Tìm từ vị trí ĐẦU TIÊN của { hoặc [
    for open_char, close_char in [("{", "}"), ("[", "]")]:
        first_pos = text.find(open_char)
        if first_pos != -1:
            candidate = text[first_pos:]
            balanced = _extract_balanced(candidate, open_char, close_char)
            if balanced:
                result = _try_parse(balanced)
                if result is not None:
                    return result

    logger.warning(
        "_extract_json: không parse được JSON từ response (len=%d)", len(raw)
    )
    return None


def _extract_balanced(text: str, open_char: str, close_char: str) -> str | None:
    """
    Trích chuỗi con cân bằng ngoặc bắt đầu từ open_char đầu tiên.
    Xử lý đúng string literals để không bị lừa bởi ngoặc trong string.
    """
    depth = 0
    in_string = False
    escape_next = False
    start = None

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == open_char:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : i + 1]

    return None


# ─────────────────────────────────────────────
# GENERIC CALL  (dùng ở mọi nơi trong project)
# ─────────────────────────────────────────────
def call_llm(prompt: str) -> dict | list | None:
    """
    Gọi Gemini, retry với exponential backoff.
    Luôn trả về Python dict/list hoặc None khi thất bại.

    Dùng response_mime_type="application/json" để yêu cầu model
    trả về JSON thuần — giảm đáng kể lỗi parse.
    """
    client = get_client()

    # Config yêu cầu JSON output — hỗ trợ từ Gemini 1.5+
    generation_config = types.GenerateContentConfig(
        response_mime_type="application/json",
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=generation_config,
            )
            raw = response.text or ""

            if not raw.strip():
                logger.warning(f"Attempt {attempt}: LLM trả về empty response.")
                continue

            parsed = _extract_json(raw)
            if parsed is not None:
                logger.info(
                    f"Attempt {attempt}: parse JSON thành công (len={len(raw)})."
                )
                return parsed

            logger.warning(
                f"Attempt {attempt}: LLM trả text nhưng không parse được JSON "
                f"(preview: {raw[:200]!r})"
            )

        except Exception as exc:
            delay = BASE_DELAY * (2 ** (attempt - 1))
            logger.error(
                f"LLM error (attempt {attempt}/{MAX_RETRIES}): {exc} – retry sau {delay}s"
            )
            if attempt < MAX_RETRIES:
                time.sleep(delay)

    return None