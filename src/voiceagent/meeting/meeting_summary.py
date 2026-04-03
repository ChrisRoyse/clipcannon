"""Post-meeting summary, title, and topic tag generation via local Ollama LLM.

Uses the Ollama HTTP API (/api/generate) to produce concise meeting
summaries, auto-titles, and topic tags from transcript segments.
"""
from __future__ import annotations

import logging
from typing import Final

import httpx

from voiceagent.meeting.errors import MeetingResponseError
from voiceagent.meeting.transcript_format import MeetingSegment

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL: Final[str] = "http://localhost:11434"
_DEFAULT_MODEL: Final[str] = "qwen3:14b-nothink"
_REQUEST_TIMEOUT_S: Final[float] = 30.0

_SUMMARY_MAX_TOKENS: Final[int] = 256
_TITLE_MAX_TOKENS: Final[int] = 64
_TOPICS_MAX_TOKENS: Final[int] = 128
_TEMPERATURE: Final[float] = 0.3

_SUMMARY_PROMPT: Final[str] = (
    "You are a meeting summarizer. Given the transcript below, produce "
    "3 to 5 bullet points covering:\n"
    "- Decisions made\n"
    "- Action items assigned\n"
    "- Key discussion points\n\n"
    "Ignore greetings, small talk, and filler. "
    "Output ONLY the bullet points, one per line, starting with '- '.\n\n"
    "TRANSCRIPT:\n{transcript}"
)

_TITLE_PROMPT: Final[str] = (
    "Generate a concise meeting title (one line, under 80 characters) "
    "from the transcript and summary below. "
    "Format: 'Topic with Participant1 and Participant2'.\n"
    "Output ONLY the title, nothing else.\n\n"
    "SUMMARY:\n{summary}\n\n"
    "TRANSCRIPT:\n{transcript}"
)

_TOPICS_PROMPT: Final[str] = (
    "Extract 3 to 5 topic tags from the meeting summary below. "
    "Output ONLY the tags as a comma-separated list of lowercase words or "
    "short phrases. No numbering, no bullets.\n\n"
    "SUMMARY:\n{summary}"
)


class MeetingSummaryGenerator:
    """Generates meeting summaries, titles, and topic tags via Ollama.

    Uses the /api/generate endpoint (non-streaming) with the configured
    local LLM model. Fails fast if Ollama is unreachable.

    Args:
        base_url: Ollama server base URL.
        model: Ollama model identifier.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def _build_transcript_text(self, segments: list[MeetingSegment]) -> str:
        """Build a plain-text transcript from meeting segments.

        Args:
            segments: Ordered list of meeting transcript segments.

        Returns:
            Multi-line transcript string with speaker labels and text.
        """
        lines: list[str] = []
        for seg in segments:
            speaker = seg.speaker_name or seg.speaker_id or "Unknown"
            # Strip clone annotation suffix for cleaner transcript
            if " (Clone)" in speaker:
                speaker = speaker.replace(" (Clone)", "")
            lines.append(f"{speaker}: {seg.text}")
        return "\n".join(lines)

    async def _call_ollama(self, prompt: str, max_tokens: int) -> str:
        """Send a generate request to Ollama and return the response text.

        Args:
            prompt: The full prompt string.
            max_tokens: Maximum number of tokens for the response.

        Returns:
            The generated text from Ollama.

        Raises:
            MeetingResponseError: If Ollama is unreachable, returns an error
                HTTP status, or produces an empty response.
        """
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": _TEMPERATURE,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
                resp = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise MeetingResponseError(
                f"Cannot connect to Ollama at {self._base_url}. "
                f"Ensure Ollama is running: 'ollama serve'. Detail: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise MeetingResponseError(
                f"Ollama request timed out after {_REQUEST_TIMEOUT_S}s. "
                f"The meeting transcript may be too long or Ollama is overloaded. "
                f"Detail: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise MeetingResponseError(
                f"HTTP error calling Ollama at {url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            raise MeetingResponseError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:500]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise MeetingResponseError(
                f"Ollama returned invalid JSON: {resp.text[:500]}"
            ) from exc

        text = data.get("response", "").strip()
        if not text:
            raise MeetingResponseError(
                f"Ollama returned empty response for model '{self._model}'. "
                f"Full payload: {data}"
            )

        return text

    async def generate_summary(self, segments: list[MeetingSegment]) -> str:
        """Generate a 3-5 bullet point meeting summary.

        Args:
            segments: Ordered list of meeting transcript segments.

        Returns:
            Plain text with bullet points (each starting with '- ').

        Raises:
            MeetingResponseError: If the LLM call fails or returns empty.
        """
        if not segments:
            raise MeetingResponseError(
                "Cannot generate summary: no transcript segments provided."
            )

        transcript = self._build_transcript_text(segments)
        prompt = _SUMMARY_PROMPT.format(transcript=transcript)
        logger.debug("Generating meeting summary (%d segments)", len(segments))
        return await self._call_ollama(prompt, _SUMMARY_MAX_TOKENS)

    async def generate_title(
        self,
        segments: list[MeetingSegment],
        summary: str,
    ) -> str:
        """Generate a concise single-line meeting title.

        Args:
            segments: Ordered list of meeting transcript segments.
            summary: Previously generated meeting summary text.

        Returns:
            Single-line title string, e.g. 'API Review with Sarah and Nate'.

        Raises:
            MeetingResponseError: If the LLM call fails or returns empty.
        """
        if not segments:
            raise MeetingResponseError(
                "Cannot generate title: no transcript segments provided."
            )

        transcript = self._build_transcript_text(segments)
        prompt = _TITLE_PROMPT.format(summary=summary, transcript=transcript)
        logger.debug("Generating meeting title")
        title = await self._call_ollama(prompt, _TITLE_MAX_TOKENS)
        # Strip quotes and trailing punctuation the LLM might add
        title = title.strip().strip('"').strip("'").strip()
        # Take only the first line if LLM produced multiple
        return title.split("\n")[0].strip()

    async def extract_topics(self, summary: str) -> list[str]:
        """Extract 3-5 topic tags from a meeting summary.

        Args:
            summary: Previously generated meeting summary text.

        Returns:
            List of lowercase topic tag strings.

        Raises:
            MeetingResponseError: If the LLM call fails or returns empty.
        """
        if not summary:
            raise MeetingResponseError(
                "Cannot extract topics: empty summary provided."
            )

        prompt = _TOPICS_PROMPT.format(summary=summary)
        logger.debug("Extracting meeting topics")
        raw = await self._call_ollama(prompt, _TOPICS_MAX_TOKENS)

        # Parse comma-separated tags, normalizing to lowercase
        tags: list[str] = []
        for tag in raw.split(","):
            cleaned = tag.strip().lower().strip(".-#* ")
            if cleaned:
                tags.append(cleaned)

        if not tags:
            raise MeetingResponseError(
                f"Ollama returned no parseable topic tags. Raw response: {raw!r}"
            )

        return tags
