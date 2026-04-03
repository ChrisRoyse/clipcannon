"""Meeting response generation via local Ollama LLM.

Generates direct, concise answers to questions directed at a clone.
Rules:
- Answer ONLY the specific question asked
- 1-3 sentences maximum
- No preamble, no extra context, no follow-up questions
- No markdown, no lists -- spoken conversation
- Stop immediately after answering
"""
from __future__ import annotations

import logging

import httpx

from voiceagent.meeting.config import ResponseConfig
from voiceagent.meeting.errors import MeetingResponseError
from voiceagent.meeting.transcript_format import MeetingSegment

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = (
    "You are {clone_name}, attending a video meeting. "
    "You have been directly asked a question. "
    "Answer ONLY the specific question asked. "
    "Be direct and concise -- 1-3 sentences maximum. "
    "Do not volunteer additional information. "
    "Do not ask follow-up questions. "
    "Do not use filler phrases like 'great question' or 'that is interesting'. "
    "Stop talking as soon as you have answered the question. "
    "No markdown, no lists, no formatting -- this is spoken conversation."
)

# Maximum time (seconds) to wait for Ollama to return a response.
_OLLAMA_TIMEOUT_S = 30.0

# Maximum number of recent meeting segments to include as context.
_MAX_CONTEXT_SEGMENTS = 20


class MeetingResponder:
    """Generate meeting responses via local Ollama LLM.

    Calls the Ollama ``/api/generate`` endpoint with a system prompt that
    forces short, direct, spoken-style answers.  If Ollama is unreachable
    or returns an error, a :class:`MeetingResponseError` is raised
    immediately -- there are no fallback responses.

    Args:
        config: Response generation configuration (model, temperature, etc.).
        clone_name: Name of the clone generating responses.
    """

    def __init__(self, config: ResponseConfig, clone_name: str = "Nate") -> None:
        self._config = config
        self._clone_name = clone_name
        self._base_url = "http://localhost:11434"
        self._system_prompt = (
            config.system_prompt_override
            or SYSTEM_PROMPT_TEMPLATE.format(clone_name=clone_name)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_response(
        self,
        question: str,
        meeting_context: list[MeetingSegment] | None = None,
    ) -> str:
        """Generate a direct answer to a question.

        Args:
            question: The question asked of the clone.
            meeting_context: Recent meeting segments for context (last ~2 min).

        Returns:
            Response text (1-3 sentences, no formatting).

        Raises:
            MeetingResponseError: If Ollama is unreachable, times out,
                returns a non-200 status, or produces an empty response.
        """
        context_str = self._build_context(meeting_context)

        if context_str:
            prompt = (
                f"Meeting context:\n{context_str}\n\n"
                f"Question directed at you: {question}"
            )
        else:
            prompt = f"Question directed at you: {question}"

        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "system": self._system_prompt,
            "stream": False,
            "options": {
                "num_predict": self._config.max_tokens,
                "temperature": self._config.temperature,
                "top_p": 0.8,
                "top_k": 20,
            },
        }

        resp = await self._call_ollama(payload)
        return self._parse_response(resp, question)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        meeting_context: list[MeetingSegment] | None,
    ) -> str:
        """Format recent meeting segments into a context string."""
        if not meeting_context:
            return ""
        lines: list[str] = []
        for seg in meeting_context[-_MAX_CONTEXT_SEGMENTS:]:
            speaker = seg.speaker_name or seg.speaker_id or "Unknown"
            lines.append(f"{speaker}: {seg.text}")
        return "\n".join(lines)

    async def _call_ollama(self, payload: dict) -> httpx.Response:
        """POST to Ollama and return the raw response.

        Raises:
            MeetingResponseError: On connection or timeout failures.
        """
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT_S) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}/api/generate",
                    json=payload,
                )
            except httpx.ConnectError as exc:
                raise MeetingResponseError(
                    f"Cannot connect to Ollama at {self._base_url}. "
                    f"Is Ollama running? Start with: ollama serve. "
                    f"Error: {exc}"
                ) from exc
            except httpx.TimeoutException as exc:
                raise MeetingResponseError(
                    f"Ollama response timed out after "
                    f"{_OLLAMA_TIMEOUT_S:.0f}s: {exc}"
                ) from exc
        return resp

    @staticmethod
    def _parse_response(resp: httpx.Response, question: str) -> str:
        """Extract and validate response text from the Ollama HTTP response.

        Raises:
            MeetingResponseError: On non-200 status, bad JSON, or empty text.
        """
        if resp.status_code != 200:
            raise MeetingResponseError(
                f"Ollama returned HTTP {resp.status_code}: "
                f"{resp.text[:300]}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise MeetingResponseError(
                f"Invalid JSON from Ollama: {exc}"
            ) from exc

        response_text = body.get("response", "").strip()
        if not response_text:
            raise MeetingResponseError(
                f"Ollama returned empty response for question: "
                f"'{question[:100]}'"
            )

        logger.info(
            "Response generated (%d chars): '%s'",
            len(response_text),
            response_text[:100],
        )
        return response_text
