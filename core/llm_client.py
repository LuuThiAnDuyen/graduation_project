"""
core/llm_client.py
------------------
Single source of truth cho mọi thứ liên quan đến Gemini API.
"""

import os, time, json, re, logging
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MODEL_NAME = "models/gemini-2.5-flash"
MAX_RETRIES = 5
BASE_DELAY = 2

logger = logging.getLogger(__name__)


def get_client():
    try:
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY chưa được set. Kiểm tra file .env tại: " + BASE_DIR
            )
        return genai.Client(api_key=api_key)
    except ImportError:
        raise ImportError("Cần cài: pip install google-genai")


def _strip_thinking(text: str) -> str:
    return re.sub(
        r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE
    ).strip()


def _try_parse(candidate: str):
    candidate = candidate.strip()
    if not candidate:
        return None
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _extract_balanced(text: str, open_char: str, close_char: str):
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


def _extract_json(raw: str):
    if not raw:
        return None
    text = _strip_thinking(raw)
    result = _try_parse(text)
    if result is not None:
        return result
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        result = _try_parse(fence.group(1))
        if result is not None:
            return result
    for oc, cc in [("{", "}"), ("[", "]")]:
        last = text.rfind(oc)
        if last != -1:
            balanced = _extract_balanced(text[last:], oc, cc)
            if balanced:
                result = _try_parse(balanced)
                if result is not None:
                    return result
    for pattern in (r"(\{[\s\S]*\})", r"(\[[\s\S]*\])"):
        m = re.search(pattern, text)
        if m:
            result = _try_parse(m.group(1))
            if result is not None:
                return result
    for oc, cc in [("{", "}"), ("[", "]")]:
        first = text.find(oc)
        if first != -1:
            balanced = _extract_balanced(text[first:], oc, cc)
            if balanced:
                result = _try_parse(balanced)
                if result is not None:
                    return result
    logger.warning("_extract_json: không parse được JSON (len=%d)", len(raw))
    return None


def call_llm(prompt: str):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("Cần cài: pip install google-genai")

    client = get_client()
    config = types.GenerateContentConfig(response_mime_type="application/json")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME, contents=prompt, config=config
            )
            raw = response.text or ""
            if not raw.strip():
                logger.warning(f"Attempt {attempt}: empty response.")
                continue
            parsed = _extract_json(raw)
            if parsed is not None:
                logger.info(
                    f"Attempt {attempt}: parse JSON thành công (len={len(raw)})."
                )
                return parsed
            logger.warning(
                f"Attempt {attempt}: không parse được JSON (preview: {raw[:200]!r})"
            )
        except Exception as exc:
            delay = BASE_DELAY * (2 ** (attempt - 1))
            logger.error(
                f"LLM error (attempt {attempt}/{MAX_RETRIES}): {exc} – retry sau {delay}s"
            )
            if attempt < MAX_RETRIES:
                time.sleep(delay)
    return None
