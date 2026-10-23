"""AI-модули BodyPilot на базе Gemini."""

from .gemini_client import GeminiClient, get_gemini_client
from .food_recognition import recognize_and_add_food, get_food_suggestions

__all__ = [
    "GeminiClient",
    "get_gemini_client",
    "recognize_and_add_food",
    "get_food_suggestions",
]