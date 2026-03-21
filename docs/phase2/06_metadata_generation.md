# Metadata Generation

## 1. Overview
- AI generates platform-specific titles, descriptions, and hashtags for each clip
- Different platforms have different character limits and content styles
- Metadata is stored in the EDL metadata{} object
- The AI uses VUD data (topics, highlights, transcript) to craft compelling metadata

## 2. Platform Metadata Requirements

| Platform | Title Max | Description Max | Hashtags | Notes |
|----------|----------|----------------|----------|-------|
| TikTok | N/A | 2200 chars | 3-5 | No separate title; description is the caption |
| Instagram | N/A | 2200 chars | 20-30 | Hashtags in description body |
| YouTube | 100 chars | 5000 chars | 500 char total | Separate title + description + tags |
| Facebook | N/A | 63,206 chars | Optional | Description/caption only |
| LinkedIn | N/A | 3000 chars | 3-5 | Professional tone required |

## 3. Metadata Generation Strategy
- Extract key topics from VUD topics[]
- Use highlight reason text for compelling titles
- Include speaker names if relevant
- Match tone to platform (casual for TikTok, professional for LinkedIn)
- Include call-to-action in descriptions
- SEO-optimize YouTube titles and descriptions

## 4. MCP Tool: clipcannon_generate_metadata
- Parameters: project_id, edit_id, target_platform
- Returns: title, description, hashtags, thumbnail_timestamp_ms
- AI reviews and can modify before approval

## 5. Implementation
File: `src/clipcannon/editing/metadata_gen.py`
- `generate_metadata(edit, project_data, platform)` -> MetadataResult
- `optimize_for_platform(metadata, platform)` -> MetadataResult
- Platform-specific formatters for each of the 5 platforms
