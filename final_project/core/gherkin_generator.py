from core.llm_client import get_client


def generate_gherkin(user_story: str) -> str:
    if not user_story.strip():
        return "User Story trống."

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

    response = client.models.generate_content(
        model="gemini-flash-latest", contents=prompt
    )

    return response.text
