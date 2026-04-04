"""Meeting response generation via local Ollama LLM with OCR Provenance RAG.

Generates direct, concise answers to questions directed at a clone.
When OCR Provenance is available, searches meeting history for relevant
context before generating a response (Retrieval-Augmented Generation).

Rules:
- Answer ONLY the specific question asked
- 1-3 sentences maximum (unless question requires detail)
- No preamble, no extra context, no follow-up questions
- No markdown, no lists -- spoken conversation
- Stop immediately after answering
- Use meeting history context when available and relevant
"""
from __future__ import annotations

import logging

import httpx

from voiceagent.meeting.config import ResponseConfig
from voiceagent.meeting.errors import MeetingResponseError
from voiceagent.meeting.mcp_client import OcrProvenanceClient
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
    "No markdown, no lists, no formatting -- this is spoken conversation. "
    "Use full prosody -- vary your pitch, pace, and emphasis naturally. "
    "Speak as a real person would in conversation, not as a text reader."
)

SYSTEM_PROMPT_WITH_HISTORY = (
    "You are {clone_name}, attending a video meeting. "
    "You have been directly asked a question. "
    "You have access to context from past meetings and the current meeting. "
    "Use this context to give informed, accurate answers. "
    "If the context contains the answer, use it. If not, say so honestly. "
    "Answer ONLY the specific question asked. "
    "Be direct and concise -- 1-3 sentences for simple questions, "
    "up to 5 sentences if the question requires detail from meeting history. "
    "Do not volunteer additional information beyond what was asked. "
    "No markdown, no lists, no formatting -- this is spoken conversation. "
    "Use full prosody -- vary your pitch, pace, and emphasis naturally."
)

# Maximum time (seconds) to wait for Ollama to return a response.
_OLLAMA_TIMEOUT_S = 60.0

# Maximum number of recent meeting segments to include as context.
_MAX_CONTEXT_SEGMENTS = 20

# Maximum number of OCR Provenance search results to include.
_MAX_HISTORY_RESULTS = 5


class MeetingResponder:
    """Generate meeting responses via local Ollama LLM with optional RAG.

    When an OCR Provenance client is provided, searches meeting history
    for relevant context before generating responses. This allows the
    clone to answer questions about past meetings, action items, and
    historical context.

    Args:
        config: Response generation configuration (model, temperature, etc.).
        clone_name: Name of the clone generating responses.
        ocr_client: Optional OCR Provenance client for meeting history search.
    """

    def __init__(
        self,
        config: ResponseConfig,
        clone_name: str = "Nate",
        ocr_client: OcrProvenanceClient | None = None,
    ) -> None:
        self._config = config
        self._clone_name = clone_name
        self._base_url = "http://localhost:11434"
        self._ocr_client = ocr_client
        self._system_prompt = config.system_prompt_override or (
            SYSTEM_PROMPT_WITH_HISTORY if ocr_client
            else SYSTEM_PROMPT_TEMPLATE
        ).format(clone_name=clone_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_response(
        self,
        question: str,
        meeting_context: list[MeetingSegment] | None = None,
    ) -> str:
        """Generate a direct answer to a question.

        If an OCR Provenance client is available, searches meeting history
        for context relevant to the question before generating the response.

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
        history_str = await self._search_history(question)

        # Build prompt with all available context
        parts: list[str] = []
        if history_str:
            parts.append(
                f"Relevant context from past meetings:\n{history_str}"
            )
        if context_str:
            parts.append(f"Current meeting context:\n{context_str}")
        parts.append(f"Question directed at you: {question}")

        prompt = "\n\n".join(parts)

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
    # OCR Provenance history search (RAG)
    # ------------------------------------------------------------------

    async def _search_history(self, question: str) -> str:
        """Search OCR Provenance meeting history for relevant context.

        Best-effort: if OCR Provenance is unavailable or search fails,
        returns empty string and logs the error. Never raises.

        Args:
            question: The question to search for relevant context.

        Returns:
            Formatted string of relevant meeting history excerpts,
            or empty string if unavailable.
        """
        if self._ocr_client is None:
            return ""

        try:
            result = await self._ocr_client.call_tool(
                "ocr_search",
                {"query": question, "limit": _MAX_HISTORY_RESULTS},
            )
        except Exception as exc:
            logger.debug("OCR Provenance search failed: %s", exc)
            return ""

        return self._format_search_results(result)

    @staticmethod
    def _format_search_results(result: dict) -> str:
        """Format OCR Provenance search results into context string.

        Args:
            result: Raw search result from OCR Provenance.

        Returns:
            Formatted string with relevant excerpts.
        """
        if not isinstance(result, dict):
            return ""

        # OCR Provenance search returns results in various formats
        results = result.get("results", [])
        if not results:
            # Try alternate format
            results = result.get("chunks", [])
        if not results:
            # Try text field directly
            text = result.get("text", "")
            if text:
                return text[:1000]
            return ""

        lines: list[str] = []
        for item in results[:_MAX_HISTORY_RESULTS]:
            if isinstance(item, dict):
                text = item.get("text", item.get("content", ""))
                doc_title = item.get("document_title", "")
                score = item.get("score", item.get("similarity", 0))
                if text:
                    prefix = f"[{doc_title}]" if doc_title else ""
                    # Truncate long excerpts
                    excerpt = text[:300].strip()
                    if len(text) > 300:
                        excerpt += "..."
                    if prefix:
                        lines.append(f"{prefix} {excerpt}")
                    else:
                        lines.append(excerpt)
            elif isinstance(item, str):
                lines.append(item[:300])

        return "\n".join(lines)

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
