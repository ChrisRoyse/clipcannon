"""Meeting transcript storage via Leapable MCP.

Each meeting is a Markdown document ingested into the 'meetings' Vault.
Leapable handles OCR/parsing, chunking, embedding, indexing, hybrid search,
and export. Leapable is the single source of truth for finalized transcripts.

In-flight Markdown files are written to ``transcript_dir`` during the meeting
for crash safety. Transcripts are ingested into Leapable using **inline
base64** content (not file paths): the Leapable runtime may run on a different
host (e.g. the Windows host while voiceagent runs in WSL), so it cannot read
voiceagent's local filesystem. Inline content sidesteps all path-translation
fragility.

The Leapable runtime MUST be running. If it is not, operations fail fast with
MeetingTranscriptStoreError -- there is no silent fallback or local-only mode.
"""
from __future__ import annotations

import base64
import gc
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from voiceagent.meeting.config import TranscriptConfig
from voiceagent.meeting.errors import MeetingTranscriptStoreError
from voiceagent.meeting.mcp_client import LeapableClient
from voiceagent.meeting.transcript_format import (
    CloneInteraction,
    MeetingDocument,
    MeetingSegment,
    build_partial_transcript,
    build_transcript_markdown,
)
from voiceagent.meeting.transcript_queries import _TranscriptQueryMixin

# Maximum segments kept in memory per meeting. Older segments are
# flushed to disk and dropped from the in-memory buffer.
_MAX_IN_MEMORY_SEGMENTS = 500

logger = logging.getLogger(__name__)


class MeetingTranscriptStore(_TranscriptQueryMixin):
    """Meeting transcript storage backed by the Leapable MCP server.

    Lifecycle:
    1. create_meeting() -- generates meeting_id, creates in-memory MeetingDocument
    2. append_segment() -- adds segments to the in-memory buffer
    3. record_interaction() -- adds Q&A interactions to the buffer
    4. flush() -- writes Markdown to transcript_dir (crash safety, periodic)
    5. end_meeting() -- finalizes Markdown, ingests it into Leapable (inline),
       tags it, then deletes the local crash-safety file

    The only persistent store is the Leapable 'meetings' Vault.
    """

    def __init__(self, config: TranscriptConfig | None = None) -> None:
        """Initialize the transcript store.

        Args:
            config: Transcript storage configuration. Uses defaults if None.
        """
        self._config = config or TranscriptConfig()
        self._transcript_dir = Path(self._config.transcript_dir).expanduser()
        self._transcript_dir.mkdir(parents=True, exist_ok=True)
        self._client = LeapableClient(base_url=self._config.leapable_url)
        self._active_meetings: dict[str, MeetingDocument] = {}
        self._segment_counts: dict[str, int] = {}
        self._db_ensured = False

    # ------------------------------------------------------------------
    # Leapable call helper -- enforces fail-loud success semantics
    # ------------------------------------------------------------------

    async def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a Leapable tool and return its ``data`` payload.

        Leapable tools return ``{"success": bool, "data": {...}, "error": ...}``.
        This wrapper raises if ``success`` is not truthy so failures never pass
        silently.

        Args:
            tool: Leapable tool name.
            args: Tool arguments.

        Returns:
            The ``data`` sub-object (or the whole envelope if it has no
            ``data`` key).

        Raises:
            MeetingTranscriptStoreError: If the call fails or success is false.
        """
        envelope = await self._client.call_tool(tool, args)
        if isinstance(envelope, dict) and "success" in envelope:
            if not envelope.get("success"):
                raise MeetingTranscriptStoreError(
                    f"Leapable tool '{tool}' failed: "
                    f"{envelope.get('error') or str(envelope)[:500]}"
                )
            data = envelope.get("data")
            return data if isinstance(data, dict) else envelope
        return envelope

    async def _ensure_db(self) -> None:
        """Create and select the 'meetings' Vault in Leapable.

        Called once on first operation. Idempotent -- if the Vault already
        exists, just selects it.

        Raises:
            MeetingTranscriptStoreError: If Vault creation or selection fails.
        """
        if self._db_ensured:
            return
        try:
            await self._call(
                "leapable_db_select",
                {"database_name": self._config.database_name},
            )
            self._db_ensured = True
            return
        except MeetingTranscriptStoreError:
            # Vault does not exist yet -- create it, then select it.
            pass
        await self._call(
            "leapable_db_create",
            {
                "name": self._config.database_name,
                "description": "Clone meeting transcripts -- auto-managed by voiceagent",
            },
        )
        await self._call(
            "leapable_db_select",
            {"database_name": self._config.database_name},
        )
        self._db_ensured = True

    # ------------------------------------------------------------------
    # In-memory meeting lifecycle
    # ------------------------------------------------------------------

    def _get_meeting(self, meeting_id: str) -> MeetingDocument:
        """Get an active meeting document by ID.

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
        logger.info("Meeting created: %s (clones=%s)", meeting_id, clone_names)
        return meeting_id

    def append_segment(self, meeting_id: str, segment: MeetingSegment) -> None:
        """Append a transcript segment to the in-memory buffer.

        Tracks participant names from non-clone speakers and caps in-memory
        segments at _MAX_IN_MEMORY_SEGMENTS to prevent unbounded growth in long
        meetings (older segments are flushed to disk before being dropped).

        Raises:
            MeetingTranscriptStoreError: If meeting_id is not active.
        """
        doc = self._get_meeting(meeting_id)
        doc.segments.append(segment)
        self._segment_counts[meeting_id] = (
            self._segment_counts.get(meeting_id, 0) + 1
        )
        if (
            segment.speaker_name
            and not segment.is_clone
            and segment.speaker_name not in doc.participant_names
        ):
            doc.participant_names.append(segment.speaker_name)

        if len(doc.segments) > _MAX_IN_MEMORY_SEGMENTS:
            self.flush(meeting_id)
            trim = len(doc.segments) - _MAX_IN_MEMORY_SEGMENTS
            del doc.segments[:trim]
            logger.debug(
                "Trimmed %d old segments from memory for %s", trim, meeting_id,
            )

    def record_interaction(
        self, meeting_id: str, interaction: CloneInteraction,
    ) -> None:
        """Record a clone Q&A interaction.

        Raises:
            MeetingTranscriptStoreError: If meeting_id is not active.
        """
        doc = self._get_meeting(meeting_id)
        doc.interactions.append(interaction)

    def should_flush(self, meeting_id: str) -> bool:
        """Return True if buffered segments >= flush_interval_segments."""
        count = self._segment_counts.get(meeting_id, 0)
        return count >= self._config.flush_interval_segments

    def flush(self, meeting_id: str) -> Path:
        """Write the current transcript state to a Markdown file on disk.

        This is for crash safety during the meeting. The file is deleted after
        a successful ingest into Leapable on end_meeting().

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
        logger.debug("Flushed %s (%d segments)", meeting_id, len(doc.segments))
        return path

    # ------------------------------------------------------------------
    # Leapable ingestion
    # ------------------------------------------------------------------

    async def _ingest_markdown(self, name: str, markdown: str) -> dict[str, Any]:
        """Ingest Markdown text into the current Vault via inline base64.

        Args:
            name: Source file name to record in Leapable (e.g. "mtg_x.md").
            markdown: The Markdown transcript content.

        Returns:
            The ingest ``data`` payload.

        Raises:
            MeetingTranscriptStoreError: If ingest reports any failure.
        """
        content_b64 = base64.b64encode(markdown.encode("utf-8")).decode("ascii")
        data = await self._call(
            "leapable_ingest_files",
            {
                "files": [{"name": name, "content_base64": content_b64}],
                "auto_process": True,
                "disable_image_extraction": True,
            },
        )
        # Fail loud on any per-file error counter.
        for counter in (
            "files_errored",
            "files_ingest_errored",
            "files_process_failed",
        ):
            if data.get(counter):
                raise MeetingTranscriptStoreError(
                    f"Leapable ingest of '{name}' reported {counter}="
                    f"{data.get(counter)}: {str(data)[:500]}"
                )
        return data

    async def end_meeting(
        self,
        meeting_id: str,
        summary: str = "",
        tags: list[str] | None = None,
    ) -> str:
        """End the meeting: finalize Markdown, ingest into Leapable, clean up.

        Auto-generates a title if not set, ingests the final transcript into
        Leapable (inline base64), applies tags, then deletes the local
        crash-safety file. Leapable becomes the single source of truth.

        Returns:
            The Leapable document_id for the ingested transcript.

        Raises:
            MeetingTranscriptStoreError: If meeting_id is not active or ingest
                fails.
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
        # Write the crash-safety file (also the recovery artifact on failure).
        path = self._transcript_dir / f"{meeting_id}.md"
        path.write_text(md, encoding="utf-8")

        await self._ensure_db()
        result = await self._ingest_markdown(f"{meeting_id}.md", md)
        doc_id = _extract_document_id(result, meeting_id)

        if self._config.auto_tag and doc.tags:
            await self._apply_tags(doc_id, doc.tags)

        # Ingest succeeded -- the crash-safety file is no longer needed.
        path.unlink(missing_ok=True)

        segment_count = len(doc.segments)
        interaction_count = len(doc.interactions)
        del self._active_meetings[meeting_id]
        self._segment_counts.pop(meeting_id, None)
        del doc
        gc.collect()

        logger.info(
            "Meeting ended: %s -> Leapable doc %s (%d segments, %d interactions)",
            meeting_id, doc_id, segment_count, interaction_count,
        )
        return doc_id

    async def _apply_tags(self, doc_id: str, tags: list[str]) -> None:
        """Create (idempotently) and apply tags to a Leapable document."""
        for tag in tags:
            try:
                await self._call("leapable_tag_create", {"name": tag})
            except MeetingTranscriptStoreError:
                # Tag already exists -- creation is idempotent by intent.
                logger.debug("Tag '%s' already exists; reusing", tag)
            await self._call(
                "leapable_tag_apply",
                {
                    "tag_name": tag,
                    "entity_type": "document",
                    "entity_id": doc_id,
                },
            )

    async def ingest_partial(self, meeting_id: str) -> str | None:
        """Ingest the current transcript state into Leapable for live search.

        Enables real-time search of an ongoing meeting. Best-effort: returns
        None (and logs) on any failure so a transient Leapable hiccup never
        crashes the live meeting loop.

        Returns:
            Leapable document_id if successful, else None.
        """
        doc = self._active_meetings.get(meeting_id)
        if doc is None or not doc.segments:
            return None
        try:
            await self._ensure_db()
            md = build_partial_transcript(doc)
            result = await self._ingest_markdown(f"{meeting_id}_live.md", md)
            doc_id = _extract_document_id(result, meeting_id)
            logger.debug(
                "Live transcript ingested: %s -> %s (%d segments)",
                meeting_id, doc_id, len(doc.segments),
            )
            return doc_id
        except Exception as exc:  # noqa: BLE001 -- best-effort live ingest
            logger.warning("Live transcript ingest failed for %s: %s", meeting_id, exc)
            return None

    async def close(self) -> None:
        """Close the Leapable MCP client and release all connections."""
        await self._client.close()


def _extract_document_id(result: object, meeting_id: str) -> str:
    """Extract the document_id from a Leapable ingest ``data`` payload.

    Leapable returns ``data.items[0].document_id`` for ingested sources.

    Raises:
        MeetingTranscriptStoreError: If no document_id can be extracted.
    """
    doc_id = ""
    if isinstance(result, dict):
        items = result.get("items", [])
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                doc_id = first.get("document_id", "") or first.get("id", "")
    if not doc_id:
        raise MeetingTranscriptStoreError(
            f"Leapable ingest returned no document_id for {meeting_id}. "
            f"Result: {str(result)[:500]}"
        )
    return doc_id
