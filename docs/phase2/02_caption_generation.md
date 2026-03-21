# Caption Generation

## 1. Overview

Captions are burned directly into the rendered video as a visual overlay, not delivered as separate subtitle files (`.srt`, `.vtt`). This guarantees that every viewer sees captions regardless of platform player support or user settings, which is critical for social media platforms where the majority of content is consumed with audio muted.

Word-level timestamps from WhisperX forced alignment (stored in the `transcript_words` table) provide 20-50ms precision per word. This precision enables word-by-word highlight effects and tight synchronization between spoken audio and displayed text.

Three rendering methods are supported:

| Method | Richness | Dependencies | Phase |
|--------|----------|-------------- |-------|
| ASS subtitles | Richest (fonts, colors, animations, borders, shadows, karaoke tags) | FFmpeg `subtitles` filter + libass | Phase 2 |
| FFmpeg drawtext | Simplest (text overlay with timed enable) | FFmpeg `drawtext` filter only | Phase 2 |
| PyCairo frame compositing | Full programmatic control (gradients, custom shapes, per-pixel effects) | PyCairo, Pillow | Phase 3 |

Captions are a primary engagement driver. Industry data shows that captioned short-form videos see 40-80% higher watch time on TikTok and Instagram. Facebook autoplays video muted, making burned-in captions essential for any engagement at all.

## 2. Caption Styles

ClipCannon ships four built-in caption styles. Each style is defined as a `CaptionStyle` Pydantic model and maps to both an ASS style definition and an equivalent drawtext filter configuration. Users can override any parameter via the EDL's `caption_options` block.

### 2.1 bold_centered

Large bold white text centered vertically (at roughly 70-80% of frame height) with a black stroke outline. Words appear 2-3 at a time. The currently spoken word is highlighted in a configurable accent color (default: yellow `#FFFF00`).

- **Font**: Montserrat Bold
- **Font size**: 48px (scaled to output resolution)
- **Text color**: White (`#FFFFFF`)
- **Highlight color**: Yellow (`#FFFF00`)
- **Stroke**: 3px black (`#000000`) outline
- **Shadow**: 2px drop shadow, 50% opacity black
- **Position**: Centered horizontally, 75% down from top
- **Words per chunk**: 2-3
- **Best for**: TikTok, Instagram Reels

This is the default style for all short-form vertical renders.

### 2.2 word_highlight

Each word highlights individually as it is spoken (karaoke-style timing). The full chunk of words is displayed, but only the currently active word uses the highlight color. Inactive words appear dimmed (50% opacity white or gray).

- **Font**: Montserrat Bold
- **Font size**: 44px
- **Text color (inactive)**: Gray (`#999999`)
- **Text color (active)**: White (`#FFFFFF`) with yellow glow
- **Stroke**: 2px black outline
- **Position**: Centered horizontally, 75% down from top
- **Words per chunk**: 3-5 (wider window so the viewer can read ahead)
- **Best for**: Short-form vertical content where engagement metrics are top priority

ASS implementation uses `\k` (karaoke) timing tags to transition each word. Drawtext fallback uses per-word filter chains with overlapping enable windows.

### 2.3 subtitle_bar

Traditional subtitle bar at the bottom of the frame with a semi-transparent dark background rectangle. Full sentences are displayed, timed to segment boundaries rather than individual words.

- **Font**: Inter Regular
- **Font size**: 32px
- **Text color**: White (`#FFFFFF`)
- **Background**: Semi-transparent black rectangle (`#000000` at 70% opacity), 8px padding
- **Position**: Bottom of frame, 10% margin from bottom edge
- **Words per chunk**: Full sentence (up to 12 words), line-wrapped at ~35 characters
- **Best for**: YouTube, LinkedIn, longer horizontal content

This style prioritizes readability and unobtrusiveness over engagement pop.

### 2.4 karaoke

The full sentence is visible at all times. The current word progressively changes color from left to right as it is spoken, creating a smooth "bouncing ball" karaoke effect.

- **Font**: Montserrat Bold
- **Font size**: 40px
- **Text color (unspoken)**: White (`#FFFFFF`) at 60% opacity
- **Text color (spoken)**: Accent color (configurable, default bright cyan `#00FFFF`)
- **Stroke**: 2px black outline on all words
- **Position**: Centered horizontally, 70% down from top
- **Words per chunk**: Full sentence
- **Transition**: Smooth color wipe across each word proportional to word duration
- **Best for**: Music-heavy content, lyric videos, podcast highlights with strong audio

ASS implementation uses `\kf` (smooth karaoke fill) tags. Drawtext fallback approximates this with rapid per-frame color interpolation (computationally expensive; ASS is strongly preferred for this style).

## 3. Caption Chunking Algorithm

The chunking algorithm converts the flat array of `transcript_words` into display-ready caption chunks with proper timing, line breaks, and word grouping.

### 3.1 Input

An ordered array of word records from `transcript_words`:

```python
@dataclass
class WordInput:
    word_id: int
    word: str
    start_ms: int
    end_ms: int
    confidence: float
    segment_id: int
```

### 3.2 Chunking Rules

The algorithm applies the following rules in priority order:

1. **Maximum words per chunk**: Default 3 (configurable via `max_words_per_chunk`). The chunk closes when this limit is reached.
2. **Punctuation boundary**: A chunk closes immediately after any word ending in `.`, `?`, `!`, `;`, or `:`. A comma (`,`) closes the chunk only if the chunk already has 2+ words.
3. **Minimum display duration**: 500ms. If a chunk's natural duration (`last_word.end_ms - first_word.start_ms`) is less than 500ms, the chunk's `end_ms` is extended to `start_ms + 500`.
4. **Maximum display duration**: 3000ms. If a chunk exceeds this, it is force-split at the nearest word boundary.
5. **No mid-word breaks**: Chunks always begin and end at word boundaries.
6. **Inter-chunk gap**: If the gap between the end of one chunk and the start of the next exceeds 200ms, the previous chunk's `end_ms` is not extended (a "no caption" gap appears). If the gap is less than 200ms, the previous chunk holds until the next chunk starts.
7. **Fast speech handling**: When speech rate exceeds 200 WPM (words per minute), `max_words_per_chunk` is dynamically increased to 4-5 to prevent captions from flashing too rapidly.
8. **Slow speech handling**: When speech rate drops below 80 WPM, the chunk holds its display (the `end_ms` is extended toward the next chunk's `start_ms`) so captions do not disappear and reappear with distracting frequency.

### 3.3 Speech Rate Calculation

Speech rate is computed per segment (not globally) using a sliding window:

```
segment_word_count = count of words in transcript_segments row
segment_duration_min = (end_ms - start_ms) / 60000
wpm = segment_word_count / segment_duration_min
```

The rate determines adaptive chunk sizing for that segment's words.

### 3.4 Profanity Handling

Words flagged in the `profanity_events` table are replaced with `[BLEEP]` in the caption text. The original word timing is preserved. The `[BLEEP]` text uses a distinct style (red text or a censor bar, depending on the caption style).

### 3.5 Algorithm Pseudocode

```
function chunk_transcript_words(words, max_words=3, min_display_ms=500, max_display_ms=3000):
    chunks = []
    current_chunk_words = []

    for each word in words:
        current_chunk_words.append(word)

        should_break = false
        if len(current_chunk_words) >= effective_max_words(segment_wpm):
            should_break = true
        if word.text ends with sentence-ending punctuation:
            should_break = true
        if word.text ends with comma and len(current_chunk_words) >= 2:
            should_break = true

        if should_break:
            chunk = make_chunk(current_chunk_words, min_display_ms)
            chunks.append(chunk)
            current_chunk_words = []

    if current_chunk_words:
        chunks.append(make_chunk(current_chunk_words, min_display_ms))

    apply_max_duration_splits(chunks, max_display_ms)
    apply_gap_handling(chunks)

    return chunks
```

## 4. ASS Subtitle Format

Advanced SubStation Alpha (ASS / `.ass`) is the primary caption rendering format. It provides the richest styling control and is natively supported by FFmpeg's `subtitles` filter via libass.

### 4.1 File Structure

Every generated `.ass` file follows this structure:

```
[Script Info]
Title: ClipCannon Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BoldCentered,Montserrat Bold,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,2,10,10,400,1
Style: BoldCenteredHighlight,Montserrat Bold,48,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,2,10,10,400,1
Style: SubtitleBar,Inter,32,&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,0,0,0,0,100,100,0,0,3,0,0,2,20,20,50,1
Style: Karaoke,Montserrat Bold,40,&H99FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,0,2,10,10,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
```

### 4.2 Color Format

ASS uses `&HAABBGGRR` color format (alpha, blue, green, red -- note: reversed from typical RGB):

| Color | ASS Code |
|-------|----------|
| White | `&H00FFFFFF` |
| Yellow | `&H0000FFFF` |
| Black | `&H00000000` |
| 50% transparent black | `&H80000000` |
| 70% transparent black | `&HB4000000` |
| Cyan | `&H00FFFF00` |

### 4.3 Dialogue Line Generation

For `bold_centered` style with word highlight, each chunk generates a dialogue line where the active word uses an inline override:

```
Dialogue: 0,0:00:02.34,0:00:03.12,BoldCentered,,0,0,0,,This {\c&H0000FFFF&}is{\c&H00FFFFFF&} amazing
```

For `karaoke` style, the `\kf` tag provides smooth fill timing:

```
Dialogue: 0,0:00:02.34,0:00:05.67,Karaoke,,0,0,0,,{\kf78}This {\kf45}is {\kf112}an {\kf89}amazing {\kf67}moment
```

The `\kf` values are in centiseconds (hundredths of a second) and represent the duration of each word.

### 4.4 Resolution Scaling

ASS `PlayResX` and `PlayResY` are set to match the output resolution. Font sizes in the style definitions are specified for 1080x1920 (vertical 9:16). When rendering to other resolutions, font sizes scale proportionally because `ScaledBorderAndShadow` is enabled.

| Output | PlayResX | PlayResY | Font Scale Factor |
|--------|----------|----------|-------------------|
| 1080x1920 (9:16) | 1080 | 1920 | 1.0x |
| 1920x1080 (16:9) | 1920 | 1080 | 0.75x |
| 1080x1080 (1:1) | 1080 | 1080 | 0.85x |
| 720x1280 (9:16) | 720 | 1280 | 0.67x |

### 4.5 Font Embedding

The `Montserrat` and `Inter` font families are bundled with ClipCannon under their SIL Open Font License. Font files are stored at `src/clipcannon/assets/fonts/` and the FFmpeg `subtitles` filter is invoked with the `fontsdir` option:

```
subtitles=filename='captions.ass':fontsdir='/path/to/assets/fonts'
```

## 5. FFmpeg drawtext Fallback

For environments where libass is unavailable or when simpler captions are acceptable, ClipCannon generates FFmpeg `drawtext` filter chains.

### 5.1 Single Chunk Filter

A single chunk generates one drawtext filter:

```
drawtext=text='This is amazing':fontfile=/path/to/Montserrat-Bold.ttf:fontsize=48:fontcolor=white:borderw=3:bordercolor=black:x=(w-tw)/2:y=h*0.75:enable='between(t,2.34,3.12)'
```

### 5.2 Word Highlight with drawtext

Word-by-word highlight requires multiple overlapping drawtext filters per chunk. The inactive words are drawn first, then the active word is drawn on top with the highlight color:

```
# Base layer: all words in white
drawtext=text='This is amazing':fontfile=...:fontcolor=white:...

# Highlight layer: 'This' highlighted during 2.34-2.67
drawtext=text='This':fontfile=...:fontcolor=yellow:x=<calculated_x>:y=h*0.75:enable='between(t,2.34,2.67)'

# Highlight layer: 'is' highlighted during 2.67-2.89
drawtext=text='is':fontfile=...:fontcolor=yellow:x=<calculated_x>:y=h*0.75:enable='between(t,2.67,2.89)'

# Highlight layer: 'amazing' highlighted during 2.89-3.12
drawtext=text='amazing':fontfile=...:fontcolor=yellow:x=<calculated_x>:y=h*0.75:enable='between(t,2.89,3.12)'
```

The x-position for each highlighted word is calculated by measuring the preceding text width. This is approximate (monospace assumption or pre-calculated glyph widths) and is one reason ASS is preferred.

### 5.3 Filter Chain Assembly

Multiple drawtext filters are chained using FFmpeg's filtergraph syntax:

```
[0:v]drawtext=...,drawtext=...,drawtext=...[v_captions]
```

For clips with many chunks, the filter chain can become very long. The generator writes the filter graph to a file and uses `-filter_complex_script`:

```
ffmpeg -i input.mp4 -filter_complex_script captions_filter.txt -map "[v_captions]" -map 0:a output.mp4
```

### 5.4 Limitations vs ASS

| Feature | ASS | drawtext |
|---------|-----|----------|
| Karaoke fill (`\kf`) | Native | Approximated (per-word, not smooth fill) |
| Background rectangle | Native (`BorderStyle=3`) | Requires separate `drawbox` filter |
| Shadow | Native | `shadowcolor` + `shadowx`/`shadowy` |
| Font fallback | Automatic via fontconfig | Must specify exact font file |
| Animation (fade, move) | `\fad`, `\move` tags | Not supported |
| Performance (many chunks) | Single filter, fast | Many filters, slower |

## 6. Caption Alignment with Edits

When a rendered clip is composed of multiple segments from different parts of the source video (as defined in the EDL), captions must be re-aligned from source timeline positions to output timeline positions.

### 6.1 The Problem

An EDL might define a clip like:

```json
{
  "segments": [
    {"source_start_ms": 120000, "source_end_ms": 135000, "output_start_ms": 0},
    {"source_start_ms": 300000, "source_end_ms": 312000, "output_start_ms": 15000}
  ]
}
```

The first segment pulls 15 seconds from 2:00-2:15 in the source. The second pulls 12 seconds from 5:00-5:12. In the output, these are concatenated: segment 1 occupies 0-15s, segment 2 occupies 15-27s.

Caption words at source position 305000ms (5:05 in source) must appear at output position 20000ms (0:20 in output).

### 6.2 Re-alignment Algorithm

```
function align_captions_to_edit(edit_segments, project_db_path):
    aligned_chunks = []

    for each segment in edit_segments:
        # Query transcript_words for this source range
        words = db.query(
            "SELECT * FROM transcript_words WHERE start_ms >= ? AND end_ms <= ? ORDER BY start_ms",
            segment.source_start_ms, segment.source_end_ms
        )

        # Compute time offset: how much to shift word timestamps
        offset = segment.output_start_ms - segment.source_start_ms

        # Shift all word timestamps
        shifted_words = [
            word._replace(
                start_ms=word.start_ms + offset,
                end_ms=word.end_ms + offset
            )
            for word in words
        ]

        # Run chunking on the shifted words
        chunks = chunk_transcript_words(shifted_words)
        aligned_chunks.extend(chunks)

    # Sort by output start_ms (should already be sorted if segments are ordered)
    aligned_chunks.sort(key=lambda c: c.start_ms)

    return aligned_chunks
```

### 6.3 Cross-Segment Boundary Handling

If a segment boundary falls mid-sentence (which is common when the EDL is auto-generated from highlights), the caption chunking algorithm naturally handles this because it operates on the per-segment word list. No chunk will span across two edit segments.

If the user wants a visual transition at the segment boundary (e.g., a fade), the caption generator inserts a 200ms gap at the boundary to prevent text from appearing during the transition effect.

## 7. Platform-Specific Caption Behavior

Caption rendering adapts to the target platform's conventions. The platform is specified in the EDL or render profile.

| Platform | Default Style | Font Size | Position (Y%) | Max Line Width | Notes |
|----------|--------------|-----------|----------------|----------------|-------|
| TikTok | `bold_centered` | 48px | 75% | 80% of frame width | Large, bold, unmissable. Avoid bottom 15% (platform UI). |
| Instagram Reels | `bold_centered` | 44px | 75% | 80% of frame width | Similar to TikTok. Avoid bottom 20% (username overlay). |
| YouTube | `subtitle_bar` | 32px | 90% | 90% of frame width | Traditional, less intrusive. Player controls overlap bottom 5%. |
| Facebook | `bold_centered` | 40px | 70% | 75% of frame width | Autoplay muted -- captions essential for initial engagement. |
| LinkedIn | `subtitle_bar` | 28px | 90% | 85% of frame width | Professional, understated. Smaller font to match business tone. |

### 7.1 Safe Zone Margins

Each platform has a "safe zone" where captions should not appear because the platform's own UI elements (usernames, like buttons, progress bars) overlay the video:

| Platform | Top Unsafe | Bottom Unsafe | Left/Right Unsafe |
|----------|-----------|---------------|-------------------|
| TikTok | 10% | 15% | 5% |
| Instagram Reels | 15% | 20% | 5% |
| YouTube | 0% | 8% | 0% |
| Facebook | 5% | 10% | 5% |
| LinkedIn | 0% | 5% | 0% |

The caption generator clamps the vertical position to stay within the safe zone. If the user-specified position would place text in an unsafe zone, it is adjusted inward with a warning logged.

## 8. Implementation Details

### 8.1 Module Location

```
src/clipcannon/editing/captions.py
```

This module is part of the `editing` package alongside `edl.py`, `smart_crop.py`, and `metadata_gen.py`.

### 8.2 Data Models

```python
from pydantic import BaseModel, Field
from enum import Enum
from pathlib import Path


class CaptionStyleName(str, Enum):
    BOLD_CENTERED = "bold_centered"
    WORD_HIGHLIGHT = "word_highlight"
    SUBTITLE_BAR = "subtitle_bar"
    KARAOKE = "karaoke"


class CaptionWord(BaseModel):
    """A single word with timing from transcript_words."""
    word: str
    start_ms: int
    end_ms: int
    confidence: float = 1.0
    is_active: bool = False  # Used during highlight rendering


class CaptionChunk(BaseModel):
    """A group of words displayed together as one caption frame."""
    text: str
    start_ms: int
    end_ms: int
    words: list[CaptionWord]
    highlight_word_index: int | None = None  # Index of the currently highlighted word


class CaptionStyle(BaseModel):
    """Full style definition for caption rendering."""
    name: CaptionStyleName
    font_name: str = "Montserrat Bold"
    font_size: int = 48
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFFF00"
    outline_color: str = "#000000"
    outline_width: int = 3
    shadow_offset: int = 2
    shadow_opacity: float = 0.5
    background_color: str | None = None  # For subtitle_bar style
    background_opacity: float = 0.7
    position_x_percent: float = 50.0  # Horizontal center
    position_y_percent: float = 75.0  # 75% down from top
    max_line_width_percent: float = 80.0
    max_words_per_chunk: int = 3
    min_display_ms: int = 500
    max_display_ms: int = 3000


class CaptionConfig(BaseModel):
    """Top-level caption configuration, embedded in the EDL."""
    enabled: bool = True
    style: CaptionStyleName = CaptionStyleName.BOLD_CENTERED
    style_overrides: dict = Field(default_factory=dict)
    profanity_replacement: str = "[BLEEP]"
    language: str = "en"
```

### 8.3 Public Functions

```python
def chunk_transcript_words(
    words: list[CaptionWord],
    max_words_per_chunk: int = 3,
    min_display_ms: int = 500,
    max_display_ms: int = 3000,
) -> list[CaptionChunk]:
    """
    Convert a flat list of timed words into display-ready caption chunks.

    Applies chunking rules: max words, punctuation breaks, min/max duration,
    speech rate adaptation, and gap handling.

    Args:
        words: Ordered list of CaptionWord from transcript_words table.
        max_words_per_chunk: Maximum words per displayed chunk.
        min_display_ms: Minimum time a chunk stays on screen.
        max_display_ms: Maximum time before force-splitting a chunk.

    Returns:
        Ordered list of CaptionChunk ready for rendering.
    """
    ...


def generate_ass_file(
    chunks: list[CaptionChunk],
    style: CaptionStyle,
    output_path: Path,
    resolution: tuple[int, int] = (1080, 1920),
) -> Path:
    """
    Generate an ASS subtitle file from caption chunks.

    Creates a complete .ass file with script info, style definitions,
    and timed dialogue lines. Supports word-level highlight and karaoke
    effects via inline override tags.

    Args:
        chunks: Caption chunks from chunk_transcript_words().
        style: The CaptionStyle to apply.
        output_path: Where to write the .ass file.
        resolution: Output video resolution (width, height).

    Returns:
        Path to the generated .ass file.
    """
    ...


def generate_drawtext_filters(
    chunks: list[CaptionChunk],
    style: CaptionStyle,
    font_path: Path | None = None,
) -> list[str]:
    """
    Generate FFmpeg drawtext filter strings from caption chunks.

    Each chunk produces one or more drawtext filter expressions.
    For highlight styles, multiple overlapping filters are generated
    (base layer + per-word highlight layer).

    Args:
        chunks: Caption chunks from chunk_transcript_words().
        style: The CaptionStyle to apply.
        font_path: Path to the .ttf font file. Defaults to bundled Montserrat.

    Returns:
        List of drawtext filter strings, ready to join with commas
        for a filtergraph.
    """
    ...


def align_captions_to_edit(
    edit_segments: list[dict],
    project_db_path: Path,
    caption_config: CaptionConfig | None = None,
) -> list[CaptionChunk]:
    """
    Query transcript_words for each edit segment's source range,
    re-map timestamps to the output timeline, and chunk.

    This is the main entry point called by the rendering pipeline.

    Args:
        edit_segments: List of segment dicts from the EDL, each with
            source_start_ms, source_end_ms, and output_start_ms.
        project_db_path: Path to the project's SQLite database.
        caption_config: Optional caption configuration. Uses defaults
            if not provided.

    Returns:
        List of CaptionChunk aligned to the output timeline.
    """
    ...
```

### 8.4 Integration with Rendering Pipeline

The rendering pipeline calls captions as follows:

```
1. Renderer receives EDL with caption_config
2. Renderer calls align_captions_to_edit() to get chunks
3. If ASS is available (check for libass):
     a. Call generate_ass_file() to write .ass to temp dir
     b. Add subtitles filter to FFmpeg filter graph:
        subtitles=filename='captions.ass':fontsdir='...'
4. Else (drawtext fallback):
     a. Call generate_drawtext_filters() to get filter strings
     b. Append drawtext filters to FFmpeg filter graph
5. Render proceeds with the combined filter graph
```

### 8.5 Performance Considerations

- **ASS rendering** is handled by libass inside FFmpeg and is highly optimized. A 60-second clip with 40 caption chunks adds negligible render time (< 0.5 seconds).
- **drawtext rendering** with word highlight can generate 100+ filter expressions for a 60-second clip. Writing the filter graph to a file (via `-filter_complex_script`) avoids shell argument length limits. Render time impact: ~1-2 seconds additional per minute of output.
- **Chunk computation** is pure Python and completes in < 10ms for a 10-minute source video.
- **Database queries** for `transcript_words` use the `idx_words_time` index on `(start_ms, end_ms)` for efficient range lookups.

## 9. Testing Strategy

### 9.1 Unit Tests

Location: `tests/test_captions.py`

**Chunking algorithm tests**:

| Test Case | Input | Expected Behavior |
|-----------|-------|-------------------|
| `test_basic_chunking` | 9 words, even timing | 3 chunks of 3 words each |
| `test_punctuation_break` | "Hello world. Goodbye." | Breaks at period: ["Hello world.", "Goodbye."] |
| `test_comma_break_threshold` | "One, two, three, four" | Comma breaks only after 2+ words in chunk |
| `test_min_display_duration` | 3 words in 200ms | Chunk end_ms extended to start_ms + 500 |
| `test_max_display_duration` | 10 words over 5 seconds | Force-split into multiple chunks |
| `test_fast_speech` | 250 WPM rate | Chunk size increases to 4-5 words |
| `test_slow_speech` | 60 WPM rate | Chunk holds display longer |
| `test_single_word` | 1 word | Single chunk with min_display_ms |
| `test_empty_input` | Empty list | Returns empty list, no crash |
| `test_profanity_replacement` | Word flagged as profanity | Text shows "[BLEEP]", timing preserved |

**ASS generation tests**:

| Test Case | Validates |
|-----------|-----------|
| `test_ass_file_structure` | Output has [Script Info], [V4+ Styles], [Events] sections |
| `test_ass_timing_format` | Times formatted as `H:MM:SS.cc` (centiseconds) |
| `test_ass_color_codes` | Colors in `&HAABBGGRR` format |
| `test_ass_bold_centered_style` | Style line matches expected parameters |
| `test_ass_karaoke_tags` | `\kf` tags present with correct centisecond values |
| `test_ass_resolution_scaling` | Font sizes scale for different PlayRes values |

**drawtext generation tests**:

| Test Case | Validates |
|-----------|-----------|
| `test_drawtext_basic` | Valid drawtext filter string with enable expression |
| `test_drawtext_centering` | `x=(w-tw)/2` expression present |
| `test_drawtext_timing` | `between(t,start,end)` with correct float seconds |
| `test_drawtext_highlight_layers` | Multiple filters generated for highlight style |
| `test_drawtext_special_chars` | Apostrophes, quotes properly escaped |

### 9.2 Integration Tests

Location: `tests/integration/test_caption_render.py`

- **test_render_with_ass_captions**: Render a 5-second test clip with ASS captions. Verify the output video has burned-in text by extracting frames at known timestamps and checking pixel regions are not blank.
- **test_render_with_drawtext_captions**: Same as above but forcing drawtext fallback.
- **test_multi_segment_alignment**: Create an EDL with 3 segments from different source positions. Verify captions appear at the correct output timestamps.
- **test_platform_style_selection**: Render the same clip for TikTok and YouTube. Verify different font sizes and positions are applied.

### 9.3 Edge Cases

| Edge Case | Expected Behavior |
|-----------|-------------------|
| Empty transcript (no words) | No captions rendered, no crash, warning logged |
| Single word transcript | One chunk with min display duration |
| Very fast speech (300+ WPM) | Chunk size expands, never shows <200ms per chunk |
| Very long word (>20 chars) | Word is never split; chunk may contain only 1 word |
| Overlapping word timestamps | Words sorted by start_ms; overlaps logged as warnings |
| Unicode/emoji in transcript | Passed through to ASS/drawtext; font must support glyphs |
| Profanity-only segment | All words replaced with [BLEEP]; timing preserved |
| Segment with zero words | Segment produces no chunks; adjacent segments unaffected |
| Confidence below threshold | Low-confidence words (< 0.3) shown with `[?]` suffix or dimmed style |

### 9.4 Acceptance Criteria

- Caption timing drift is less than 100ms from the spoken word (verified by manual spot-check on 5 test clips).
- All four caption styles render without errors on both ASS and drawtext paths.
- The chunking algorithm handles speech rates from 40 WPM to 300 WPM without visual artifacts (text flashing, overlapping chunks, or excessively long holds).
- Profanity replacement works correctly when `profanity_events` table has matching entries.
- Platform-specific safe zones are respected (no caption text hidden behind platform UI).
