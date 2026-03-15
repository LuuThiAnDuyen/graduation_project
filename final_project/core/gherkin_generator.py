import time
from google.genai import errors
from core.llm_client import get_client


MAX_CHARS = 10000
MAX_RETRIES = 3
BASE_DELAY = 2


def generate_gherkin(user_story: str) -> str:
    if not user_story or not user_story.strip():
        return "User Story trống."

    user_story = user_story.strip()

    if len(user_story) > MAX_CHARS:
        user_story = user_story[:MAX_CHARS]

    client = get_client()

    prompt = f"""
You are a senior QA engineer.
From the following user story, generate Gherkin scenarios.

Include:
- Positive cases
- Negative cases
- Boundary cases

User Story:
{user_story}

Output only valid Gherkin syntax.
"""

    model_name = "gemini-flash-latest"

    delay = BASE_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)

            if hasattr(response, "text") and response.text:
                return response.text.strip()

            return "Không nhận được nội dung từ model."

        except errors.ServerError as e:
            error_code = getattr(e, "code", None)

            if error_code == 503:
                print(f"[{model_name}] overloaded. Retry {attempt}/{MAX_RETRIES}")
                time.sleep(delay)
                delay *= 2
                continue
            else:
                return f"Lỗi server: {str(e)}"

        except Exception as e:
            return f"Lỗi khi gọi AI: {str(e)}"

    return "AI service is temporarily overloaded. Please try again later."
