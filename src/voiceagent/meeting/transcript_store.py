"""Meeting transcript storage via OCR Provenance MCP.

Each meeting is a Markdown document ingested into the 'meetings' database.
OCR Provenance handles chunking, embedding, indexing, search, and export.

No local database. No garbage data. OCR Provenance is the single source of truth.
In-flight Markdown files are written to transcript_dir during meetings for crash
safety, then DELETED after successful ingest.

The MCP server MUST be running. If it's not, operations fail fast with
MeetingTranscriptStoreError.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from voiceagent.meeting.config import TranscriptConfig
from voiceagent.meeting.errors import MeetingTranscriptStoreError
from voiceagent.meeting.mcp_client import OcrProvenanceClient
from voiceagent.meeting.transcript_format import (
    CloneInteraction,
    MeetingDocument,
    MeetingSegment,
    build_partial_transcript,
    build_transcript_markdown,
)

logger = logging.getLogger(__name__)


class MeetingTranscriptStore:
    """Meeting transcript storage via OCR Provenance MCP server.

    Lifecycle:
    1. create_meeting() -- generates meeting_id, creates in-memory MeetingDocument
    2. append_segment() -- adds segments to in-memory buffer
    3. record_interaction() -- adds Q&A interactions to buffer
    4. flush() -- writes Markdown to transcript_dir (crash safety, periodic)
    5. end_meeting() -- finalizes Markdown, ingests into OCR Provenance,
       tags it, DELETES the local file after successful ingest

    No local database. No garbage files. The only persistent storage is
    OCR Provenance's 'meetings' database.
    """

    def __init__(self, config: TranscriptConfig | None = None) -> None:
        """Initialize the transcript store.

        Args:
            config: Transcript storage configuration. Uses defaults if None.
        """
        self._config = config or TranscriptConfig()
        self._transcript_dir = Path(self._config.transcript_dir).expanduser()
        self._transcript_dir.mkdir(parents=True, exist_ok=True)
        self._client = OcrProvenanceClient(
            base_url=self._config.ocr_provenance_url,
        )
        self._active_meetings: dict[str, MeetingDocument] = {}
        self._segment_counts: dict[str, int] = {}
        self._db_ensured = False

    async def _ensure_db(self) -> None:
        """Create and select the 'meetings' database in OCR Provenance.

        Called once on first operation. Idempotent -- if the database already
        exists, just selects it.

        Raises:
            MeetingTranscriptStoreError: If database creation or selection fails.
        """
        if self._db_ensured:
            return
        try:
            await self._client.call_tool(
                "ocr_db_select", {"name": self._config.database_name},
            )
            self._db_ensured = True
            return
        except MeetingTranscriptStoreError:
            pass
        await self._client.call_tool(
            "ocr_db_create",
            {
                "name": self._config.database_name,
                "description": "Clone meeting transcripts -- auto-managed by voiceagent",
            },
        )
        await self._client.call_tool(
            "ocr_db_select", {"name": self._config.database_name},
        )
        self._db_ensured = True

    def _get_meeting(self, meeting_id: str) -> MeetingDocument:
        """Get an active meeting document by ID.

        Args:
            meeting_id: The meeting identifier.

        Returns:
            The active MeetingDocument.

        Raises:
            MeetingTranscriptStoreError: If no active meeting with that ID.
        """
        doc = self._active_meetings.get(meeting_id)
        if doc is None:
            raise MeetingTranscriptStoreError(
                f"No active meeting with id '{meeting_id}'"
            )
        return doc

    def create_meeting(
        self,
        clone_names: list[str],
        platform: str = "unknown",
    ) -> str:
        """Create a new meeting and return its meeting_id.

        Args:
            clone_names: Names of clones participating in the meeting.
            platform: Meeting platform name (e.g. "zoom", "teams").

        Returns:
            The generated meeting_id (format: "mtg_<12 hex chars>").
        """
        meeting_id = f"mtg_{uuid.uuid4().hex[:12]}"
        doc = MeetingDocument(
            meeting_id=meeting_id,
            title="",
            started_at=datetime.now(),
            platform=platform,
            clone_names=list(clone_names),
        )
        self._active_meetings[meeting_id] = doc
        self._segment_counts[meeting_id] = 0
        logger.info(
            "Meeting created: %s (clones=%s)", meeting_id, clone_names,
        )
        return meeting_id

    def append_segment(
        self, meeting_id: str, segment: MeetingSegment,
    ) -> None:
        """Append a transcript segment to the in-memory buffer.

        Automatically tracks participant names from non-clone speakers.

        Args:
            meeting_id: The meeting to append to.
            segment: The transcript segment to add.

        Raises:
            MeetingTranscriptStoreError: If meeting_id is not active.
        """
        doc = self._get_meeting(meeting_id)
        doc.segments.append(segment)
        self._segment_counts[meeting_id] = (
            self._segment_counts.get(meeting_id, 0) + 1
        )
        if segment.speaker_name and not segment.is_clone:
            if segment.speaker_name not in doc.participant_names:
                doc.participant_names.append(segment.speaker_name)

    def record_interaction(
        self, meeting_id: str, interaction: CloneInteraction,
    ) -> None:
        """Record a clone Q&A interaction.

        Args:
            meeting_id: The meeting to record to.
            interaction: The Q&A interaction data.

        Raises:
            MeetingTranscriptStoreError: If meeting_id is not active.
        """
        doc = self._get_meeting(meeting_id)
        doc.interactions.append(interaction)

    def should_flush(self, meeting_id: str) -> bool:
        """Check if we should flush to disk based on segment count.

        Args:
            meeting_id: The meeting to check.

        Returns:
            True if segment count since last flush >= flush_interval_segments.
        """
        count = self._segment_counts.get(meeting_id, 0)
        return count >= self._config.flush_interval_segments

    def flush(self, meeting_id: str) -> Path:
        """Write current transcript state to Markdown file on disk.

        This is for crash safety during the meeting. The file will be
        deleted after successful ingest into OCR Provenance on end_meeting().

        Args:
            meeting_id: The meeting to flush.

        Returns:
            Path to the written Markdown file.

        Raises:
            MeetingTranscriptStoreError: If meeting_id is not active.
        """
        doc = self._get_meeting(meeting_id)
        md = build_partial_transcript(doc)
        path = self._transcript_dir / f"{meeting_id}.md"
        path.write_text(md, encoding="utf-8")
        self._segment_counts[meeting_id] = 0
        logger.debug(
            "Flushed %s (%d segments)", meeting_id, len(doc.segments),
        )
        return path

    async def end_meeting(
        self,
        meeting_id: str,
        summary: str = "",
        tags: list[str] | None = None,
    ) -> str:
        """End meeting: finalize Markdown, ingest into OCR Provenance, delete local file.

        Auto-generates title if not set. Writes final Markdown to disk,
        ingests it into OCR Provenance, applies tags, then deletes the
        local file. OCR Provenance becomes the single source of truth.

        Args:
            meeting_id: The meeting to end.
            summary: Optional post-meeting summary text.
            tags: Optional list of tags to apply.

        Returns:
            The OCR Provenance document_id for the ingested transcript.

        Raises:
            MeetingTranscriptStoreError: If meeting_id is not active or
                ingest fails.
        """
        doc = self._get_meeting(meeting_id)

        doc.ended_at = datetime.now()
        doc.duration_minutes = int(
            (doc.ended_at - doc.started_at).total_seconds() / 60
        )
        doc.summary = summary
        if tags:
            doc.tags = tags

        if not doc.title:
            participants = ", ".join(doc.participant_names[:3]) or "Unknown"
            date_str = doc.started_at.strftime("%b %d, %Y")
            doc.title = f"Meeting with {participants} -- {date_str}"

        md = build_transcript_markdown(doc)
        path = self._transcript_dir / f"{meeting_id}.md"
        path.write_text(md, encoding="utf-8")

        await self._ensure_db()
        result = await self._client.call_tool(
            "ocr_ingest_files",
            {
                "files": [str(path)],
                "disable_image_extraction": True,
            },
        )

        doc_id = _extract_document_id(result, meeting_id)

        if self._config.auto_tag and doc.tags:
            await self._apply_tags(doc_id, doc.tags)

        path.unlink(missing_ok=True)

        segment_count = len(doc.segments)
        interaction_count = len(doc.interactions)
        del self._active_meetings[meeting_id]
        self._segment_counts.pop(meeting_id, None)

        logger.info(
            "Meeting ended: %s -> OCR Provenance doc %s (%d segments, %d interactions)",
            meeting_id,
            doc_id,
            segment_count,
            interaction_count,
        )
        return doc_id

    async def _apply_tags(self, doc_id: str, tags: list[str]) -> None:
        """Create and apply tags to a document in OCR Provenance.

        Args:
            doc_id: The OCR Provenance document ID.
            tags: List of tag names to apply.
        """
        for tag in tags:
            try:
                await self._client.call_tool("ocr_tag_create", {"name": tag})
            except MeetingTranscriptStoreError:
                pass  # Tag may already exist
            await self._client.call_tool(
                "ocr_tag_apply",
                {
                    "tag_name": tag,
                    "entity_type": "document",
                    "entity_id": doc_id,
                },
            )

    async def search(self, query: str, limit: int = 20) -> dict:
        """Semantic + full-text hybrid search across all meetings.

        Args:
            query: Search query text.
            limit: Maximum number of results to return.

        Returns:
            Raw OCR Provenance search result dict.

        Raises:
            MeetingTranscriptStoreError: If search fails.
        """
        await self._ensure_db()
        return await self._client.call_tool(
            "ocr_search", {"query": query, "limit": limit},
        )

    async def list_meetings(
        self, limit: int = 50, cursor: str | None = None,
    ) -> dict:
        """List all meeting documents in OCR Provenance.

        Args:
            limit: Maximum number of documents to return.
            cursor: Pagination cursor from a previous list call.

        Returns:
            Raw OCR Provenance document list result dict.

        Raises:
            MeetingTranscriptStoreError: If list operation fails.
        """
        await self._ensure_db()
        args: dict = {"limit": limit}
        if cursor:
            args["cursor"] = cursor
        return await self._client.call_tool("ocr_document_list", args)

    async def get_meeting(self, document_id: str) -> dict:
        """Get a full meeting document from OCR Provenance.

        Args:
            document_id: The OCR Provenance document ID.

        Returns:
            Raw OCR Provenance document result dict.

        Raises:
            MeetingTranscriptStoreError: If document retrieval fails.
        """
        await self._ensure_db()
        return await self._client.call_tool(
            "ocr_document_get", {"id": document_id},
        )

    async def export_meeting(
        self, document_id: str, export_format: str = "markdown",
    ) -> dict:
        """Export a meeting via OCR Provenance.

        Args:
            document_id: The OCR Provenance document ID to export.
            export_format: Export format (e.g. "markdown", "json").

        Returns:
            Raw OCR Provenance export result dict.

        Raises:
            MeetingTranscriptStoreError: If export fails.
        """
        await self._ensure_db()
        return await self._client.call_tool(
            "ocr_export",
            {"document_id": document_id, "format": export_format},
        )

    async def recover_stale_transcripts(self) -> int:
        """Ingest any .md files left in transcript_dir from previous crashes.

        Scans the transcript directory for mtg_*.md files, ingests each
        into OCR Provenance, then deletes the local file.

        Returns:
            Count of successfully recovered files.

        Raises:
            MeetingTranscriptStoreError: If database setup fails.
        """
        await self._ensure_db()
        stale_files = list(self._transcript_dir.glob("mtg_*.md"))
        if not stale_files:
            return 0
        count = 0
        for path in stale_files:
            try:
                await self._client.call_tool(
                    "ocr_ingest_files",
                    {
                        "files": [str(path)],
                        "disable_image_extraction": True,
                    },
                )
                path.unlink()
                count += 1
                logger.info("Recovered stale transcript: %s", path.name)
            except MeetingTranscriptStoreError as exc:
                logger.error("Failed to recover %s: %s", path.name, exc)
        return count

    async def close(self) -> None:
        """Close the MCP client and release all connections.

        Must be called on shutdown to prevent connection leaks.
        """
        await self._client.close()


def _extract_document_id(result: object, meeting_id: str) -> str:
    """Extract the document_id from an OCR Provenance ingest result.

    Args:
        result: The raw result from ocr_ingest_files.
        meeting_id: The meeting ID (for error messages).

    Returns:
        The document ID string.

    Raises:
        MeetingTranscriptStoreError: If no document_id can be extracted.
    """
    doc_id = ""
    if isinstance(result, dict):
        docs = result.get("documents", [])
        if isinstance(docs, list) and len(docs) > 0:
            first = docs[0]
            if isinstance(first, dict):
                doc_id = first.get("id", "")
    if not doc_id:
        raise MeetingTranscriptStoreError(
            f"OCR Provenance ingest returned no document_id for {meeting_id}. "
            f"Result: {str(result)[:500]}"
        )
    return doc_id
