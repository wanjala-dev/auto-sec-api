"""
Thin OpenAI wrapper for workspace data utilities.
"""

from openai import OpenAI, RateLimitError
from django.conf import settings

client = OpenAI(api_key=settings.OPEN_AI_SECRET_KEY)


def generate_response(prompt: str) -> str:
    try:
        response = client.completions.create(
            model="text-davinci-003",
            prompt=prompt,
            max_tokens=2048,
            n=1,
            stop=None,
            top_p=1.0,
            temperature=0.7,
            frequency_penalty=0,
            presence_penalty=0,
        )
        return response.choices[0].text.strip().replace("\n", " ")
    except RateLimitError as e:  # pragma: no cover - external service
        # Handle the rate limit error gracefully
        return f"Rate limit error: {e}"
