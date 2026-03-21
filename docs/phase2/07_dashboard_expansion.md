# Dashboard Expansion

## 1. Overview
Phase 2 expands the dashboard from a basic status viewer to a full human-in-the-loop review interface. The dashboard is the primary way humans interact with ClipCannon's output.

## 2. New Pages

### 2.1 Project View (Enhanced)
- Source video thumbnail and metadata (from Phase 1)
- Analysis status with 16-stream progress bars
- Video Understanding Summary (from VUD)
- Quick links to timeline, transcript, edits

### 2.2 Timeline Visualization
- Interactive horizontal timeline
- Layers: scene boundaries (visual), speaker segments (color-coded), emotion/energy curve (graph), topic segments (labeled regions), highlight markers (starred)
- Click on any point to see frame + context
- Zoom in/out for detail vs overview
- Data from: scenes, speakers, emotion_curve, topics, highlights tables

### 2.3 Transcript Panel
- Full searchable transcript with timestamps
- Speaker labels (color-coded)
- Click timestamp to jump to that point in timeline
- Highlight regions used in edits
- Word-level confidence indicators

### 2.4 Edit Review Page (Core Human-in-the-Loop)
This is the most critical Phase 2 dashboard page.

- Clip Preview Player: watch rendered clip in browser (HTML5 video)
- Platform Preview: mockups showing how clip appears on each platform (phone frame for TikTok/Reels, desktop for YouTube)
- Metadata Review: editable title, description, hashtags, thumbnail selection
- Caption Preview: see burned-in captions in the player
- Action Buttons:
  - Approve -> moves to publishing queue
  - Approve with Edits -> save metadata changes, approve
  - Reject -> provides feedback text for AI regeneration
  - Regenerate -> re-run with adjusted parameters
  - Skip -> next clip in batch

### 2.5 Batch Review Mode
- For efficiency: swipe through all clips from a source video
- One-click approve/reject per clip
- Inline metadata editing
- Target: review 20 clips in under 5 minutes
- Keyboard shortcuts for fast review

## 3. API Endpoints (New)

### Timeline API
- `GET /api/projects/{project_id}/timeline` - Scene/speaker/emotion data for visualization
- `GET /api/projects/{project_id}/transcript?start_ms=&end_ms=` - Paginated transcript

### Editing API
- `GET /api/projects/{project_id}/edits` - List all edits
- `GET /api/projects/{project_id}/edits/{edit_id}` - Edit detail with render status
- `POST /api/projects/{project_id}/edits/{edit_id}/approve` - Approve edit
- `POST /api/projects/{project_id}/edits/{edit_id}/reject` - Reject with feedback
- `GET /api/projects/{project_id}/renders/{render_id}/video` - Stream rendered video

## 4. Frontend Technology
- Static SPA (HTML + CSS + vanilla JS or Alpine.js)
- Served from dashboard/static/
- Calls JSON API endpoints
- Video playback via HTML5 <video> element
- Timeline visualization via Canvas or SVG
- Responsive design (works on desktop + tablet)

## 5. Implementation Files
- `src/clipcannon/dashboard/routes/timeline.py` - Timeline data endpoints
- `src/clipcannon/dashboard/routes/editing.py` - Edit management endpoints
- `src/clipcannon/dashboard/routes/review.py` - Review/approve/reject endpoints
- `src/clipcannon/dashboard/static/` - Frontend assets (HTML, CSS, JS)
