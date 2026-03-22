# Solving the 16:9 → 9:16 Problem

## The Real Problem

The AI can detect WHERE content is on screen (face detection, frame differencing) but cannot understand WHAT is visually important. It picks wrong areas because it has no concept of "this part is interesting" vs "this part is empty space."

This is fundamentally a **visual saliency** problem - knowing what a human viewer would find interesting in each frame.

## Why It's Hard for Screen Recordings

Screen recordings are the WORST case for 16:9 → 9:16 conversion because:
1. Content is spread across the full width (dashboards, file lists, text)
2. The important content changes location as the user scrolls/clicks
3. Text needs to be readable - you can't just shrink it
4. There's no single "subject" to track like in a talking-head video
5. The webcam overlay is small and in one corner

## How OpusClip/Vizard Solve This

They use **saliency-based reframing** with these techniques:
1. **Face/speaker tracking** - Keep the active speaker centered
2. **Object detection** - Track moving objects, UI interactions
3. **Visual saliency maps** - Per-pixel "importance" scores
4. **Temporal smoothing** - Don't jump the crop window every frame

But they DON'T solve the screen recording problem well either - their best results are on talking-head and podcast content where the subject IS the person, not the screen.

## The Real Answer: Don't Try to Auto-Crop Screen Content

For screen recordings with a speaker webcam, the answer is NOT to crop a portion of the 16:9 screen into the 9:16 bottom panel. Instead:

### Strategy 1: Full-Width Contain (letterbox)
Show the ENTIRE screen content width in the bottom panel using `contain` mode. Yes, there will be black bars above/below, but the content is FULLY visible and readable. The viewer sees exactly what the speaker sees.

### Strategy 2: Segment-Aware Smart Crop
Instead of trying to crop automatically, the scene_analysis pipeline should:
1. Run OCR on each scene's middle frame to READ what text is on screen
2. Find the bounding box of the LARGEST text block (that's probably the important content)
3. If the text is in a sidebar/panel → crop to just that panel
4. If the text fills the whole screen → use contain mode
5. If it's a code editor → crop to the code area only

### Strategy 3: Use the Transcript to Infer What to Show
The speaker TELLS you what to look at. When they say "you can see the file list" → the important content is the file list table. When they say "document viewer" → the important content is the document content area. Use NLP on the transcript to match spoken references to visual elements detected by OCR.

### Strategy 4: Content-Type Specific Layouts
Don't use the same layout for every scene type:
- **Website** → contain mode (show full page width)
- **Dashboard overview** → crop to stat cards only
- **File/document list** → crop to the table area
- **Document viewer** → crop to document content (already vertical-friendly)
- **Code editor** → crop to code panel
- **Terminal** → crop to terminal window

## Recommended Implementation

### Phase 1: OCR-Enhanced Scene Analysis (highest impact)
Add OCR to the scene_analysis pipeline to READ what's on screen:
- Run EasyOCR/PaddleOCR on each scene's middle frame
- Store detected text + bounding boxes in scene_map
- Use text content to classify scene type (website/dashboard/doc/code)

### Phase 2: Content-Type Specific Crop Logic
Based on the classified content type, choose the appropriate crop strategy:
```python
if content_type == "document_viewer":
    # Documents are already vertical-friendly
    # Crop to just the document content area (no sidebar)
    strategy = "smart_crop"
elif content_type == "code_editor":
    # Code needs readable text
    # Crop to code panel only
    strategy = "smart_crop"
elif content_type == "dashboard":
    # Dashboards have dense horizontal layouts
    # Use contain mode to show full width
    strategy = "contain"
elif content_type == "website":
    # Websites vary - use contain for safety
    strategy = "contain"
else:
    # Default: contain mode (never cuts off important content)
    strategy = "contain"
```

### Phase 3: Transcript-Visual Alignment
Use the transcript to identify WHAT the speaker is referring to, then:
1. OCR finds text matching the spoken reference on screen
2. Crop window centers on that matching text region
3. Falls back to contain mode if no match found

## Key Insight

The document viewer frames in the video look GREAT because medical protocol documents are already portrait-oriented text content. The problem frames are always the dashboard/file list views which are inherently wide/horizontal layouts.

For horizontal layouts: **just use contain mode.** A readable letterboxed dashboard is infinitely better than a cropped dashboard where you can only see empty dark rows.

## What to Change in scene_analysis.py

1. Add `fit_mode` selection per scene based on content aspect ratio:
   - If content_w / content_h > 2.0 → contain mode (very wide content)
   - If content_w / content_h < 1.0 → cover mode (already vertical)
   - Otherwise → cover mode (close enough to square)

2. In the canvas region builder, set screen region fit_mode dynamically:
   ```python
   content_aspect = content["w"] / content["h"]
   fit_mode = "contain" if content_aspect > 1.5 else "cover"
   ```

3. Use dark background (#0D0D0D) for contain mode padding to blend with dark UIs

This single change would dramatically improve results because wide dashboard/file list views would show their FULL content (letterboxed but readable) instead of a random crop of empty space.
