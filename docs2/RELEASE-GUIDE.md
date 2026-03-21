# Release Guide: npm + Docker Hub Publishing

## Architecture: ONE Container

There is **ONE version** of the system. No CPU variant, no GPU variant, no older versions. Just one container that auto-detects GPU (NVIDIA CUDA, AMD ROCm) and falls back to CPU only when no GPU is available.

| Component | Image | Size | Changes |
|-----------|-------|------|---------|
| **Models base** | `leapable/ocr-provenance-models:v1` | ~26GB | Rarely (only when AI models or PyTorch change) |
| **App** | `leapable/ocr-provenance-mcp:latest` | ~350MB new layers | Every code release |
| **npm wrapper** | `ocr-provenance-mcp` on npmjs.com | ~27KB | Every code release |

**GPU Strategy:**
- Models image includes CUDA PyTorch (works on CPU too — auto-degrades)
- Container always starts with `--runtime=nvidia --gpus all`
- If no NVIDIA runtime, silently falls back to CPU with a log message
- Chandra VLM requires 16GB+ GPU VRAM — unavailable on CPU but OCR/embeddings/search still work
- Apple Silicon MPS: only available bare-metal (not in Docker), use non-Docker install

**Version Policy:**
- Only `:latest` and the current version tag exist on Docker Hub
- Older versions are NOT published and NOT supported
- Every release REPLACES the previous one — there is no rollback via image tags

---

## Quick Release (Code Changes Only)

This is what you'll do 99% of the time. Models don't change — only code does.

### Step 1: Bump version

```bash
npm version patch --no-git-tag-version   # 1.2.38 → 1.2.39
cd packages/wrapper && npm version patch --no-git-tag-version && cd ../..
```

### Step 2: Build & test

```bash
pkill -f "dist/bin.js"    # Kill stale server (separate command)
npm run build              # Must succeed with 0 errors
npm test                   # Must pass with 0 failures
```

### Step 3: Build app Docker image

```bash
VERSION=$(node -e "console.log(require('./package.json').version)")

docker build \
  --build-context dashboard=../ocrprovenance-cloud \
  --build-arg MODELS_TAG=v1 \
  --build-arg MODELS_IMAGE=leapable/ocr-provenance-models \
  --build-arg VERSION=$VERSION \
  -t leapable/ocr-provenance-mcp:$VERSION \
  -t leapable/ocr-provenance-mcp:latest \
  .
```

No `:cpu` or `:gpu` tags. Just version + latest.

### Step 4: Push app image to Docker Hub

```bash
docker login -u leapable
docker push leapable/ocr-provenance-mcp:$VERSION
docker push leapable/ocr-provenance-mcp:latest
```

Only ~350MB of new layers upload (models layers already on Docker Hub).

### Step 5: Publish npm package

```bash
# Set token, publish, then IMMEDIATELY delete token
echo "//registry.npmjs.org/:_authToken=YOUR_NPM_TOKEN" >> ~/.npmrc
cd packages/wrapper && npm publish --access public && cd ../..
rm -f ~/.npmrc
```

**CRITICAL: Always delete `~/.npmrc` after publishing.** Never leave npm tokens on disk. The `.npmrc` file is gitignored but still a risk if the home directory is shared or backed up. Verify cleanup:

```bash
# Must return "file not found" — if it exists, you leaked a token
cat ~/.npmrc 2>&1 | grep -q "No such file" && echo "OK: .npmrc cleaned" || echo "DANGER: .npmrc still exists — delete it now"
```

### Step 6: Commit & tag

```bash
git add -A
git commit -m "v$VERSION: <description>"
git tag "v$VERSION"
```

### Step 7: Clean up old version from Docker Hub

Delete the PREVIOUS version tag from Docker Hub. Only `:latest` and the current version should exist.

---

## Full Release (Models Changed)

Only needed when you update Marker, Chandra, nomic, PyTorch, or Python dependencies.

### Step 1: Build models image

The models image always includes CUDA PyTorch. No separate CPU build.

```bash
MODELS_TAG="v$(cat MODELS_VERSION)"

docker build -f Dockerfile.models \
  --build-context hf_models=/home/cabdru/.cache/huggingface/hub \
  --build-context surya_models=/home/cabdru/.cache/datalab/models \
  -t leapable/ocr-provenance-models:$MODELS_TAG \
  -t leapable/ocr-provenance-models:latest \
  .
```

Defaults are `COMPUTE=cu130` and `BASE=nvidia/cuda:13.2.0-runtime-ubuntu22.04`. Do NOT override these.

### Step 2: Push models image FIRST

```bash
docker login -u leapable
docker push leapable/ocr-provenance-models:$MODELS_TAG
docker push leapable/ocr-provenance-models:latest
```

Wait for this to complete (~30-60 min for first push) before pushing the app image.

### Step 3: Then do the Quick Release (Steps 1-6 above)

---

## What End Users Run

```bash
npx -y ocr-provenance-mcp install
```

This:
1. Checks Docker is installed and running
2. Pulls `leapable/ocr-provenance-models:v1` (~26GB, once)
3. Pulls `leapable/ocr-provenance-mcp:latest` (~350MB new layers)
4. Starts container with GPU auto-detection (`--runtime=nvidia --gpus all`, falls back to CPU)
5. Auto-provisions a license key
6. Registers with detected AI clients (Claude, Cursor, Windsurf)

Updates: `npx -y ocr-provenance-mcp update` pulls only the app image (~350MB).

---

## Container Start: GPU Auto-Detection

Every container start follows this pattern (wrapper, compose, and release scripts all use it):

```
1. Try: docker run --runtime=nvidia --gpus all -e NVIDIA_VISIBLE_DEVICES=all ...
2. If NVIDIA runtime not found → retry without GPU flags
3. Inside container: entrypoint runs gpu_utils.py to resolve TORCH_DEVICE=auto → cuda:0 or cpu
4. Log clearly: "[docker] GPU passthrough enabled." or "[docker] GPU not available, running on CPU."
```

There is NO config flag, NO env var, NO setting to toggle GPU. It is always attempted.

---

## Automated Release Script

```bash
export DOCKERHUB_TOKEN=dckr_pat_xxxxx

./scripts/docker-release.sh              # Build & push app image
./scripts/docker-release.sh --dry-run    # Build only, don't push
./scripts/docker-release.sh --skip-test  # Skip smoke test
```

---

## Credentials

| Service | Login | Auth Method | Cleanup |
|---------|-------|-------------|---------|
| Docker Hub | `docker login -u leapable` | Access token | `docker logout` after push |
| npm | Write token to `~/.npmrc` | Access token | **`rm -f ~/.npmrc` immediately after publish** |

**Never leave `~/.npmrc` on disk after publishing.** Set the token, publish, delete the file — all in the same step. The `.gitignore` blocks `.npmrc` from being committed, but tokens on disk are still a security risk.

---

## Troubleshooting

### GPU not detected inside container
1. Verify host GPU: `nvidia-smi` must show GPU
2. Verify Docker runtime: `docker info | grep nvidia` must show nvidia runtime
3. Container must start with `--runtime=nvidia --gpus all`
4. CUDA PyTorch must be in the models image (not CPU-only torch)

### Container starts on CPU despite having GPU
- Check: `docker logs ocr-provenance-mcp | grep TORCH_DEVICE`
- If "auto -> cpu": the CUDA runtime libs are missing from the base image
- Fix: rebuild models image (it uses nvidia/cuda base with CUDA PyTorch by default)

### App image push is 26GB instead of 350MB
- Models image must be pushed FIRST so Docker Hub has the base layers
- Push order: models → app
- Look for "Mounted from leapable/ocr-provenance-models" in push output

### Build cache bloat
- Run `docker builder prune -af` after builds to reclaim cache
- Run `docker system prune -af` to remove all unused images/containers

### Dashboard not found during build
- Dashboard repo must exist at `../ocrprovenance-cloud`

---

## Docker Cleanup (Before and After Release)

There should be exactly **2 images** on the host: 1 models base + 1 app. No old versions, no dangling images, no stopped containers consuming disk.

### Pre-release cleanup

```bash
# Stop and remove old container
docker stop ocr-provenance-mcp 2>/dev/null
docker rm ocr-provenance-mcp 2>/dev/null

# Remove old app image (keeps models base)
docker images leapable/ocr-provenance-mcp --format '{{.ID}} {{.Tag}}' | \
  grep -v "$(node -e "console.log(require('./package.json').version)")" | \
  awk '{print $1}' | xargs -r docker rmi 2>/dev/null

# Remove dangling images and build cache
docker image prune -f
docker builder prune -af
```

### Post-release verification

```bash
# Should show exactly 2 images: models:v1 + mcp:latest/version
docker images | grep -E "ocr-provenance"

# Should show exactly 1 running container
docker ps | grep ocr-provenance

# Should show no stopped containers
docker ps -a --filter "status=exited" | grep ocr-provenance && echo "WARN: stopped containers found" || echo "OK: no stopped containers"

# Check disk usage
docker system df
```

### Nuclear cleanup (reclaim all Docker disk space)

```bash
docker stop ocr-provenance-mcp 2>/dev/null
docker rm ocr-provenance-mcp 2>/dev/null
docker system prune -af --volumes  # WARNING: removes ALL unused images, containers, volumes
```

Note: `--volumes` removes the named volume `ocr-provenance-mcp-data` which contains the license key, machine ID, secrets, and all databases. Only use this if you want a complete fresh start.
