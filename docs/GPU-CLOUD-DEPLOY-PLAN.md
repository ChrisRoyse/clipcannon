# GPU Cloud Deployment Plan — OCR Provenance MCP

> **Date**: 2026-03-20 | **Goal**: Enable any user to deploy OCR Provenance MCP on a cloud GPU in 3-4 steps

## Executive Summary

GitHub Codespaces discontinued GPU support in August 2025. The best alternatives are **RunPod** (best UX, 4 steps) and **Vast.ai** (cheapest, 5 steps). Both support custom Docker templates with NVIDIA GPU passthrough, port forwarding, and web-based access.

**The user experience we're targeting:**

```
Step 1: Create a RunPod account (or Vast.ai)
Step 2: Add credits ($5-10 minimum)
Step 3: Click our deploy template link
Step 4: Select GPU tier and click "Deploy"
→ Dashboard live at https://<pod-id>-3367.proxy.runpod.net in ~3 minutes
```

That's it. No Docker install. No GPU drivers. No terminal commands. No configuration.

---

## Why Not GitHub Codespaces?

GitHub deprecated GPU machine types in Codespaces effective August 2025 (Azure retired NCv3-series VMs). The GPU offering was never GA — limited beta only. **Not an option.**

---

## Platform Comparison

| Platform | 24GB GPU $/hr | 1-Click Deploy | User Steps | Best For |
|----------|--------------|----------------|-----------|----------|
| **RunPod** | $0.34 (3090) / $0.44 (4090) / $0.69 (5090) | Yes (Hub template) | 4 | Best overall UX |
| **Vast.ai** | $0.16-0.31 (marketplace) | Partial (template link) | 5 | Lowest cost |
| Lambda Cloud | $1.10+ (A100 only) | No | 4 | Enterprise ML |
| GCP | $0.71+ (L4) | No | 8-10 | Enterprise compliance |
| AWS | $1.01+ (g5) | No | 8-10 | Enterprise compliance |
| Paperspace | $1.42+ (A5000) | Partial | 5-6 | ML notebooks |
| NVIDIA Brev | Varies | Yes (Launchable) | 3-4 | Emerging option |
| Modal | $0.80+ | No (code-first) | High | Serverless (wrong fit) |

**Recommendation: RunPod as primary, Vast.ai as budget alternative.**

---

## GPU Tier Pricing (RunPod)

| Tier | GPU | VRAM | Price/hr | Price/day | Price/mo (730hr) | Best For |
|------|-----|------|----------|-----------|-------------------|----------|
| **Standard** | RTX 3090 | 24 GB | $0.34 | $8.16 | $248 | Budget processing |
| **Performance** | RTX 4090 | 24 GB | $0.44 | $10.56 | $321 | Fast processing |
| **Pro** | RTX 5090 | 32 GB | $0.69 | $16.56 | $504 | Large documents + VLM |

All tiers run the exact same Docker image. The only difference is processing speed and VRAM headroom for the VLM model (Chandra needs ~18GB).

**Vast.ai equivalent pricing** (marketplace, prices vary):

| GPU | VRAM | Typical $/hr |
|-----|------|-------------|
| RTX 3090 | 24 GB | $0.16-0.25 |
| RTX 4090 | 24 GB | $0.18-0.31 |
| RTX 5090 | 32 GB | $0.40-0.69 |

---

## Implementation Plan

### Phase 1: RunPod Template (Primary — 1-2 days)

#### What Needs to Happen

1. **Create a RunPod account** at runpod.io (already have one or create one)

2. **Create a Pod Template** on RunPod with these settings:

```
Template Name: OCR Provenance MCP
Container Image: leapable/ocr-provenance-mcp:latest
Container Disk: 20 GB
Volume Disk: 50 GB (for models + databases)
Volume Mount Path: /data
Expose HTTP Ports: 3000, 3366, 3367
Expose TCP Ports: (none needed)
Docker Command: (leave empty — uses ENTRYPOINT from Dockerfile)
Environment Variables:
  MCP_TRANSPORT=http
  TORCH_DEVICE=auto
  MCP_HTTP_PORT=3366
  PORT=3367
```

3. **Publish to RunPod Hub** — make the template public so anyone can deploy it

4. **Get the deploy URL** — RunPod Hub templates have shareable URLs

#### RunPod-Specific Considerations

**Port Access**: RunPod creates HTTPS proxy URLs for each exposed HTTP port:
- Dashboard: `https://{pod-id}-3367.proxy.runpod.net`
- MCP Server: `https://{pod-id}-3366.proxy.runpod.net`
- License Server: `https://{pod-id}-3000.proxy.runpod.net`

**Volume Persistence**: The `/data` volume persists across pod restarts. User databases, license keys, and cached models survive pod stop/start cycles. Users only lose data if they explicitly delete the volume.

**Docker-in-Docker**: RunPod pods ARE Docker containers — you can't run `docker run` inside them. Our application runs directly as the pod, NOT as a container inside a container. This means:
- The `docker-entrypoint.sh` script runs as the pod's entry point
- All 3 services (MCP, License, Dashboard) start inside the pod
- No wrapper needed — the MCP server runs directly

**What Changes in Our Code**: Nothing for the server side. The existing Docker image works as-is on RunPod. The entry point, healthcheck, and service startup all work because the pod IS a Docker container.

#### What the User Sees

```
1. Go to runpod.io → Sign up → Add $5 credits
2. Click our template link: https://runpod.io/console/deploy?template=ocr-provenance-mcp
3. Select GPU:
   [ ] RTX 3090 — $0.34/hr (Standard)
   [ ] RTX 4090 — $0.44/hr (Performance)
   [ ] RTX 5090 — $0.69/hr (Pro)
4. Click "Deploy"
5. Wait ~2-3 min for models to load
6. Click the "3367" port link → Dashboard opens in browser
```

### Phase 2: Vast.ai Template (Budget Alternative — 1 day)

#### What Needs to Happen

1. **Create a Vast.ai account** and create a template:

```
Template Name: OCR Provenance MCP
Docker Image: leapable/ocr-provenance-mcp:latest
Launch Type: Run interactive shell command + ENTRYPOINT
Disk Space to Allocate: 50 GB
On-start script: (leave empty — ENTRYPOINT handles startup)
Environment Variables:
  MCP_TRANSPORT=http
  TORCH_DEVICE=auto
Ports: 3000, 3366, 3367
```

2. **Make the template public** — generates a shareable link

3. **Referral link**: Vast.ai provides a referral URL. When users register through your template link, you earn 3% of their credits (lifetime).

#### Vast.ai Port Access

Vast.ai uses Cloudflare tunnels via "Instance Portal":
- Each exposed port gets a URL like: `https://four-random-words.trycloudflare.com`
- Users click the port links in the Vast.ai dashboard to access each service

#### What the User Sees

```
1. Go to vast.ai → Sign up → Add $5 credits
2. Click our template link
3. Browse available machines → Filter by: 24GB+ VRAM, 50GB+ disk
4. Pick a machine → Click "Rent"
5. Wait ~3-5 min for image pull + model load
6. Click port 3367 in Instance Portal → Dashboard opens
```

### Phase 3: Landing Page Integration (1 day)

Add a "Cloud Deploy" section to the dashboard landing page (port 3367, unauthenticated `/` route) and to the README/website:

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  Deploy on GPU Cloud                                │
│                                                     │
│  No GPU? No problem. Run OCR Provenance on a        │
│  cloud GPU in under 5 minutes.                      │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐                │
│  │   RunPod     │  │   Vast.ai    │                │
│  │  From $0.34/hr│  │  From $0.16/hr│                │
│  │  [Deploy →]  │  │  [Deploy →]  │                │
│  └──────────────┘  └──────────────┘                │
│                                                     │
│  GPU Tiers:                                         │
│  RTX 3090 (24GB) — Standard       $0.34/hr         │
│  RTX 4090 (24GB) — Performance    $0.44/hr         │
│  RTX 5090 (32GB) — Pro            $0.69/hr         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Phase 4: Documentation & Video Script (1 day)

#### README Addition

```markdown
## Cloud Deploy (No Local GPU Required)

Run OCR Provenance on a cloud GPU in 4 steps:

### RunPod (Recommended)
1. Create account at [runpod.io](https://runpod.io)
2. Add $5+ credits
3. [Deploy OCR Provenance →](https://runpod.io/console/deploy?template=ocr-provenance-mcp)
4. Select GPU tier and click Deploy

Dashboard available at the 3367 port link within 3 minutes.

### Vast.ai (Budget Option)
1. Create account at [vast.ai](https://vast.ai)
2. Add $5 credits
3. [Open template →](https://vast.ai/templates/ocr-provenance-mcp)
4. Select a machine with 24GB+ GPU and click Rent

| GPU | VRAM | RunPod $/hr | Vast.ai $/hr |
|-----|------|-------------|-------------|
| RTX 3090 | 24 GB | $0.34 | ~$0.16-0.25 |
| RTX 4090 | 24 GB | $0.44 | ~$0.18-0.31 |
| RTX 5090 | 32 GB | $0.69 | ~$0.40-0.69 |
```

#### Video Script (3-4 minutes)

```
[0:00] "You don't need a GPU to use OCR Provenance. Let me show you how to deploy
        it on a cloud GPU in under 3 minutes."

[0:10] Screen: RunPod.io homepage
       "Go to runpod.io and create a free account."

[0:25] Screen: RunPod dashboard → Credits
       "Add $5 in credits. That gives you 14 hours on an RTX 3090."

[0:40] Screen: Click template deploy link
       "Click this deploy link — I'll put it in the description."

[0:50] Screen: GPU selection dropdown
       "Pick your GPU. RTX 3090 for $0.34/hour is great for most documents.
        RTX 4090 if you want faster processing. RTX 5090 if you're doing
        heavy image analysis with the vision model."

[1:10] Screen: Click Deploy button
       "Click Deploy. That's it. Four steps."

[1:20] Screen: Pod spinning up, logs showing
       "It takes about 2-3 minutes to start up. The system loads 5 AI models
        into the GPU — OCR, vision AI, embeddings, search reranking, and clustering."

[1:50] Screen: Pod ready, click 3367 port link
       "When it's ready, click the 3367 port link to open the dashboard."

[2:00] Screen: Dashboard loading
       "This is your document intelligence dashboard. Everything runs on that
        cloud GPU. Your documents never leave the cloud instance."

[2:15] Screen: Upload a document, watch it process
       "Upload a document... and watch it process in real time. OCR, chunking,
        embeddings, image analysis — the full pipeline."

[2:40] Screen: Click document → Viewer opens
       "Click any document to open the viewer. You can see the original file,
        the extracted chunks, and the full provenance chain."

[3:00] Screen: Search demo
       "Search across all your documents with natural language.
        'Find all payment terms' — and you get results with exact page numbers
        and source attribution."

[3:20] Screen: RunPod dashboard → Stop pod
       "When you're done, stop the pod. Your data is saved on the volume.
        Next time you start it, everything is still there. You only pay
        for the time the GPU is running."

[3:35] End card
       "Link to deploy is in the description. Try it free with $5 in credits."
```

---

## Technical Details

### How the Docker Image Works on RunPod

RunPod pods ARE Docker containers. When a user deploys our template:

1. RunPod pulls `leapable/ocr-provenance-mcp:latest` from Docker Hub
2. The pod starts with our `ENTRYPOINT` (`docker-entrypoint.sh`)
3. Entrypoint bootstraps secrets, detects GPU, starts all 3 services
4. RunPod's HTTP proxy maps exposed ports to public HTTPS URLs

**No code changes needed** for the server. The existing image works as-is.

### What Changes for RunPod vs Local Docker

| Aspect | Local Docker | RunPod |
|--------|-------------|--------|
| GPU access | `--gpus all` flag | Built-in, always available |
| Port access | `localhost:3366` | `https://{pod-id}-3366.proxy.runpod.net` |
| Data persistence | Named volume | RunPod volume (persists across restarts) |
| Host file access | `-v $HOME:/host:ro` | Upload via dashboard or wget |
| NPM wrapper | Required (manages Docker) | Not used (pod IS the container) |
| License key | Auto-provisioned | Auto-provisioned (same mechanism) |
| Dashboard | `localhost:3367` | `https://{pod-id}-3367.proxy.runpod.net` |

### File Upload on RunPod

Since there's no host mount (`/host`), users upload files via:
1. **Dashboard upload** — drag and drop files in the web UI
2. **HTTP upload API** — `POST /api/upload` with multipart form data
3. **wget/curl** — download files directly into the pod via web terminal

The existing upload endpoint handles all of this. No changes needed.

### MCP Client Connection on RunPod

For users who want to connect Claude Code or Cursor to the cloud instance:

```json
{
  "mcpServers": {
    "ocr-provenance-mcp": {
      "command": "npx",
      "args": ["-y", "ocr-provenance-mcp"],
      "env": {
        "OCR_MCP_URL": "https://<pod-id>-3366.proxy.runpod.net"
      }
    }
  }
}
```

**This requires a small wrapper change**: The NPM wrapper needs to support connecting to a remote MCP server URL instead of always spawning a local Docker container. When `OCR_MCP_URL` is set, the wrapper should proxy stdin/stdout to that URL instead of managing Docker.

### Wrapper Enhancement Needed

Add to `packages/wrapper/src/bridge.ts` (or equivalent):

```typescript
// If OCR_MCP_URL is set, proxy to remote instead of local Docker
const remoteUrl = process.env.OCR_MCP_URL;
if (remoteUrl) {
  // Proxy stdin/stdout to remote MCP server via HTTP
  bridgeToRemote(remoteUrl);
} else {
  // Existing behavior: manage local Docker container
  bridgeToDocker();
}
```

This enables the flow:
1. User deploys OCR Provenance on RunPod
2. User configures Claude Code with `OCR_MCP_URL=https://<pod-id>-3366.proxy.runpod.net`
3. Claude Code runs the wrapper locally, which proxies to the cloud instance
4. All 153 tools available through the cloud GPU

---

## What Needs to Be Built

### Must Have (MVP)

| Item | Effort | Description |
|------|--------|-------------|
| RunPod template | 1 hour | Create and publish template on RunPod Hub |
| Vast.ai template | 1 hour | Create and publish template |
| README cloud deploy section | 30 min | Add deployment instructions and pricing table |
| Test on RunPod | 2 hours | Deploy, ingest documents, verify all features work |
| Test on Vast.ai | 2 hours | Same verification on Vast.ai |

### Nice to Have (Post-MVP)

| Item | Effort | Description |
|------|--------|-------------|
| Remote MCP proxy in wrapper | 4 hours | `OCR_MCP_URL` env var for connecting local AI clients to cloud instance |
| Landing page "Cloud Deploy" section | 2 hours | Add deploy buttons to dashboard landing page |
| Video recording | 2 hours | Record the 3-4 minute deployment walkthrough |
| Vast.ai referral integration | 30 min | Configure referral link for passive credits |
| Auto-stop on idle | 2 hours | RunPod pod auto-stops after X hours of no MCP requests (saves money) |

### Not Needed

| Item | Why Not |
|------|---------|
| Code changes to MCP server | Existing Docker image works as-is on RunPod |
| Code changes to entrypoint | Same entrypoint works in RunPod pods |
| New Docker image variant | One image for all platforms |
| Kubernetes/Helm chart | Overkill for individual users |
| Custom cloud provider integration | RunPod/Vast.ai templates are sufficient |

---

## Cost Comparison for Users

### Processing 1,000 Documents (one-time batch)

| GPU | Processing Time | RunPod Cost | Vast.ai Cost |
|-----|----------------|-------------|-------------|
| RTX 3090 | ~3 hours | $1.02 | ~$0.48-0.75 |
| RTX 4090 | ~2 hours | $0.88 | ~$0.36-0.62 |
| RTX 5090 | ~1.5 hours | $1.04 | ~$0.60-1.04 |

### Ongoing Daily Use (8 hours/day)

| GPU | RunPod/day | RunPod/month | Vast.ai/day | Vast.ai/month |
|-----|-----------|-------------|------------|--------------|
| RTX 3090 | $2.72 | $54 | ~$1.28-2.00 | ~$26-40 |
| RTX 4090 | $3.52 | $70 | ~$1.44-2.48 | ~$29-50 |
| RTX 5090 | $5.52 | $110 | ~$3.20-5.52 | ~$64-110 |

**Key selling point**: Users can stop the pod when not using it. A pod with a 50GB volume sitting idle costs $0 on RunPod (volume storage is free up to the allocation). They only pay when the GPU is running.

---

## Action Items (Ordered)

1. Create RunPod account (if not already done)
2. Create RunPod template with the Docker image and settings above
3. Publish template to RunPod Hub
4. Test the full flow: deploy → ingest → search → viewer → stop → restart
5. Create Vast.ai template
6. Test on Vast.ai
7. Add "Cloud Deploy" section to README
8. Record deployment video
9. (Optional) Add `OCR_MCP_URL` remote proxy to the NPM wrapper
10. (Optional) Add deploy buttons to dashboard landing page

---

## FAQ

**Q: Will the models need to download every time a pod starts?**
A: No. The models are baked into the Docker image (~26GB models layer). RunPod caches Docker layers, so after the first pull, subsequent starts are fast (~1-2 minutes). Vast.ai also caches images on the host machine.

**Q: What happens to my data when I stop the pod?**
A: Data in the `/data` volume persists across pod stop/start cycles. Databases, license keys, processed documents — all saved. Data is only lost if you delete the volume.

**Q: Can I connect Claude Code on my Mac to the cloud GPU?**
A: Yes, with the remote proxy feature (post-MVP). Set `OCR_MCP_URL` to your pod's MCP endpoint URL, and the NPM wrapper proxies all tool calls to the cloud instance. Your Mac runs nothing locally except the thin wrapper.

**Q: Is my data secure on RunPod/Vast.ai?**
A: RunPod Secure Cloud uses enterprise data centers with SOC 2 compliance. Community Cloud machines are from individual providers — less guaranteed isolation. For sensitive data, use Secure Cloud. The application itself does zero telemetry and processes everything inside the pod.

**Q: Can I use the free tier?**
A: RunPod has no free tier for GPU pods. Minimum deposit is $5 (covers ~14 hours on RTX 3090). Vast.ai minimum is also $5.

**Q: What about Apple Silicon Macs?**
A: Cloud GPU solves this completely. MPS (Apple Silicon GPU) only works bare-metal, not in Docker. By deploying to RunPod/Vast.ai, Mac users get full CUDA GPU acceleration without any local GPU at all.
