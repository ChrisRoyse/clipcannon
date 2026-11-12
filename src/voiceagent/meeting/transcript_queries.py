"""Query / retrieval and crash recovery for the meeting transcript store.

Split out of ``voiceagent.meeting.transcript_store`` (pure move): the
search / list / get / export / stale-recovery methods that
``MeetingTranscriptStore`` inherits from ``_TranscriptQueryMixin``.
"""

from __future__ import annotations

import logging
from typing import Any

from voiceagent.meeting.errors import MeetingTranscriptStoreError

logger = logging.getLogger(__name__)


class _TranscriptQueryMixin:
    """Leapable search / retrieval and stale-transcript recovery."""

    # ------------------------------------------------------------------
    # Query / retrieval
    # ------------------------------------------------------------------

    async def search(self, query: str, limit: int = 20) -> dict:
        """Hybrid (keyword + semantic) search across all meetings.

        Args:
            query: Natural-language question (Leapable requires 8+ words).
            limit: Maximum number of results.

        Returns:
            The Leapable search ``data`` payload (``results``, ``low_confidence``,
            ``total``, ...).

        Raises:
            MeetingTranscriptStoreError: If search fails.
        """
        await self._ensure_db()
        return await self._call(
            "leapable_search", {"query": query, "limit": limit},
        )

    async def list_meetings(
        self, limit: int = 50, cursor: str | None = None,
    ) -> dict:
        """List meeting documents in the Leapable 'meetings' Vault.

        Returns:
            The Leapable document-list ``data`` payload (``documents``,
            ``total``, ``next_cursor``).

        Raises:
            MeetingTranscriptStoreError: If the list operation fails.
        """
        await self._ensure_db()
        args: dict[str, Any] = {"limit": limit}
        if cursor:
            args["cursor"] = cursor
        return await self._call("leapable_document_list", args)

    async def get_meeting(self, document_id: str) -> dict:
        """Get a full meeting document (with OCR text) from Leapable.

        Raises:
            MeetingTranscriptStoreError: If document retrieval fails.
        """
        await self._ensure_db()
        return await self._call(
            "leapable_document_get",
            {"document_id": document_id, "include_text": True},
        )

    async def export_meeting(
        self,
        document_id: str,
        output_path: str,
        export_format: str = "markdown",
    ) -> dict:
        """Export a meeting document to a file via Leapable.

        Args:
            document_id: The Leapable document ID to export.
            output_path: Where Leapable should write the exported file
                (required by Leapable).
            export_format: "markdown" or "json" for a single document.

        Raises:
            MeetingTranscriptStoreError: If export fails.
        """
        await self._ensure_db()
        return await self._call(
            "leapable_export",
            {
                "document_id": document_id,
                "format": export_format,
                "output_path": output_path,
            },
        )

    async def recover_stale_transcripts(self) -> int:
        """Ingest any mtg_*.md files left in transcript_dir by prior crashes.

        Ingests each into Leapable (inline base64), then deletes the local
        file. Returns the count of successfully recovered files.

        Raises:
            MeetingTranscriptStoreError: If Vault setup fails.
        """
        await self._ensure_db()
        stale_files = list(self._transcript_dir.glob("mtg_*.md"))
        if not stale_files:
            return 0
        count = 0
        for path in stale_files:
            try:
                md = path.read_text(encoding="utf-8")
                await self._ingest_markdown(path.name, md)
                path.unlink()
                count += 1
                logger.info("Recovered stale transcript: %s", path.name)
            except (MeetingTranscriptStoreError, OSError) as exc:
                logger.error("Failed to recover %s: %s", path.name, exc)
        return count
