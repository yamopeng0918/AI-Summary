"""Summary generation adapters."""

from ai_digest.summarizers.base import Summarizer
from ai_digest.summarizers.openai import OpenAISummarizer

__all__ = ["OpenAISummarizer", "Summarizer"]
