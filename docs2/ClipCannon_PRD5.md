### 8.6 Disk Space Management

Problem: A 4-hour 4K video project can consume 80-120GB of disk space. Multiple projects can exhaust storage quickly. There is no cleanup strategy.

Solution: 3-tier file classification with lifecycle policies. Every file produced by the pipeline is classified as Sacred (never delete), Regenerable (can be recreated from sacred files), or Ephemeral (delete after use).


##### Tier 1 — Sacred (never auto-delete):


| File | Why Sacred |
|:---|:---|
| Original source video | Cannot be recreated |
| EDL JSON files | The AI's creative decisions (tiny files) |
| Project manifest + provenance.db | Audit trail (tiny files) |
| Final rendered output clips | Delivered product |


##### Tier 2 — Regenerable (delete when disk space needed, recreate from sacred files on demand):


| File | Recreated By |
|:---|:---|
| CFR-normalized source copy | Re-run VFR normalization on original |
| Audio stems (vocals.wav, music.wav, etc.) | Re-run FFmpeg extract + HTDemucs on original |
| Extracted frames (JPEGs) | Re-run FFmpeg frame extraction |
| Storyboard grid JPEGs | Re-composite from extracted frames |
| analysis.db (entire database) | Re-run full pipeline on original source |


##### Tier 3 — Ephemeral (delete immediately after their consumer completes):


| File | Lifetime |
|:---|:---|
| Intermediate render segments | Deleted after final concatenation |
| Temp audio chunks | Deleted after WhisperX completes |
| Preview renders (low-res) | Deleted after human review |
| Animation frame sequences (PNGs) | Deleted after FFmpeg composites them |

Disk budget estimate (4-hour 4K source):

| Tier | Size | Persistent? |
|:---|:---|:---|
| Sacred (source + renders + metadata) | 30-45 GB | Always |
| Regenerable (when all analysis cached) | 30-50 GB | Until space needed |
| Ephemeral (during pipeline run) | 10-30 GB | Deleted automatically |
| Peak usage | 70-125 GB | During processing |
| Steady-state | 30-45 GB | After cleanup |

MCP Tool: clipcannon_disk_status(project_id) — returns current usage by tier. clipcannon_disk_cleanup(project_id, target_free_gb) — frees space by deleting ephemeral first, then regenerable (largest first).

Proactive cleanup: Ephemeral files are deleted automatically as each pipeline step completes. The system warns when disk space falls below 20GB free.


### 8.7 Graceful Pipeline Degradation

Problem: The 12-stream understanding pipeline runs 18 processing steps. If one stream fails (e.g., Wav2Vec2 crashes on a corrupt audio segment, PaddleOCR fails on unusual frame encoding), should the entire pipeline fail? If yes, the user gets nothing from a 15-minute processing run. If no, how does the AI know which data is missing?

Solution: DAG-based execution with required and optional tasks. Required tasks (audio extraction, VFR normalization) stop the pipeline on failure. Optional tasks (emotion analysis, OCR, beat detection) provide fallback empty values and mark themselves as failed in the VUD.

Task Classification:

| Task | Required? | If It Fails |
|:---|:---|:---|
| Probe | Yes | Pipeline stops — can't read the file |
| VFR normalization | Yes | Pipeline stops — timestamps will be unreliable |
| Audio extraction | Yes | Pipeline stops — no audio = no transcript |
| HTDemucs source separation | No | Fallback: feed mixed audio to all audio models (lower quality, still functional) |
| WhisperX transcription | Yes | Pipeline stops — transcript is the primary editing signal |
| SigLIP visual embedding | No | Fallback: no scene detection, no visual similarity. AI relies on storyboard grids only. |
| PaddleOCR text detection | No | Fallback: empty on_screen_text[]. AI can still read text from storyboard grid images. |
| Quality assessment | No | Fallback: all scenes classified as "unknown" quality. AI skips quality filtering. |
| Shot type classification | No | Fallback: all scenes classified as "unknown" shot type. AI uses default crop strategy. |
| Nomic semantic embedding | No | Fallback: no topic segmentation. AI uses transcript directly for topic identification. |
| Wav2Vec2 emotion | No | Fallback: flat emotion curve (energy=0.5 everywhere). Highlights rely on reactions + transcript only. |
| WavLM speaker diarization | No | Fallback: single speaker "speaker_0" for all segments. WhisperX diarization may partially cover. |
| SenseVoice reactions | No | Fallback: empty reactions[]. Highlights rely on emotion + transcript only. |
| Beat This! beat detection | No | Fallback: no beat grid. AI places cuts without beat-snapping. |
| Acoustic analysis | No | Fallback: no silence gaps detected. AI uses word boundaries for cut points. |
| Content safety | No | Fallback: content rated "unknown". AI includes content safety disclaimer. |
| Chronemic computation | No | Fallback: no pacing data. AI estimates pacing from transcript word count. |
| Storyboard generation | No | Fallback: AI requests individual frames via clipcannon_get_frame instead. |

VUD marks failed streams explicitly:

```json
{
  "stream_status": {
    "transcription": "completed",
    "visual": "completed",
    "ocr": "failed",
    "quality": "completed",
    "shot_type": "completed",
    "semantic": "completed",
    "emotion": "failed",
    "speaker": "completed",
    "reactions": "completed",
    "beats": "completed",
    "acoustic": "completed",
    "chronemic": "completed"
  },
  "failed_streams": ["ocr", "emotion"],
  "degradation_note": "OCR and emotion analysis failed. On-screen text detection unavailable. Emotion energy data is flat (0.5). Highlights rely on reactions and transcript only."
}
The AI reads stream_status and degradation_note and adjusts its editing strategy accordingly. It does not crash or refuse to edit — it works with what it has, like a human editor working with incomplete notes.
```


### 8.8 Generation Loss Prevention

Problem: If the user rejects a clip and the AI re-renders with changes, the system might accidentally render from a previously rendered output instead of the original source. Each re-encode degrades quality (generation loss). Over 2-3 re-renders, compression artifacts become visible.

Solution: Immutable Source Reference architecture. Every EDL and every render command traces back to the original source video via a SHA-256-verified reference. The rendering engine physically cannot accept a rendered output as input.

Enforcement rules:

Every EDL contains an immutable source reference: source_file_sha256 that was computed during probe. The rendering engine verifies this hash matches the file before rendering. If the file has been modified or replaced, rendering is rejected.

Rendered outputs are tagged: All rendered files are written to renders/{render_id}/output.mp4. The rendering engine refuses to open any file from a renders/ directory as a source input.

Single-pass rendering: When an EDL specifies multiple segments (multi-segment clip), the typed-ffmpeg translation layer builds ONE FFmpeg filter_complex command that reads all segments from the original source and concatenates in a single encode pass. There are no intermediate rendered segments that get re-encoded.

Re-render = new render from source: When the AI modifies an EDL and re-renders, it creates a new render job that reads from the original source. The previous render output is not touched — it can be deleted (ephemeral tier) or kept for comparison.

Provenance enforces lineage: Every render provenance record contains input.sha256 pointing to the original source's hash. If a render record's input hash matches any output hash from a prior render, the provenance chain integrity check fails — detecting accidental generation loss.


## 9. Publishing Pipeline

(Section numbers 9.1, 9.2 below)


### 9.1 Platform API Integration

Publishing is the final phase. Each platform requires OAuth authentication and has specific API endpoints for video upload.


#### 8.1.1 YouTube Data API v3

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 (Google Cloud Console project required) |
| Scopes | youtube.upload, youtube.readonly |
| Upload | Resumable upload via videos.insert |
| Max File | 256 GB / 12 hours |
| Rate Limits | 10,000 units/day (each upload costs 1600 units) |
| Metadata | Title (100 chars), description (5000 chars), tags, category, privacy |
| Shorts | Upload as regular video with #Shorts in title/description, vertical aspect |


#### 8.1.2 Meta Graph API (Instagram + Facebook)

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 via Facebook Login (Meta Business Suite) |
| Instagram Reels | Content Publishing API: POST /{ig-user-id}/media (type=REELS) |
| Instagram Feed | Content Publishing API: POST /{ig-user-id}/media (type=VIDEO) |
| Facebook Reels | POST /{page-id}/video_reels |
| Facebook Feed | POST /{page-id}/videos |
| Requirements | Instagram Business/Creator account, Facebook Page |
| Upload | Resumable upload with upload session |
| Rate Limits | 25 content publishes per day (Instagram), 50 API calls/hour |


#### 8.1.3 TikTok Content Posting API

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 (TikTok Developer Portal app required) |
| Scopes | video.publish, video.upload |
| Upload Flow | 1) Init upload → 2) Upload video chunks → 3) Publish with metadata |
| Metadata | Description (2200 chars), privacy level, disable comments/duet/stitch flags |
| Requirements | TikTok Developer account, app review |
| Rate Limits | Varies by app tier |
| Note | Direct posting requires app review; "Share to TikTok" is alternative |


#### 8.1.4 LinkedIn API

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 (LinkedIn Developer app) |
| Scopes | w_member_social (personal), w_organization_social (company) |
| Upload Flow | 1) Register upload → 2) Upload binary → 3) Create post with video asset |
| Metadata | Commentary text (3000 chars), visibility |
| Rate Limits | 100 API calls/day for most apps |
| Requirements | LinkedIn Developer app with Marketing API access |


### 9.2 Human Approval Workflow

All content goes through human approval before publishing:

```
PUBLISH WORKFLOW
================
```

1. AI generates edit + renders output + generates metadata
2. Post enters REVIEW queue with:
   - Rendered video file (playable locally)
   - Platform-specific metadata (title, description, hashtags)
   - Suggested publish time (if scheduling enabled)
   - Thumbnail image

3. Human reviews via MCP tool calls:
   clipcannon_publish_review → see all pending posts
   clipcannon_get_frame → inspect specific moments
   (Watch the rendered video locally)

4. Human decides:
   clipcannon_publish_approve → approve for publishing
   clipcannon_publish_reject → reject with feedback
                            (AI can regenerate based on feedback)

5. Approved posts are published:
   clipcannon_publish_execute → push to platform API
   clipcannon_publish_status → confirm successful upload

## 9. Business Model & Billing


### 9.1 Strategic Positioning (Value Equation)

ClipCannon's competitive advantage is built on the Hormozi Value Equation:

Value = (Dream Outcome × Perceived Likelihood) / (Time Delay × Effort & Sacrifice)
| Element | ClipCannon Delivery | Competitor (Manual) |
|:---|:---|:---|
| Dream Outcome | 20+ platform-ready clips from one video, with titles, descriptions, captions | Same result, eventually |
| Perceived Likelihood | Consistent AI analysis + human approval gate = reliable output | Depends on editor skill |
| Time Delay | 5 min analysis + seconds per render = minutes total | 4-8 hours per source video |
| Effort & Sacrifice | Drop video in, approve outputs. Zero editing skills needed | Learn editing software, make decisions frame-by-frame |

Competitive Vectors (win on all four):

Speed: 5-minute analysis vs. hours. Render in seconds, not minutes. 3 parallel NVENC encoders
Risk: AI produces consistent quality. Human approval prevents bad posts. Performance-based billing (only charge on success)
Ease: One video in → everything handled. No editing skills required. Dashboard shows everything clearly
Price: Local GPU = zero per-API-call cost. Amortized over volume, drastically cheaper than human editors ($50-150/hour) or cloud services ($20-50/video)

### 9.2 Grand Slam Offer

Make the offer so good people feel stupid saying no:

What they get:

Full multimodal video understanding (12 parallel AI streams)
AI-generated edit plans with highlight detection
Platform-optimized renders for 5 platforms (TikTok, Instagram, YouTube, Facebook, LinkedIn)
Word-level animated captions burned in
Face-aware smart cropping (landscape → vertical)
AI-composed original background music (no licensing fees, no copyright claims, commercially safe)
Programmatic sound effects (transition whooshes, risers, impacts, stingers, chimes)
Professional animated lower thirds (10 template styles, custom text/colors/animation)
Animated title cards with kinetic typography
28+ built-in Lottie animations (subscribe CTAs, emoji reactions, social icons, decorative effects)
20+ pre-rendered video effects (light leaks, bokeh, glitch, particles, film grain)
104+ transition types (44 FFmpeg native + 60 GL shader ports)
AI-generated titles, descriptions, and hashtags per platform
Human approval dashboard before anything publishes
All processing on their own GPU (data never leaves their machine)
What they risk: Nothing. Performance-based billing — only charged when analysis completes successfully. Failed processing = automatic refund.

The guarantee: Conditional — if analysis doesn't produce at least 5 viable clips from a video over 10 minutes long, no charge. Once you have reputation (anti-guarantee), the guarantee becomes unnecessary because results speak.


### 9.3 Pricing Model

Adapted from OCR Provenance's proven dual-layer billing architecture:


#### 9.3.1 Per-Video Credit System

| Operation | Credit Cost | Rationale |
|:---|:---|:---|
| Video Analysis (full 12-stream pipeline) | 10 credits | GPU-intensive: transcription + embeddings + frame extraction |
| Clip Render (per output clip, includes audio + animations) | 2 credits | NVENC encoding + caption burn + crop + audio mix + overlay compositing |
| AI Music Generation (per track, included in render) | 0 credits | Included in clip render cost -- no separate music licensing fees |
| Metadata Generation (per clip per platform) | 1 credit | AI-generated title + description + hashtags |
| Platform Publish (per post) | 1 credit | API call + upload + status tracking |

Credit Packages (Stripe checkout):

| Package | Credits | Price | Per-Credit | Use Case |
|:---|:---|:---|:---|:---|
| Starter | 50 | $5 | $0.10 | Try it out (5 source videos) |
| Creator | 250 | $20 | $0.08 | Weekly content creator |
| Pro | 1,000 | $60 | $0.06 | Daily content production |
| Studio | 5,000 | $200 | $0.04 | Agency / multi-channel |
| Unlimited | Unlimited | $99/month | — | Subscription for high-volume users |

Why credits, not subscription-only: Credits align cost with value delivered. A user who processes 2 videos/month shouldn't pay the same as someone processing 50. Credits also have zero ongoing cost when idle (no monthly drain). The unlimited tier serves power users who want predictability.

Example workflow cost: 1-hour podcast → full analysis (10 credits) + 15 clips rendered (30 credits) + metadata for all 5 platforms per clip (75 credits) = 115 credits = ~$7-12 depending on package. Compare to hiring a human editor: $200-500 for the same output.


#### 9.3.2 Billing Architecture

Directly adapted from OCR Provenance's proven system:

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  ClipCannon MCP     │     │  License Server   │     │  Cloudflare D1   │
│  Server (local)  │────▶│  (port 3100)      │────▶│  (source of truth)│
│                  │     │  SQLite cache      │     │  Stripe webhooks  │
│  LicenseClient   │     │  HMAC integrity    │     │  Credit balances  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
Charge Flow:
```

User initiates video analysis via MCP tool
MCP server calls POST /v1/charge on local license server
License server deducts credits locally + verifies with Cloudflare D1 (source of truth)
On success: credits confirmed, processing begins
On failure (insufficient credits): automatic refund, processing blocked with clear message
On processing error: automatic refund to local + central balance
HMAC Balance Integrity: Every credit mutation is HMAC-SHA256 signed. Tampered balances trigger fatal exit. Same proven pattern as OCR Provenance.

Machine ID + License Key: Deterministic HMAC key from machine ID. Same machine always gets same key. Balance persists across container restarts.


#### 9.3.3 Spending Controls

Monthly spending caps: $5 - $500 (user-configurable)
Dashboard warning at 80% of limit
Per-video cost estimate shown before processing begins
Detailed cost breakdown in project view

### 9.4 Revenue Model

Revenue = Credits Sold × Margin

Cost per credit to us:
  - Infrastructure: ~$0 (user's GPU, user's electricity)
  - Cloudflare D1: ~$0.001/transaction
  - Stripe fees: 2.9% + $0.30 per checkout
  - Development + maintenance: amortized

Gross Margin: ~95% (no cloud compute costs — user provides GPU)
Growth levers:

Volume: More creators → more credits purchased
Platform expansion: Add more platforms (Twitter/X, Pinterest, Threads) → more renders per source
Premium features: Advanced ACE-Step LoRA fine-tuning, custom brand audio styles, premium animation packs at higher credit rates
Agency tier: Multi-seat dashboard, team management, bulk pricing
Template marketplace: User-created editing templates (audio presets, animation styles, brand kits), revenue share
Animation marketplace: Community-contributed Lottie/WebM animation packs, credit-based purchasing

## 10. Dashboard & Human-in-the-Loop Interface


### 10.1 Architecture

The dashboard is a web application running locally as part of the ClipCannon container, providing the human-in-the-loop interface for reviewing, approving, and managing all AI-generated content.

```
┌──────────────────────────────────────────────────────┐
│  Docker Container (3 Mandatory Services)              │
│                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │ ClipCannon MCP │  │License Server│  │  Dashboard   ││
│  │ Server      │  │  port 3100   │  │  port 3200   ││
│  │ port 3366   │  │  Billing/Auth│  │  Web UI      ││
│  │ 60+ tools   │  │  Credits     │  │  Review/     ││
│  │             │  │  Stripe      │  │  Approve     ││
│  └──────┬──────┘  └──────────────┘  └──────────────┘│
│         │                                             │
│  ┌──────▼───────────────────────────────────────────┐│
│  │  GPU Processing Pipeline (Python Workers)         ││
│  │  Whisper │ SigLIP │ Wav2Vec2 │ WavLM │ FFmpeg   ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
```

### 10.2 Dashboard Pages


#### 10.2.1 Main Dashboard (Home)

Credit Balance: Current credits remaining + credits consumed this month
Projects Overview: Active projects with status indicators (analyzing, ready for review, published)
Recent Activity: Timeline of analyses, renders, approvals, and publications
Quick Stats: Videos processed, clips generated, posts published (this week/month)
System Health: GPU status, VRAM usage, model loading status, disk space

#### 10.2.2 Project View

Source Video: Thumbnail, duration, resolution, file info
Analysis Status: Progress bar for each of the 12 streams (source separation, visual, OCR, quality, shot type, transcript, semantic, emotion, speaker, reactions, acoustic/beats, chronemic)
Video Understanding Summary: AI-generated summary of the video content, topics detected, speakers identified, highlight moments
Timeline Visualization: Interactive timeline showing:
Scene boundaries (visual)
Speaker segments (color-coded)
Emotion/energy curve (graph overlay)
Topic segments (labeled regions)
Detected highlights (starred markers)
Transcript Panel: Full searchable transcript with speaker labels and timestamps. Click to jump to that point in the video preview

#### 10.2.3 Edit Review Page (Core Human-in-the-Loop)

This is where the human reviews and approves AI-generated edits:

Clip Preview Player: Watch the rendered clip directly in the browser
Platform Preview: Side-by-side mockups showing how the clip will appear on each target platform (phone frame for TikTok/Reels, desktop for YouTube/LinkedIn)
Metadata Review:
Title (editable)
Description (editable)
Hashtags (editable, with suggestions)
Thumbnail (selectable from key frames)
Caption Preview: See burned-in captions in real-time in the video player
Action Buttons:
Approve → moves to publishing queue
Approve with Edits → save metadata changes, then approve
Reject → provides feedback to AI for regeneration
Regenerate → re-run AI edit suggestions with adjusted parameters
Skip → move to next clip in batch

#### 10.2.4 Publishing Queue

Pending Approval: All clips awaiting human review (batch review mode)
Approved (Ready to Publish): Clips approved but not yet published
Scheduled: Clips scheduled for future publishing
Published: History of all published posts with links
Rejected: Clips that were rejected with feedback notes
Platform Status: Connection status for each social media account (connected/disconnected/token expiring)

#### 10.2.5 Account & Billing

Credit Balance: Current balance with visual indicator
Add Credits: Preset buttons ($5, $20, $60, $200) → Stripe checkout
Subscription Management: Upgrade/downgrade/cancel unlimited plan
Usage History: Table of all charges (date, operation, credits used, project)
Spending Limit: Set monthly cap with 80% warning threshold
API Key: Display (prefix only) with regeneration option
Connected Platforms: OAuth connection status for all 5 platforms

#### 10.2.6 Settings

Processing Defaults: Default whisper model, frame extraction rate, caption style
Platform Profiles: Default encoding profiles, preferred aspect ratios per platform
Output Preferences: Default output directory, naming convention, thumbnail settings
GPU Configuration: VRAM allocation, concurrent model limits, NVENC encoder count

### 10.3 Authentication

Adapted from OCR Provenance's magic link system:

User enters email → POST /login
Server generates signed JWT (10-min expiry)
Email sent via Resend API (or dev mode returns token in console)
User clicks magic link → GET /auth/verify?token=...
Token verified → session created (30-day TTL)
HTTP-only cookie set → redirect to /dashboard
Environment Isolation: Dashboard runs with whitelisted env vars only. Cannot access license signing keys or Stripe webhook secrets. Even if compromised, cannot forge credits or payments.


### 10.4 Human-in-the-Loop Workflow

```
AI GENERATES CONTENT
        │
        ▼
┌───────────────────────────────────┐
│        DASHBOARD REVIEW           │
│                                   │
│  ┌─────────┐  ┌──────────────┐  │
│  │ Preview  │  │  Metadata    │  │
│  │ Player   │  │  Editor      │  │
│  │          │  │              │  │
│  │ [Play]   │  │  Title: ...  │  │
│  │          │  │  Desc: ...   │  │
│  │          │  │  Tags: ...   │  │
│  └─────────┘  └──────────────┘  │
│                                   │
│  ┌─────────────────────────────┐ │
│  │ Platform Previews           │ │
│  │  📱 TikTok  📱 Reels       │ │
│  │  🖥️ YouTube  💼 LinkedIn   │ │
│  └─────────────────────────────┘ │
│                                   │
│  [✓ Approve] [✎ Edit] [✗ Reject] │
└───────────────────────────────────┘
        │
        ├── Approved ──► Publishing Queue ──► Platform API
        │
        ├── Edited ──► Save changes ──► Approved
        │
        └── Rejected ──► Feedback to AI ──► Regenerate
Batch Review Mode: For efficiency, the dashboard supports batch review where the human can swipe through all clips from a source video, approve/reject each with one click, and edit metadata inline. Target: review 20 clips in under 5 minutes.
```

Notification System: When analysis completes or clips are ready for review, the dashboard shows a notification badge. Optional: browser push notifications, email notifications, or webhook to Slack/Discord.


## 11. Business Strategy


### 11.1 Go-to-Market: Content Creators First

Initial Target: Solo content creators who produce long-form video (podcasts, interviews, talks, tutorials) and need to repurpose for social media but can't afford editors.

Why this segment first:

Pain is acute and daily (hours spent editing every week)
They already own capable GPUs (gaming/streaming rigs with RTX 3070+)
Price-sensitive (can't afford $200/video human editors)
Technical enough to run Docker containers
Small enough that 1-2 users per machine is fine
Vocal community (will share tools that save them time)
Expansion path: Solo creators → Small agencies → Media companies → Enterprise


### 11.2 Acquisition Strategy (Hormozi Leads Framework)

Free content lead generation (eat your own dog food):

Use ClipCannon to process YOUR OWN content about ClipCannon
Every demo video is also a proof-of-concept: "This video was cut into 15 clips and posted to 5 platforms by ClipCannon"
Technical tutorials as lead magnets
Open-source the MCP server, monetize through credits (freemium model)
The 4 ways to get customers (Hormozi):

Warm outreach: DM content creators you follow. "I built something that turns your 1-hour podcast into 20 platform-ready clips in 5 minutes. Want to try it?"
Content: YouTube/Twitter showing before/after of ClipCannon processing a real video
Cold outreach: Automated but personalized emails to creators with >10K subscribers who post long-form
Paid ads: After product-market fit, scale with paid acquisition

### 11.3 Retention Levers

Consistency (Hormozi risk vector): Every analysis produces reliable, predictable output. Users learn to trust it
Speed addiction (Hormozi speed vector): Once you've experienced 5-minute video repurposing, going back to manual editing is painful
Data lock-in (positive): Project history, editorial preferences, platform analytics accumulate over time
Habit formation: Content creators produce on a schedule. ClipCannon becomes part of the weekly workflow
Credit balance: Pre-purchased credits create commitment (sunk cost + convenience)

### 11.4 Pricing Psychology

From Hormozi's framework:

Charge more, not less: Position as premium tool ($0.04-0.10/credit) not race-to-bottom. The value delivered ($200+ of human editor time saved per video) supports premium pricing
Anchor to alternatives: "A human editor charges $200/video. ClipCannon processes the same video for $7-12"
Remove risk: Performance-based billing. Only charged on successful analysis. Failed = refund
Stack the value: Analysis + editing + rendering + captions + metadata + thumbnail + publishing prep = one price. Don't unbundle
Urgency via volume: Show "X credits remaining" prominently. Credit packages feel like buying ammunition — you want to have enough

### 11.5 Moat & Defensibility

Speed + Ease dominance: No competitor offers 12-stream multimodal understanding locally. Existing tools (Opus Clip, Descript) are cloud-only, per-video priced, and don't run locally
Local-first: Data never leaves the machine. Critical for creators with unreleased content, brand deals, or NDAs
GPU utilization: Amortizes the RTX 5090 investment that creators already made for gaming/streaming. Zero marginal compute cost
Embedder architecture: The Hexa-Modal-derived 12-stream approach is novel and produces richer understanding than competitors using only transcription
MCP protocol: Plugs into any AI model, not locked to one vendor. Future-proof against model provider changes
Zero-cost audio: AI-generated music and programmatic SFX eliminate stock music licensing fees ($15-50/track at competitors). Every generated track is original, commercially safe, and tailored to the content
Full creative suite: Professional motion graphics (lower thirds, titles, transitions, CTAs) built in -- competitors like Opus Clip produce bare clips with no overlays. CapCut has templates but requires manual selection. ClipCannon's AI selects and parameterizes overlays autonomously

## 12. Phased Delivery (Updated)


### Phase 1: Video Understanding + Billing + Provenance Foundation

Deliverables:

MCP server scaffold with project management tools
Video ingestion pipeline (FFmpeg probe + audio extraction + frame extraction)
Transcription via faster-whisper with word-level timestamps
Frame embedding via SigLIP
Scene boundary detection
Video Understanding Document (VUD) generation with AI-readable translations (scene descriptions, topic labels, energy scores -- not raw embeddings)
SHA-256 Provenance Hash Chain: provenance.db per project, hash computation at every pipeline stage, chain integrity verification, provenance query MCP tools (clipcannon_provenance_verify, clipcannon_provenance_query, clipcannon_provenance_chain)
27 MCP tools across 7 categories: project management (5), understanding/pipeline (4), understanding/visual (4), understanding/search (1), provenance (4), disk management (2), configuration (3), billing (4)
License server with credit-based billing (local SQLite + HMAC integrity + Stripe webhooks; Cloudflare D1 sync stubbed for Phase 2)
Machine ID provisioning + HMAC balance integrity
Dashboard: balance display, add credits, project list, provenance chain viewer, system health
Success Criteria:

Process a 1-hour video in under 5 minutes
Accurate word-level timestamps (WER < 5% on English content)
Scene detection captures 90%+ of visual transitions
Credit charge/refund flow works end-to-end
VUD contains AI-readable data (text labels, scores, timestamps) not raw embeddings
Provenance chain has 19 records (one per pipeline stage: probe through finalize) with valid chain hashes
clipcannon_provenance_verify passes on every completed project
Any file modification after provenance recording is detected by hash mismatch

> **Phase 1 COMPLETED and VERIFIED on 2026-03-21.** 750/750 FSV checks passed. 181 pytest tests pass. 0 lint errors. 27 MCP tools, 20 pipeline stages, 16 analysis streams, 23 database tables, 4 vector tables. See [Verification Report](../docs/codestate/12_verification_report.md).

### Phase 2: Editing Engine + Audio + Dashboard

Deliverables:

Full audio embedding pipeline (emotion, speaker, acoustic)
Topic segmentation and highlight detection
EDL format and edit creation tools (with audio + animation specs)
Caption generation and rendering
Face-aware smart cropping
Platform encoding profiles
FFmpeg rendering pipeline with NVENC
All editing and rendering MCP tools
Batch rendering
AI Audio Generation Engine:
ACE-Step v1.5 integration for AI-generated background music
MIDI composition pipeline (MIDIUtil + music21 + FluidSynth)
Programmatic DSP sound effects (whooshes, risers, impacts, chimes)
Audio mixing pipeline with ducking, crossfade, normalization (pydub + pedalboard)
Audio generation MCP tools (clipcannon_generate_music, clipcannon_compose_midi, clipcannon_generate_sfx)
Full dashboard with project view, timeline visualization, clip preview player
Edit review page with approve/reject/edit workflow
Batch review mode for human-in-the-loop efficiency
Success Criteria:

AI can produce 10+ platform-ready clips from a single 1-hour source
Render time < 30 seconds per clip
Captions are word-accurate and properly timed
Output passes platform validation for all 5 target platforms
Human can review and approve 20 clips in under 5 minutes via dashboard
AI-generated music is coherent, mood-appropriate, and at least 30 seconds long
DSP sound effects are clean (no clicks/pops) and properly timed to transitions
Audio ducking correctly reduces music under speech segments

### Phase 3: Motion Graphics, Publishing & Full Dashboard

Deliverables:

Motion Graphics & Animation Engine:
PyCairo-based lower third rendering (10 template styles) with slide/fade/pop animations
PyCairo-based title card rendering with kinetic typography
Lottie animation rendering pipeline (rlottie-python) with shipped 28-asset pack
Pre-rendered WebM overlay system with shipped 20-asset effects pack
60+ GL Transition shaders ported to FFmpeg xfade expressions
Animation MCP tools (clipcannon_add_lower_third, clipcannon_add_animation, clipcannon_add_transition, etc.)
Optional LottieFiles.com asset fetching (100K+ free animations)
Custom asset import system for user-provided WebM/Lottie files
Metadata generation (titles, descriptions, hashtags per platform)
Thumbnail generation
Human approval workflow
OAuth integration for all 5 platforms
Publishing API integration (YouTube, Instagram, TikTok, Facebook, LinkedIn)
Publishing queue management with scheduling
Post-publish status tracking
Publishing queue dashboard page with batch approve/reject
Platform connection management (OAuth flows in dashboard)
Account & billing page with full credit history, spending limits
Success Criteria:

Generated metadata is platform-appropriate and engaging
OAuth flows work for all 5 platforms
Successful automated posting with human approval gate
Full audit trail of all publishing actions
Credit billing accurate across all operations
Lower thirds render at 1080p with smooth animation (no jank/stutter)
Lottie animations render at correct frame rate with proper alpha transparency
All 44+ FFmpeg native transitions work reliably between segments
Animation overlays do not degrade render speed by more than 20%

### Phase 4: Intelligence, Optimization & Growth

Deliverables:

Content performance feedback loop (if analytics APIs available)
Improved highlight detection using performance data
A/B testing support (generate multiple versions of same clip)
Scheduling optimization (best time to post per platform)
Template system for recurring content types (save audio/animation presets)
Multi-language support for captions and metadata
Advanced Audio: ACE-Step LoRA fine-tuning on user's brand audio style, custom SoundFont import, audio style presets per content type
Advanced Animation: User-created PyCairo template builder (define custom lower third designs), brand kit system (consistent colors/fonts across all overlays), animated thumbnail generation
Animation Marketplace: Community-contributed Lottie/WebM animation packs with credit-based purchasing
Agency tier: Multi-seat dashboard, team accounts, bulk credit pricing
Usage analytics dashboard: Cost per video, ROI tracking, performance heatmaps
Unlimited subscription tier for high-volume creators

## 10. Data Flow Summary

SOURCE VIDEO (mp4/mov/mkv/webm)
```
         │
         ▼
    ┌─────────┐
    │  INGEST  │──── FFprobe metadata
    └─────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
 AUDIO     FRAMES
 (16kHz)   (2fps JPEGs)
    │         │
    ├─────┐   │
    │     │   │
    ▼     ▼   ▼
 WHISPER  AUDIO  SIGLIP
 (transcript) (embedders) (visual embeddings)
    │     │         │
    │     ├─────┐   │
    │     │     │   │
    ▼     ▼     ▼   ▼
 NOMIC  EMOTION SPEAKER SCENES
 (semantic) (energy) (who)  (where)
    │     │     │     │
    └─────┴─────┴─────┘
              │
              ▼
    ┌─────────────────┐
    │  VIDEO UNDERSTANDING  │
    │    DOCUMENT (VUD)     │
    └─────────────────┘
              │
         AI MODEL READS VUD
         AI MODEL PRODUCES EDL
              │
              ▼
    ┌─────────────────┐
    │   EDIT DECISION  │
    │  LIST (EDL) with │
    │  audio + animation│
    │  specifications   │
    └─────────────────┘
              │
    ┌────┬────┴────┬────┐
    │    │         │    │
    ▼    ▼         ▼    ▼
  AUDIO  MIDI    DSP   ANIMATION
  GEN    COMP    SFX   RENDER
  (ACE-  (music21 (numpy (PyCairo
  Step)  +Fluid  scipy) +rlottie
         Synth)         +WebM)
    │    │         │    │
    └────┴────┬────┴────┘
              │
         AUDIO MIX
         (pydub)
              │
              ▼
    ┌─────────────────┐
    │  FFMPEG RENDER   │
    │  (NVENC/NVDEC)   │
    │  + overlay comp  │
    │  + audio mux     │
    └─────────────────┘
              │
    ┌────┬────┬────┬────┐
    │    │    │    │    │
    ▼    ▼    ▼    ▼    ▼
  TIKTOK INSTA  YT   FB  LI
  9:16  9:16  16:9  9:16 1:1
  60s   90s   10m   60s  3m

              │
         HUMAN REVIEW
              │
              ▼
    ┌─────────────────┐
    │  PUBLISH TO      │
    │  PLATFORM APIs   │
    └─────────────────┘
```

