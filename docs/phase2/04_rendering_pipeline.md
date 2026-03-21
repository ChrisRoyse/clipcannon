# Rendering Pipeline

## 1. Overview

The rendering engine takes an EDL (Edit Decision List) and produces a platform-ready video file. The pipeline follows a single-pass architecture to minimize generation loss and maximize throughput.

- EDL -> typed-ffmpeg filter graph -> FFmpeg execution -> output MP4
- Single-pass rendering: all segments concatenated in one FFmpeg command
- NVENC hardware encoding (H.264, H.265, AV1)
- Captions burned in via ASS subtitles filter or drawtext
- Crop applied via crop+scale filters
- Audio mixed externally (pydub), muxed in final FFmpeg pass
- Generation loss prevention: always render from original source, never from previous renders

## 2. typed-ffmpeg Integration

typed-ffmpeg v3.0 provides a Python API for building FFmpeg filter graphs with type safety. It validates filter parameters at build time (before FFmpeg runs), generates correct `filter_complex` syntax, and handles input/output stream mapping.

### Example: Simple segment extraction

```python
import typed_ffmpeg as ffmpeg

(
    ffmpeg.input("source.mp4", ss=14.0, to=15.0)
    .filter("crop", "ih*9/16", "ih", "(iw-ih*9/16)/2", "0")
    .filter("scale", 1080, 1920)
    .filter("subtitles", "captions.ass")
    .output("output.mp4", vcodec="h264_nvenc", preset="p4",
            b_v="8M", maxrate="10M", bufsize="20M",
            acodec="aac", b_a="192k", ar=44100,
            movflags="+faststart")
    .run()
)
```

### Key Benefits

- **Build-time validation**: Filter parameter types are checked before FFmpeg is invoked, catching errors early (e.g., passing a string where an integer is expected).
- **Correct filter_complex generation**: Multi-input, multi-output filter graphs with xfade transitions are constructed programmatically rather than via string concatenation.
- **Stream mapping**: Input and output streams are tracked as typed objects, preventing mismatched stream references.

### Multi-segment Example

```python
import typed_ffmpeg as ffmpeg

# Build a filter graph that trims and concatenates multiple segments
source = ffmpeg.input("source.mp4")

segments = []
for seg in edl.segments:
    trimmed = (
        source
        .filter("trim", start=seg.start_s, end=seg.end_s)
        .filter("setpts", "PTS-STARTPTS")
        .filter("crop", seg.crop_w, seg.crop_h, seg.crop_x, seg.crop_y)
        .filter("scale", profile.width, profile.height)
    )
    segments.append(trimmed)

# Concatenate all segments
concat = ffmpeg.concat(*segments, v=1, a=0)

# Apply captions and output
(
    concat
    .filter("subtitles", "captions.ass")
    .output("output.mp4", vcodec="h264_nvenc", preset="p4",
            b_v="8M", maxrate="10M", bufsize="20M")
    .run()
)
```

## 3. Rendering Pipeline Steps

```
EDL JSON
    |
    v
1. VALIDATE EDL
   |-- Verify source_sha256 matches project source
   |-- Validate segment time ranges within source duration
   |-- Validate platform profile compatibility
   +-- Check disk space for output

2. GENERATE CAPTIONS (if enabled)
   |-- Query transcript_words for each segment's time range
   |-- Re-align word timestamps to output timeline
   |-- Chunk words into caption groups
   +-- Generate .ass subtitle file

3. COMPUTE CROP (if needed)
   |-- Run face detection on key frames per segment
   |-- Calculate crop regions per scene
   |-- Smooth transitions between crop positions
   +-- Generate crop filter expressions

4. GENERATE AUDIO (if specified)
   |-- Generate background music (ACE-Step or MIDI)
   |-- Generate sound effects (DSP)
   |-- Extract source audio for segments
   |-- Apply ducking (reduce music under speech)
   |-- Mix all audio layers
   +-- Export final_mix.wav

5. BUILD FILTER GRAPH (typed-ffmpeg)
   |-- Input: source video (or CFR copy)
   |-- For each segment: trim to time range
   |-- Apply crop + scale
   |-- Apply transitions between segments (xfade)
   |-- Apply subtitle overlay
   |-- Chain all filters into filter_complex
   +-- Set output encoding parameters

6. EXECUTE RENDER (FFmpeg + NVENC)
   |-- Run FFmpeg with constructed command
   |-- Monitor progress (frame count / total)
   |-- Write output to renders/{render_id}/output.mp4
   +-- Generate thumbnail at specified timestamp

7. RECORD PROVENANCE
   |-- Hash output file (SHA-256)
   |-- Record render provenance (input hash, output hash, FFmpeg params)
   +-- Update edit status to "rendered"
```

### Step Details

#### Step 1: Validate EDL

Before any rendering work begins, the EDL is validated against the project state:

- **Source integrity**: The `source_sha256` field in the EDL is compared against the SHA-256 hash of the actual source file on disk. If they do not match, the render is rejected.
- **Time range bounds**: Each segment's `start_ms` and `end_ms` are checked against the source video duration obtained during ingest. Out-of-range segments cause a validation error.
- **Profile compatibility**: The requested platform profile is checked for compatibility with the source material (e.g., minimum resolution, duration limits).
- **Disk space**: The estimated output size (based on bitrate and duration) is compared against available disk space. A minimum 2x buffer is required.

#### Step 2: Generate Captions

Caption generation produces an ASS (Advanced SubStation Alpha) subtitle file that is burned into the video during the filter graph stage.

- Words are queried from the `transcript_words` table for each segment's source time range.
- Timestamps are re-mapped from source timeline to output timeline (accounting for segment ordering and transitions).
- Words are grouped into caption chunks of 3-5 words based on timing gaps and line length.
- The ASS file uses a configurable style (font, size, position, colors, animation).

#### Step 3: Compute Crop

For vertical (9:16) output from horizontal (16:9) source material, intelligent cropping is required:

- Face detection runs on sampled keyframes (every 1-2 seconds) within each segment.
- A crop region is calculated to keep detected faces centered.
- When no faces are detected, the crop defaults to center-frame.
- Crop positions are smoothed across adjacent keyframes to avoid jarring jumps (exponential moving average with configurable alpha).
- The crop filter expression is generated as typed-ffmpeg parameters.

#### Step 4: Generate Audio

Audio mixing is handled externally via pydub before the FFmpeg render:

- Source audio is extracted for each segment's time range using `pydub.AudioSegment.from_file()`.
- If background music is specified, it is generated or loaded and volume-adjusted.
- Ducking is applied: music volume is reduced by a configurable amount (default -12 dB) during speech segments detected via VAD (voice activity detection).
- All audio layers are mixed to a single `final_mix.wav` file.
- This file is muxed into the final output during the FFmpeg pass.

#### Step 5: Build Filter Graph

The typed-ffmpeg filter graph is the core of the rendering pipeline:

- A single `ffmpeg.input()` references the source video.
- Each segment produces a `trim` -> `setpts` -> `crop` -> `scale` filter chain.
- Segments are joined via `concat` (hard cut) or `xfade` (crossfade transition).
- The captions ASS file is applied via the `subtitles` filter.
- Output encoding parameters are set from the platform profile.

#### Step 6: Execute Render

FFmpeg is executed as a subprocess:

- The typed-ffmpeg graph is compiled to a command-line invocation.
- Progress is monitored by parsing FFmpeg's `progress` output (frame number, fps, bitrate).
- Progress percentage is calculated as `current_frame / total_frames * 100`.
- The output file is written to `renders/{render_id}/output.mp4`.
- On completion, a thumbnail is extracted.

#### Step 7: Record Provenance

Every render is recorded in the provenance system:

- The output file is hashed (SHA-256).
- A provenance record is created linking: source hash, EDL hash, output hash, FFmpeg command used, encoding parameters, render duration, and timestamp.
- The edit record's status is updated to `"rendered"`.
- The render record includes the exact FFmpeg command for reproducibility.

## 4. Platform Encoding Profiles

### tiktok_vertical

| Parameter | Value |
|-----------|-------|
| Resolution | 1080x1920 |
| Aspect | 9:16 |
| Codec | H.264 (h264_nvenc) |
| Preset | p4 |
| Bitrate | 8 Mbps |
| Max Bitrate | 10 Mbps |
| Buffer Size | 20 Mbps |
| FPS | 30 |
| Audio | AAC 192kbps 44.1kHz stereo |
| Max Duration | 60s |
| Max File Size | 72 MB (Android) |

### instagram_reels

| Parameter | Value |
|-----------|-------|
| Resolution | 1080x1920 |
| Aspect | 9:16 |
| Codec | H.264 (h264_nvenc) |
| Preset | p4 |
| Bitrate | 8 Mbps |
| Max Bitrate | 10 Mbps |
| Buffer Size | 20 Mbps |
| FPS | 30 |
| Audio | AAC 192kbps 44.1kHz stereo |
| Max Duration | 90s |
| Max File Size | 100 MB |

### youtube_standard

| Parameter | Value |
|-----------|-------|
| Resolution | 1920x1080 |
| Aspect | 16:9 |
| Codec | H.264 (h264_nvenc) |
| Preset | p4 |
| Bitrate | 12 Mbps |
| Max Bitrate | 15 Mbps |
| Buffer Size | 30 Mbps |
| FPS | 30 |
| Audio | AAC 256kbps 48kHz stereo |
| Max Duration | 600s (10 min for clips) |
| Max File Size | 256 MB |

### youtube_shorts

| Parameter | Value |
|-----------|-------|
| Resolution | 1080x1920 |
| Aspect | 9:16 |
| Codec | H.264 (h264_nvenc) |
| Preset | p4 |
| Bitrate | 8 Mbps |
| Max Bitrate | 10 Mbps |
| Buffer Size | 20 Mbps |
| FPS | 30 |
| Audio | AAC 192kbps 44.1kHz stereo |
| Max Duration | 60s |
| Max File Size | 72 MB |

### facebook_reels

| Parameter | Value |
|-----------|-------|
| Resolution | 1080x1920 |
| Aspect | 9:16 |
| Codec | H.264 (h264_nvenc) |
| Preset | p4 |
| Bitrate | 8 Mbps |
| Max Bitrate | 10 Mbps |
| Buffer Size | 20 Mbps |
| FPS | 30 |
| Audio | AAC 192kbps 44.1kHz stereo |
| Max Duration | 60s |
| Max File Size | 72 MB |

### linkedin_square

| Parameter | Value |
|-----------|-------|
| Resolution | 1080x1080 |
| Aspect | 1:1 |
| Codec | H.264 (h264_nvenc) |
| Preset | p4 |
| Bitrate | 6 Mbps |
| Max Bitrate | 8 Mbps |
| Buffer Size | 16 Mbps |
| FPS | 30 |
| Audio | AAC 192kbps 44.1kHz stereo |
| Max Duration | 180s (3 min) |
| Max File Size | 200 MB |

### linkedin_landscape

| Parameter | Value |
|-----------|-------|
| Resolution | 1920x1080 |
| Aspect | 16:9 |
| Codec | H.264 (h264_nvenc) |
| Preset | p4 |
| Bitrate | 8 Mbps |
| Max Bitrate | 10 Mbps |
| Buffer Size | 20 Mbps |
| FPS | 30 |
| Audio | AAC 192kbps 44.1kHz stereo |
| Max Duration | 600s (10 min) |
| Max File Size | 200 MB |

### Profile Data Model

```python
class EncodingProfile(BaseModel):
    name: str
    width: int
    height: int
    aspect: str                     # "9:16", "16:9", "1:1"
    codec: str                      # "h264_nvenc", "hevc_nvenc", "av1_nvenc"
    preset: str                     # "p1" (fastest) to "p7" (best quality)
    bitrate: str                    # e.g. "8M"
    max_bitrate: str                # e.g. "10M"
    buffer_size: str                # e.g. "20M"
    fps: int                        # 30 or 60
    audio_codec: str                # "aac"
    audio_bitrate: str              # "192k" or "256k"
    audio_sample_rate: int          # 44100 or 48000
    audio_channels: int             # 2 (stereo)
    max_duration_s: int             # platform limit in seconds
    max_file_size_mb: int | None    # platform limit in MB, None if no limit
    movflags: str                   # "+faststart" for streaming
```

## 5. Batch Rendering

The RTX 5090 has 3 independent NVENC encoding sessions available simultaneously. The `BatchRenderer` exploits this for parallel rendering.

### Architecture

```
BatchRenderer
    |
    |-- NVENC Session 0 --> Render edit_001 (tiktok_vertical)
    |-- NVENC Session 1 --> Render edit_002 (instagram_reels)
    +-- NVENC Session 2 --> Render edit_003 (youtube_shorts)
```

### Queue Management

- Renders are queued in FIFO order by default.
- Priority override: a render can be submitted with `priority="high"` to jump to the front of the queue.
- The queue is persisted to the database so renders survive process restarts.
- Maximum queue depth: 100 pending renders per project.

### Concurrency Control

- A semaphore limits concurrent renders to `max_nvenc_sessions` (default 3).
- Each render acquires a session before starting and releases it on completion or failure.
- If all sessions are occupied, the render waits in the queue.

### Progress Tracking

- Each render reports progress as a percentage (0-100).
- Batch progress is the average of individual render progress values.
- Status transitions: `queued` -> `rendering` -> `completed` | `failed`.

### Error Handling

- If a render fails, it is marked as `failed` with the error message and FFmpeg stderr.
- Failed renders do not block other renders in the batch.
- Retries are manual (user must re-submit).

### Batch Data Model

```python
class BatchStatus(BaseModel):
    batch_id: str
    total: int
    completed: int
    failed: int
    rendering: int
    queued: int
    progress_pct: float
    renders: list[RenderStatus]

class RenderStatus(BaseModel):
    render_id: str
    edit_id: str
    status: str                     # "queued", "rendering", "completed", "failed"
    progress_pct: float
    output_path: str | None
    file_size_bytes: int | None
    duration_ms: int | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
```

## 6. Thumbnail Generation

A thumbnail is generated for each rendered clip to serve as a preview image.

### Process

1. A timestamp is selected: either user-specified or auto-selected (first keyframe after 25% of clip duration).
2. FFmpeg extracts a single frame at that timestamp.
3. The same crop region used for the video is applied to the frame.
4. The frame is scaled to the output resolution.
5. The frame is encoded as JPEG at 95% quality.
6. The thumbnail is saved to `renders/{render_id}/thumbnail.jpg`.

### Implementation

```python
def generate_thumbnail(
    source_path: Path,
    timestamp_ms: int,
    crop_region: CropRegion | None,
    output_resolution: tuple[int, int],
    output_path: Path,
    quality: int = 95,
) -> Path:
    """Extract a single frame, apply crop, save as JPEG."""
    stream = ffmpeg.input(str(source_path), ss=timestamp_ms / 1000.0)
    if crop_region:
        stream = stream.filter(
            "crop",
            crop_region.w,
            crop_region.h,
            crop_region.x,
            crop_region.y,
        )
    stream = stream.filter("scale", output_resolution[0], output_resolution[1])
    stream.output(
        str(output_path),
        vframes=1,
        qmin=1,
        q_v=2,  # JPEG quality
    ).run()
    return output_path
```

### Auto-selection Heuristic

When no timestamp is provided, the thumbnail generator selects the "best" frame:

1. Sample 5 frames evenly across the clip duration.
2. Score each frame by sharpness (Laplacian variance) and brightness (mean pixel value).
3. Select the frame with the highest combined score.
4. This avoids selecting blurry or dark frames as thumbnails.

## 7. Generation Loss Prevention

Generation loss occurs when a previously rendered (lossy-compressed) file is used as input for another render. Each encode cycle degrades quality. The rendering pipeline enforces strict rules to prevent this.

### Rules

1. **Source-only inputs**: The renderer ONLY accepts the original ingested source file (or the CFR copy created during ingest) as input. The source path is resolved from the project database, not from user input.
2. **SHA-256 verification**: Before rendering, the source file's SHA-256 hash is computed and compared against the hash recorded during ingest. A mismatch aborts the render.
3. **Render directory blacklist**: The renderer refuses to open any file located under the `renders/` directory as a source input. This is enforced by path validation before FFmpeg is invoked.
4. **Single-pass concatenation**: Multi-segment clips are rendered in a single FFmpeg command using `filter_complex` with `trim` and `concat` filters. No intermediate files are created between segments.
5. **No re-encoding of renders**: If a user wants to change encoding parameters, the clip must be re-rendered from the original source, not from a previous render output.

### Validation Code

```python
def _verify_source(self, source_path: Path, expected_sha256: str) -> None:
    """Verify source file integrity before rendering."""
    # Reject any path under renders/
    renders_dir = self.project_dir / "renders"
    if renders_dir in source_path.parents or source_path.parent == renders_dir:
        raise RenderError(
            f"Refusing to use rendered output as source: {source_path}"
        )

    # Verify SHA-256
    actual_hash = compute_sha256(source_path)
    if actual_hash != expected_sha256:
        raise RenderError(
            f"Source integrity check failed. "
            f"Expected {expected_sha256}, got {actual_hash}"
        )
```

## 8. Implementation

### File: src/clipcannon/rendering/renderer.py

The main rendering engine.

```python
class VideoRenderer:
    """Renders an EDL to a platform-ready video file."""

    def __init__(self, project_dir: Path, db: Database):
        self.project_dir = project_dir
        self.db = db

    def render(self, edit: Edit, config: RenderConfig) -> RenderResult:
        """Execute the full rendering pipeline for a single edit."""
        # 1. Validate
        self._validate_edl(edit)
        self._verify_source(edit.source_path, edit.source_sha256)

        # 2. Generate captions
        captions_path = None
        if edit.captions_enabled:
            captions_path = self._generate_captions(edit)

        # 3. Compute crop
        crop_regions = None
        if edit.profile.aspect != edit.source_aspect:
            crop_regions = self._compute_crop(edit)

        # 4. Generate audio
        audio_path = None
        if edit.audio_config:
            audio_path = self._generate_audio(edit)

        # 5. Build filter graph
        graph = self._build_filter_graph(
            edit, captions_path, crop_regions, audio_path
        )

        # 6. Execute render
        render_id = generate_render_id()
        output_dir = self.project_dir / "renders" / render_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "output.mp4"

        self._execute_render(graph, output_path, config)

        # 7. Generate thumbnail
        thumb_path = output_dir / "thumbnail.jpg"
        generate_thumbnail(
            source_path=edit.source_path,
            timestamp_ms=edit.thumbnail_ts_ms or self._auto_select_thumb_ts(edit),
            crop_region=crop_regions[0] if crop_regions else None,
            output_resolution=(edit.profile.width, edit.profile.height),
            output_path=thumb_path,
        )

        # 8. Record provenance
        output_hash = compute_sha256(output_path)
        self._record_provenance(edit, render_id, output_path, output_hash)

        return RenderResult(
            render_id=render_id,
            output_path=output_path,
            thumbnail_path=thumb_path,
            file_size_bytes=output_path.stat().st_size,
            duration_ms=edit.total_duration_ms,
            output_sha256=output_hash,
        )

    def _build_filter_graph(
        self,
        edit: Edit,
        captions_path: Path | None,
        crop_regions: list[CropRegion] | None,
        audio_path: Path | None,
    ) -> ffmpeg.Stream:
        """Construct the typed-ffmpeg filter graph."""
        ...

    def _verify_source(self, source_path: Path, expected_sha256: str) -> None:
        """Verify source file integrity and reject render outputs."""
        ...

    def _execute_render(
        self,
        graph: ffmpeg.Stream,
        output_path: Path,
        config: RenderConfig,
    ) -> None:
        """Run FFmpeg and monitor progress."""
        ...

    def _record_provenance(
        self,
        edit: Edit,
        render_id: str,
        output_path: Path,
        output_sha256: str,
    ) -> None:
        """Record render provenance in the database."""
        ...
```

### File: src/clipcannon/rendering/profiles.py

Platform encoding profiles.

```python
PLATFORM_PROFILES: dict[str, EncodingProfile] = {
    "tiktok_vertical": EncodingProfile(
        name="tiktok_vertical",
        width=1080, height=1920, aspect="9:16",
        codec="h264_nvenc", preset="p4",
        bitrate="8M", max_bitrate="10M", buffer_size="20M",
        fps=30,
        audio_codec="aac", audio_bitrate="192k",
        audio_sample_rate=44100, audio_channels=2,
        max_duration_s=60, max_file_size_mb=72,
        movflags="+faststart",
    ),
    "instagram_reels": EncodingProfile(
        name="instagram_reels",
        width=1080, height=1920, aspect="9:16",
        codec="h264_nvenc", preset="p4",
        bitrate="8M", max_bitrate="10M", buffer_size="20M",
        fps=30,
        audio_codec="aac", audio_bitrate="192k",
        audio_sample_rate=44100, audio_channels=2,
        max_duration_s=90, max_file_size_mb=100,
        movflags="+faststart",
    ),
    "youtube_standard": EncodingProfile(
        name="youtube_standard",
        width=1920, height=1080, aspect="16:9",
        codec="h264_nvenc", preset="p4",
        bitrate="12M", max_bitrate="15M", buffer_size="30M",
        fps=30,
        audio_codec="aac", audio_bitrate="256k",
        audio_sample_rate=48000, audio_channels=2,
        max_duration_s=600, max_file_size_mb=256,
        movflags="+faststart",
    ),
    "youtube_shorts": EncodingProfile(
        name="youtube_shorts",
        width=1080, height=1920, aspect="9:16",
        codec="h264_nvenc", preset="p4",
        bitrate="8M", max_bitrate="10M", buffer_size="20M",
        fps=30,
        audio_codec="aac", audio_bitrate="192k",
        audio_sample_rate=44100, audio_channels=2,
        max_duration_s=60, max_file_size_mb=72,
        movflags="+faststart",
    ),
    "facebook_reels": EncodingProfile(
        name="facebook_reels",
        width=1080, height=1920, aspect="9:16",
        codec="h264_nvenc", preset="p4",
        bitrate="8M", max_bitrate="10M", buffer_size="20M",
        fps=30,
        audio_codec="aac", audio_bitrate="192k",
        audio_sample_rate=44100, audio_channels=2,
        max_duration_s=60, max_file_size_mb=72,
        movflags="+faststart",
    ),
    "linkedin_square": EncodingProfile(
        name="linkedin_square",
        width=1080, height=1080, aspect="1:1",
        codec="h264_nvenc", preset="p4",
        bitrate="6M", max_bitrate="8M", buffer_size="16M",
        fps=30,
        audio_codec="aac", audio_bitrate="192k",
        audio_sample_rate=44100, audio_channels=2,
        max_duration_s=180, max_file_size_mb=200,
        movflags="+faststart",
    ),
    "linkedin_landscape": EncodingProfile(
        name="linkedin_landscape",
        width=1920, height=1080, aspect="16:9",
        codec="h264_nvenc", preset="p4",
        bitrate="8M", max_bitrate="10M", buffer_size="20M",
        fps=30,
        audio_codec="aac", audio_bitrate="192k",
        audio_sample_rate=44100, audio_channels=2,
        max_duration_s=600, max_file_size_mb=200,
        movflags="+faststart",
    ),
}
```

### File: src/clipcannon/rendering/batch.py

Parallel NVENC session management.

```python
class BatchRenderer:
    """Manages parallel NVENC rendering sessions."""

    def __init__(
        self,
        renderer: VideoRenderer,
        max_sessions: int = 3,
    ):
        self.renderer = renderer
        self.max_sessions = max_sessions
        self._semaphore = asyncio.Semaphore(max_sessions)
        self._queue: asyncio.Queue[RenderJob] = asyncio.Queue(maxsize=100)

    async def submit(
        self,
        edits: list[Edit],
        config: RenderConfig,
        priority: str = "normal",
    ) -> str:
        """Submit a batch of edits for rendering. Returns batch_id."""
        batch_id = generate_batch_id()
        for edit in edits:
            job = RenderJob(
                batch_id=batch_id,
                edit=edit,
                config=config,
                priority=priority,
            )
            await self._queue.put(job)
        asyncio.create_task(self._process_batch(batch_id, len(edits)))
        return batch_id

    async def status(self, batch_id: str) -> BatchStatus:
        """Get the current status of a batch."""
        ...

    async def _process_batch(self, batch_id: str, count: int) -> None:
        """Process all jobs in a batch with concurrency control."""
        tasks = []
        for _ in range(count):
            job = await self._queue.get()
            task = asyncio.create_task(self._render_with_semaphore(job))
            tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _render_with_semaphore(self, job: RenderJob) -> RenderResult:
        """Acquire an NVENC session and render."""
        async with self._semaphore:
            return await asyncio.to_thread(
                self.renderer.render, job.edit, job.config
            )
```

### File: src/clipcannon/rendering/thumbnail.py

Thumbnail extraction and auto-selection.

```python
def generate_thumbnail(
    source_path: Path,
    timestamp_ms: int,
    crop_region: CropRegion | None,
    output_resolution: tuple[int, int],
    output_path: Path,
    quality: int = 95,
) -> Path:
    """Extract a single frame from the source, apply crop, save as JPEG."""
    ...

def auto_select_thumbnail_ts(
    source_path: Path,
    duration_ms: int,
    num_candidates: int = 5,
) -> int:
    """Select the best thumbnail timestamp by scoring candidate frames."""
    ...
```

## 9. MCP Tools

### clipcannon_render

Renders a single edit to the target platform format.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| project_id | string | yes | Project identifier |
| edit_id | string | yes | Edit to render |

**Returns:**

```json
{
  "render_id": "rnd_abc123",
  "output_path": "renders/rnd_abc123/output.mp4",
  "file_size_bytes": 15234567,
  "duration_ms": 45200,
  "output_sha256": "a1b2c3..."
}
```

### clipcannon_render_status

Check the status of a render.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| project_id | string | yes | Project identifier |
| render_id | string | yes | Render identifier |

**Returns:**

```json
{
  "render_id": "rnd_abc123",
  "status": "rendering",
  "progress_pct": 67.5,
  "output_path": null,
  "started_at": "2026-03-21T10:00:00Z"
}
```

### clipcannon_render_batch

Renders multiple edits in parallel using up to 3 NVENC sessions.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| project_id | string | yes | Project identifier |
| edit_ids | string[] | yes | List of edit IDs to render |

**Returns:**

```json
{
  "batch_id": "bat_xyz789",
  "render_ids": ["rnd_001", "rnd_002", "rnd_003"],
  "total": 3,
  "status": "rendering"
}
```

## 10. Testing Strategy

### Unit Tests

- **Filter graph construction**: Build filter graphs for various EDL configurations and validate the generated FFmpeg command string matches expected output. No actual FFmpeg execution.
- **Platform profile validation**: Verify all profiles have valid parameters (resolution divisible by 2, bitrate within codec limits, required fields present).
- **Caption generation**: Generate ASS files from transcript data and verify timing alignment, word grouping, and style formatting.
- **Crop calculation**: Provide mock face detection results and verify crop region computation, smoothing, and boundary clamping.
- **Source verification**: Test SHA-256 validation with matching and mismatching hashes. Test render directory rejection.

### Integration Tests

- **Single segment render**: Render a single segment from a test source file and verify:
  - Output file exists and is a valid MP4.
  - Output resolution matches the platform profile.
  - Output duration matches the segment time range (within 100ms tolerance).
  - Audio stream is present with correct sample rate and channels.
- **Multi-segment render**: Render 3 segments concatenated and verify total duration is the sum of segment durations.
- **Thumbnail generation**: Generate a thumbnail and verify it is a valid JPEG with correct dimensions.

### End-to-End Tests

- **Full pipeline**: Create an edit via MCP tool, render it, and verify:
  - The output plays correctly (probe with ffprobe).
  - Provenance is recorded in the database.
  - The render status transitions correctly (queued -> rendering -> completed).
- **Batch rendering**: Submit 3 edits for batch rendering and verify all complete successfully with correct provenance.

### Performance Tests

- **Single render throughput**: Measure render time for a 60-second clip at 1080x1920 with NVENC.
- **Batch concurrency**: Verify that 3 concurrent renders complete faster than 3 sequential renders.
- **NVENC session limits**: Verify that submitting more than 3 concurrent renders queues the excess rather than failing.
