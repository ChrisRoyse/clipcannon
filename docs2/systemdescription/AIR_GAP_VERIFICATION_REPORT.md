# Air-Gapped Data Security: Comprehensive Proof Methods for Enterprise Clients

> **Audit Date**: 2026-03-20 | **System**: OCR Provenance MCP v1.2.66 | **Tools**: 153 | **Tests**: 3700+

## Executive Summary

This report catalogs every available method to **prove** that a Docker-based, local GPU document processing system (OCR, VLM, embedding generation) processes data entirely on-premise with zero data exfiltration. Methods are organized from strongest (cryptographic/mathematical proof) to weakest (contractual/verbal assurance), each rated by cost, effort, and whether the client can verify independently.

**Target audience**: CISOs, enterprise security teams, procurement, and compliance officers.

**Key principle**: The strongest proof mechanisms are those the client can verify themselves, without trusting the vendor. Every recommendation below is designed around that principle.

---

## Forensic Audit: Complete Network Call Inventory

Before discussing proof methods, here is a forensic audit of every network call in the system, established by reading every source file in the codebase.

### Category A: Network Calls During Document Processing

**Result: ZERO outbound network calls during OCR, VLM, or embedding processing.**

Evidence from source code analysis:

| Worker | File | Network Imports | Network Calls | Verdict |
|--------|------|-----------------|---------------|---------|
| **OCR** | `python/ocr_worker_local.py` | ZERO (`requests`, `urllib`, `httpx`, `aiohttp`, `socket` all absent) | ZERO | CLEAN |
| **VLM** | `python/vlm_worker_local.py` | ZERO | ZERO | CLEAN |
| **Embedding** | `python/embedding_worker.py` | ZERO (model loaded with `local_files_only=True`) | ZERO | CLEAN |
| **GPU Utils** | `python/gpu_utils.py` | ZERO | ZERO | CLEAN |
| **Reranker** | `python/reranker_worker.py` | ZERO (model loaded with `local_files_only`) | ZERO | CLEAN |
| **Spreadsheet Prep** | `python/spreadsheet_prepare.py` | ZERO (openpyxl/xlrd only) | ZERO | CLEAN |

**Docker-level enforcement**:
- `HF_HUB_OFFLINE=1` — prevents HuggingFace Hub from making any HTTP request
- `TRANSFORMERS_OFFLINE=1` — prevents transformers library from downloading anything
- `MODEL_CHECKPOINT=/opt/models/chandra` — prevents Chandra from reaching HuggingFace
- All 3 models (~24GB) are baked into the Docker image at build time — zero runtime downloads

**TypeScript bridge layer** (Marker, Chandra, Nomic clients): Communicates with Python workers exclusively via `child_process.spawn()` + stdin/stdout JSON protocol. No `fetch()`, no `axios`, no HTTP calls.

**Document Viewer** (v1.2.64+): The viewer API uses LibreOffice headless (`--headless --norestore`) for Office→PDF conversion and Pillow for TIFF→PNG. Both are local-only command-line invocations. LibreOffice runs with no network access and `--norestore` prevents any restore-from-cloud behavior. No document data is transmitted externally.

### Category B: Network Calls for Billing/Licensing (Expected, Contains NO Document Data)

These calls are part of the commercial licensing system. They communicate with `api.ocrprovenance.com` (Cloudflare Worker). **No document content, OCR text, embeddings, or VLM descriptions are ever transmitted.**

| Call | When | Data Sent | Document Data? |
|------|------|-----------|----------------|
| `POST /v1/secrets/bootstrap` | Container startup | `machine_id` (random hex) | NO |
| `POST /v1/charge/authorize` | Per document processed | `license_key`, `amount_cents`, `document_hash` (SHA-256 hash only) | SHA-256 HASH ONLY |
| `POST /v1/charge/refund` | On processing error | `license_key`, `charge_id` | NO |
| `POST /v1/balance/sync` | Every 60 seconds | `key_hash` | NO |
| `POST /v1/checkout/create` | User clicks "Add Funds" | `amount_cents`, `email` | NO |
| `POST /emails` (Resend API) | User requests magic link | `email`, `login_link` | NO |

**Cloud proxy header processing**: When deployed behind a reverse proxy (RunPod, Vast.ai), the license server reads `X-Forwarded-Host` and `X-Forwarded-Proto` headers to determine the public URL for Stripe callbacks and magic link emails. This is HTTP header processing only — no document data is involved.

**Critical note on `document_hash`**: This is a SHA-256 hash of the file, not the file content. The hash cannot be reversed to reconstruct the document. However, it is a unique fingerprint that enables frequency analysis. For fully air-gapped deployments, this call can be eliminated (see "Air-Gap Deployment Mode" below).

### Category C: Telemetry, Analytics, Tracking

**Result: ZERO telemetry, analytics, or tracking of any kind.** No Sentry, Mixpanel, Amplitude, Segment, Google Analytics, or any other tracking library exists in the codebase.

### Category D: Identified Gaps and Risks

| ID | Severity | Finding | Mitigation |
|----|----------|---------|------------|
| D1 | MEDIUM | Charge authorization sends document SHA-256 hash to Cloudflare Worker | Hash cannot reconstruct content. Eliminable in air-gap mode. |
| D2 | LOW | `machine_id` correlated with charges enables processing profile | Standard SaaS licensing. Eliminable in air-gap mode. |
| D3 | LOW | Embedding model loaded with `trust_remote_code=True` | Mitigated by `local_files_only=True` + `HF_HUB_OFFLINE=1` + pinned revision hash |
| D4 | INFO | No runtime network firewall enforcement on Python workers | Workers have zero network imports. Defense-in-depth gap only. |

### Air-Gap Deployment Mode (Recommended for Security-Sensitive Clients)

For clients requiring mathematical proof of zero egress, the system supports a fully air-gapped mode:

```bash
# Option 1: Hard network kill (batch processing only)
docker run --network=none \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --read-only \
  -v /data:/data \
  leapable/ocr-provenance-mcp:latest

# Option 2: Localhost-only with iptables egress block (MCP HTTP mode)
# See Tier 1.3 below for full implementation
```

In air-gap mode, billing is disabled (unlimited local processing with a site license key), eliminating ALL Category B network calls. The result is **mathematically provable zero-egress processing**.

---

## Table of Contents

1. [Tier 1: Network-Level Proof (Zero Egress)](#tier-1-network-level-proof-zero-egress)
2. [Tier 2: Runtime Monitoring and Audit](#tier-2-runtime-monitoring-and-audit)
3. [Tier 3: Supply Chain Integrity](#tier-3-supply-chain-integrity)
4. [Tier 4: Container Hardening and Isolation](#tier-4-container-hardening-and-isolation)
5. [Tier 5: Compliance Certifications and Third-Party Audits](#tier-5-compliance-certifications-and-third-party-audits)
6. [Tier 6: Canary and Honeypot Methods](#tier-6-canary-and-honeypot-methods)
7. [Tier 7: Architectural Proof Mechanisms](#tier-7-architectural-proof-mechanisms)
8. [Tier 8: What Enterprise Security Teams Actually Want](#tier-8-what-enterprise-security-teams-actually-want)
9. [Tier 9: Competitor Analysis](#tier-9-competitor-analysis)
10. [Implementation Priority Matrix](#implementation-priority-matrix)
11. [Appendix: Compliance Framework Mapping](#appendix-compliance-framework-mapping)

---

## Tier 1: Network-Level Proof (Zero Egress)

These methods provide the strongest, most independently verifiable proof that no data leaves the host machine during document processing.

### 1.1 Docker `--network=none` (Hard Network Kill)

**What it proves**: The container has **zero network interfaces** except loopback (127.0.0.1). No DNS resolution, no TCP/UDP egress, no data exfiltration path exists at the kernel level.

**How to implement**:
```bash
docker run --network=none \
  --read-only \
  --cap-drop=ALL \
  -v /data/input:/input:ro \
  -v /data/output:/output \
  ocr-provenance-mcp:latest
```

**Verification by client**:
```bash
# From inside the container:
docker exec <container_id> ip link show
# Expected: ONLY "lo" (loopback) interface

docker exec <container_id> ping -c1 8.8.8.8
# Expected: "Network is unreachable"

docker exec <container_id> curl https://example.com
# Expected: connection failure
```

**Cost/effort**: Zero. Built into Docker Engine.
**Client-verifiable**: YES - client runs the verification commands themselves.
**Standards satisfied**: NIST 800-190 (container network isolation), CIS Docker Benchmark 5.29.

**Limitation**: When `--network=none` is used, the MCP server cannot listen on a port for HTTP transport. This mode is suitable for batch/CLI processing. For MCP HTTP mode, use the iptables approach (1.3) or localhost-only binding (1.4) instead.

### 1.2 tcpdump / Packet Capture Proof

**What it proves**: Complete, timestamped, cryptographic record of every packet entering or leaving the container's network namespace. An empty capture during a processing run proves zero egress.

**How to implement**:
```bash
# Capture ALL traffic on the Docker bridge during processing
tcpdump -i docker0 -w /evidence/capture_$(date +%s).pcap \
  'src net 172.17.0.0/16 and not dst net 172.17.0.0/16' &
TCPDUMP_PID=$!

# Run document processing
docker exec <container_id> process_documents /input/

# Stop capture
kill $TCPDUMP_PID

# Verify: zero outbound packets
tcpdump -r /evidence/capture_*.pcap | wc -l
# Expected: 0 packets
```

**For `--network=none` containers**: There is no network interface to capture on, which is itself proof. The absence of a capture interface IS the evidence.

**Client-side verification script**:
```bash
#!/bin/bash
# air_gap_test.sh - Client runs this on their infrastructure
echo "=== Air-Gap Verification Test ==="
echo "Starting packet capture on ALL interfaces..."
tcpdump -i any -w /tmp/airgap_test.pcap &
PID=$!
sleep 2

echo "Processing test document..."
docker exec ocr-container process /input/test_document.pdf

echo "Stopping capture..."
kill $PID
sleep 1

PACKETS=$(tcpdump -r /tmp/airgap_test.pcap \
  'src net 172.17.0.0/16 and not dst net 172.17.0.0/16 and not dst 127.0.0.0/8' \
  2>/dev/null | wc -l)

if [ "$PACKETS" -eq "0" ]; then
  echo "PASS: Zero outbound packets detected"
else
  echo "FAIL: $PACKETS outbound packets detected"
  tcpdump -r /tmp/airgap_test.pcap -nn
fi
```

**Cost/effort**: Minimal. tcpdump is pre-installed on most Linux systems.
**Client-verifiable**: YES - client runs capture on their own host.
**Standards satisfied**: SOC 2 (monitoring controls), NIST 800-53 SI-4 (information system monitoring).

### 1.3 iptables / nftables Firewall Rules (Kernel-Level Block)

**What it proves**: Even if the container has a network interface (needed for localhost MCP communication), the Linux kernel will DROP all non-localhost egress packets. This is enforced at the kernel level, below the application.

**How to implement**:
```bash
# Get container's veth interface
CONTAINER_ID=$(docker inspect -f '{{.Id}}' ocr-container)
VETH=$(ip link | grep "veth" | grep "$CONTAINER_ID" | awk '{print $2}' | tr -d ':@')

# Block ALL egress except localhost and established connections
iptables -I DOCKER-USER -i $VETH -d 0.0.0.0/0 -j DROP
iptables -I DOCKER-USER -i $VETH -d 127.0.0.0/8 -j ACCEPT
iptables -I DOCKER-USER -i $VETH -d 172.17.0.0/16 -j ACCEPT  # Docker internal only

# Log any blocked attempts (evidence)
iptables -I DOCKER-USER -i $VETH -d 0.0.0.0/0 -j LOG \
  --log-prefix "AIRGAP-VIOLATION: " --log-level 4
```

**Verification by client**:
```bash
# View active rules
iptables -L DOCKER-USER -n -v

# Check kernel logs for any violation attempts
dmesg | grep "AIRGAP-VIOLATION"
# Expected: no entries during processing
```

**Cost/effort**: Low. Standard Linux networking.
**Client-verifiable**: YES - client inspects their own firewall rules.
**Standards satisfied**: NIST 800-53 SC-7 (boundary protection), CIS Docker Benchmark.

### 1.4 Localhost-Only Binding (Host Network Restriction)

**What it proves**: The MCP server only listens on 127.0.0.1, making it unreachable from any external network. Combined with egress blocking, this creates bidirectional isolation.

**How to implement**:
```typescript
// Already implemented in the system:
// MCP server binds 127.0.0.1 locally, 0.0.0.0 in Docker (container-internal only)
const host = process.env.DOCKER_MODE ? '0.0.0.0' : '127.0.0.1';
server.listen(port, host);
```

**Verification by client**:
```bash
# Verify binding
docker exec <container> ss -tlnp | grep LISTEN
# Should show 0.0.0.0:3000 (inside container) but...

# From host: verify container port only maps to localhost
docker port <container>
# Should show: 3000/tcp -> 127.0.0.1:3000 (NOT 0.0.0.0:3000)

# From another machine: verify unreachable
curl http://<host-ip>:3000/health
# Expected: connection refused
```

**Cost/effort**: Zero. Already implemented.
**Client-verifiable**: YES.
**Standards satisfied**: CIS Docker Benchmark 5.13 (bind incoming traffic to specific host interface).

### 1.5 DNS Sinkhole / DNS Blocking

**What it proves**: Even if application code attempts DNS resolution (a prerequisite for almost all data exfiltration), the query will fail.

**How to implement**:
```bash
# Option A: No DNS in container (with --network=none, this is automatic)

# Option B: Custom resolv.conf pointing to nothing
docker run --dns=127.0.0.1 --dns-search=. ocr-provenance-mcp:latest

# Option C: Docker daemon config (/etc/docker/daemon.json)
{
  "dns": ["127.0.0.1"],
  "dns-opts": ["attempts:0"]
}
```

**Verification**:
```bash
docker exec <container> nslookup google.com
# Expected: "connection timed out; no servers could be reached"
```

**Cost/effort**: Zero.
**Client-verifiable**: YES.

---

## Tier 2: Runtime Monitoring and Audit

These methods provide continuous, real-time proof during operation.

### 2.1 Cilium Tetragon (eBPF-Based Runtime Security)

**What it proves**: Kernel-level, tamper-proof monitoring of every system call, network connection, and file access made by the container. Tetragon hooks into the kernel via eBPF, making it impossible for userspace code to evade detection.

**How to implement**:
```yaml
# TracingPolicy for zero-egress enforcement
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: block-container-egress
spec:
  kprobes:
    - call: "tcp_connect"
      syscall: false
      args:
        - index: 0
          type: "sock"
      selectors:
        - matchActions:
            - action: Sigkill  # Kill process that attempts network connection
          matchArgs:
            - index: 0
              operator: "NotEqual"
              values:
                - "127.0.0.1"
```

**What Tetragon monitors**:
- `process_exec` / `process_exit` - every process started in the container
- `tcp_connect` / `udp_sendmsg` - every network connection attempt
- `open` / `openat` - every file access
- `process_kprobe` - custom kernel hook points

**Evidence format**: JSON event stream with full Kubernetes/container metadata:
```json
{
  "process_kprobe": {
    "process": {"binary": "/usr/bin/python3", "pod": {"container": {"id": "abc123"}}},
    "function_name": "tcp_connect",
    "args": [{"sock_arg": {"daddr": "142.250.80.46", "dport": 443}}],
    "action": "SIGKILL"
  }
}
```

**Cost/effort**: Medium. Tetragon is open source (CNCF). Requires kernel 4.19+.
**Client-verifiable**: YES - client deploys Tetragon on their own infrastructure.
**Standards satisfied**: NIST 800-53 AU-2 (event logging), SI-4 (system monitoring), AC-4 (information flow enforcement).

### 2.2 Falco (Cloud-Native Runtime Security)

**What it proves**: Real-time detection and alerting on anomalous container behavior, including unexpected network connections, file access, and process execution.

**How to implement**:
```yaml
# /etc/falco/rules.d/airgap-rules.yaml
- rule: Container Outbound Connection
  desc: Detect any outbound network connection from OCR container
  condition: >
    evt.type in (connect, sendto, sendmsg) and
    container.name = "ocr-provenance-mcp" and
    fd.net != "127.0.0.0/8" and
    fd.net != "172.17.0.0/16"
  output: >
    AIRGAP VIOLATION: Outbound connection from OCR container
    (user=%user.name command=%proc.cmdline connection=%fd.name
     container=%container.name image=%container.image.repository)
  priority: CRITICAL
  tags: [network, airgap, compliance]

- rule: Container DNS Query
  desc: Detect DNS resolution attempt from OCR container
  condition: >
    evt.type in (connect, sendto) and
    container.name = "ocr-provenance-mcp" and
    fd.sport = 53
  output: >
    AIRGAP VIOLATION: DNS query from OCR container
    (command=%proc.cmdline connection=%fd.name)
  priority: CRITICAL

- rule: Container Process Unexpected
  desc: Detect unexpected processes in OCR container
  condition: >
    spawned_process and
    container.name = "ocr-provenance-mcp" and
    not proc.name in (python3, node, marker, chandra)
  output: >
    SUSPICIOUS: Unexpected process in OCR container
    (user=%user.name command=%proc.cmdline)
  priority: WARNING
```

**Cost/effort**: Low-Medium. Falco is open source (CNCF graduated project).
**Client-verifiable**: YES - client runs Falco on their own host.
**Standards satisfied**: NIST 800-53 AU-6 (audit review/analysis), SI-4, CIS Docker Benchmark.

### 2.3 Sysdig (Commercial Runtime Security)

**What it proves**: Enterprise-grade container forensics with compliance reporting, policy enforcement, and incident response capabilities.

**Key features for air-gap proof**:
- Network topology maps showing zero external connections
- Compliance dashboards mapped to NIST, CIS, SOC 2
- Forensic capture of all system calls during processing
- Runtime vulnerability scanning

**Cost/effort**: Commercial license ($15-50/node/month).
**Client-verifiable**: YES - deployed on client infrastructure.
**Standards satisfied**: SOC 2, NIST 800-53, PCI-DSS, HIPAA.

### 2.4 Audit Logging (Built-In Provenance Chain)

**What it proves**: Every document processing action is recorded in an immutable, hash-chained audit log with SHA-256 provenance chains. Tampering at any point breaks the chain.

**Already implemented in the system**:
```
Provenance chain: DOCUMENT(0) -> OCR_RESULT(1) -> CHUNK(2)/IMAGE(2) -> EMBEDDING(3)/VLM_DESC(3) -> EMBEDDING(4)

chain_hash = SHA-256(content_hash + ":" + parent.chain_hash)
```

**How clients verify**:
```bash
# Verify entire provenance chain integrity
docker exec <container> ocr_provenance_verify --document-id <id>

# Export audit log for independent review
docker exec <container> ocr_export_audit_log --format json > audit.json
```

**Cost/effort**: Zero. Already built into the system.
**Client-verifiable**: YES.
**Standards satisfied**: NIST 800-53 AU-10 (non-repudiation), SOC 2 CC7.2.

---

## Tier 3: Supply Chain Integrity

These methods prove the Docker image contains exactly what is claimed, with no hidden telemetry, backdoors, or data exfiltration code.

### 3.1 Cosign Image Signing (Sigstore)

**What it proves**: The container image was built by a specific identity (verified via OIDC), has not been tampered with since signing, and the signing event is recorded in a public transparency log (Rekor).

**How to implement**:
```bash
# Sign during CI/CD build
cosign sign --yes \
  docker.io/leapable/ocr-provenance-mcp:latest

# Generate and sign SBOM attestation
cosign attest --yes \
  --predicate sbom.spdx.json \
  --type spdxjson \
  docker.io/leapable/ocr-provenance-mcp:latest

# Generate and sign provenance attestation
cosign attest --yes \
  --predicate provenance.slsa.json \
  --type slsaprovenance \
  docker.io/leapable/ocr-provenance-mcp:latest
```

**Client verification**:
```bash
# Verify image signature
cosign verify \
  --certificate-identity=ci@ocr-provenance.dev \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  docker.io/leapable/ocr-provenance-mcp:latest

# Verify SBOM attestation
cosign verify-attestation \
  --type spdxjson \
  --certificate-identity=ci@ocr-provenance.dev \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  docker.io/leapable/ocr-provenance-mcp:latest
```

**Cost/effort**: Low. Cosign is free and open source. Integration into GitHub Actions takes ~30 minutes.
**Client-verifiable**: YES - cosign verify is a single command.
**Standards satisfied**: SLSA L2-L3, Executive Order 14028, NIST 800-53 SA-12 (supply chain protection).

### 3.2 Docker Content Trust (DCT / Notary)

**What it proves**: Image integrity and publisher authentication using a root-of-trust key hierarchy. When DCT is enabled, Docker refuses to pull unsigned images.

**How to implement**:
```bash
# Enable DCT
export DOCKER_CONTENT_TRUST=1

# Sign and push (automatic with DCT enabled)
docker push docker.io/leapable/ocr-provenance-mcp:latest

# Client: enforce signature verification
export DOCKER_CONTENT_TRUST=1
docker pull docker.io/leapable/ocr-provenance-mcp:latest
# Will REFUSE to pull if unsigned
```

**Cost/effort**: Zero. Built into Docker Engine.
**Client-verifiable**: YES.
**Standards satisfied**: NIST 800-190 (image integrity), CIS Docker Benchmark 4.5.

### 3.3 SBOM (Software Bill of Materials)

**What it proves**: Complete, auditable inventory of every software component, library, and dependency in the container image. Enables vulnerability assessment and ensures no unexpected components (telemetry SDKs, analytics libraries) are present.

**How to implement**:
```bash
# Generate SBOM with Syft
syft docker.io/leapable/ocr-provenance-mcp:latest \
  -o spdx-json > sbom.spdx.json

# Generate SBOM with Trivy
trivy image --format spdx-json \
  docker.io/leapable/ocr-provenance-mcp:latest > sbom-trivy.spdx.json

# Attach SBOM to image (via Docker BuildKit)
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  --push \
  -t docker.io/leapable/ocr-provenance-mcp:latest .
```

**Client verification**:
```bash
# Inspect SBOM
docker buildx imagetools inspect \
  docker.io/leapable/ocr-provenance-mcp:latest --format '{{json .SBOM}}'

# Search for suspicious components
cat sbom.spdx.json | jq '.packages[].name' | grep -i "telemetry\|analytics\|sentry\|datadog\|segment\|mixpanel\|amplitude"
# Expected: no results

# Scan for vulnerabilities
trivy sbom sbom.spdx.json --severity CRITICAL,HIGH
```

**SBOM minimum elements (per NTIA/Executive Order 14028)**:
- Supplier name
- Component name and version
- Unique identifier (CPE, PURL)
- Dependency relationships
- Timestamp of SBOM generation
- Author of SBOM

**Cost/effort**: Low. Syft, Trivy are free. SBOM generation adds ~2 minutes to CI/CD.
**Client-verifiable**: YES - client can generate their own SBOM and compare.
**Standards satisfied**: Executive Order 14028, NTIA minimum SBOM elements, NIST 800-53 SA-12, CMMC.

### 3.4 SLSA Framework (Supply-chain Levels for Software Artifacts)

**What it proves**: Graduated levels of supply chain integrity, from basic provenance (L1) to hardened builds with isolation (L3).

**SLSA Levels**:

| Level | Requirement | What It Proves |
|-------|------------|----------------|
| L0 | Nothing | No guarantees |
| L1 | Provenance exists | Build process is documented |
| L2 | Hosted build platform + signed provenance | Prevents post-build tampering |
| L3 | Hardened builds, isolated environments | Prevents build-time compromise, insider threats |

**How to implement SLSA L3**:
```yaml
# GitHub Actions with SLSA provenance generator
name: Release
on:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v6
        with:
          push: true
          tags: docker.io/leapable/ocr-provenance-mcp:${{ github.ref_name }}
          provenance: mode=max
          sbom: true

  provenance:
    needs: build
    uses: slsa-framework/slsa-github-generator/.github/workflows/generator_container_slsa3.yml@v2.1.0
    with:
      image: docker.io/leapable/ocr-provenance-mcp
      digest: ${{ needs.build.outputs.digest }}
    secrets:
      registry-username: ${{ secrets.DOCKERHUB_USERNAME }}
      registry-password: ${{ secrets.DOCKERHUB_TOKEN }}
```

**Cost/effort**: Low-Medium. GitHub Actions integration.
**Client-verifiable**: YES - `slsa-verifier verify-image`.
**Standards satisfied**: SLSA L1-L3, NIST 800-53 SA-12, Executive Order 14028.

### 3.5 in-toto Attestations

**What it proves**: Cryptographic proof that every step in the software supply chain was performed by an authorized entity, in the correct order, with expected inputs and outputs.

**How it works**:
1. Define a supply chain "layout" specifying allowed steps and functionaries
2. Each build step generates a signed "link" attestation
3. Verification checks all links against the layout

**Cost/effort**: Medium. Requires build pipeline integration.
**Client-verifiable**: YES - `in-toto-verify` command.
**Standards satisfied**: CNCF graduated project, SLSA provenance format, NIST 800-53 SA-12.

### 3.6 Reproducible Builds

**What it proves**: Anyone can rebuild the Docker image from source and get a bit-identical result. This proves no hidden code was injected during the build.

**How to implement**:
```dockerfile
# Pin ALL dependencies
FROM python:3.11.9-slim-bookworm@sha256:<exact-digest>
# Use exact package versions
RUN pip install --no-cache-dir \
  marker-pdf==1.10.2 \
  torch==2.5.1+cu124 \
  --index-url https://download.pytorch.org/whl/cu124

# Eliminate non-determinism
ENV SOURCE_DATE_EPOCH=0
ENV PYTHONDONTWRITEBYTECODE=1
```

```bash
# Client rebuilds from source
git clone https://github.com/leapable/ocr-provenance-mcp.git
cd ocr-provenance-mcp
docker buildx build --no-cache -t local-rebuild:test .

# Compare digests
docker inspect --format='{{.Id}}' docker.io/leapable/ocr-provenance-mcp:latest
docker inspect --format='{{.Id}}' local-rebuild:test
# Should match (or diff shows only expected timestamp differences)
```

**Cost/effort**: High. Achieving fully reproducible builds with CUDA/GPU dependencies is difficult.
**Client-verifiable**: YES - client rebuilds from source.
**Standards satisfied**: Reproducible Builds project standards, SLSA L3.

---

## Tier 4: Container Hardening and Isolation

### 4.1 Read-Only Root Filesystem

**What it proves**: The container cannot write to its filesystem, preventing malware installation, configuration changes, or staging of exfiltration payloads.

**How to implement**:
```bash
docker run \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=1g \
  --tmpfs /run:rw,noexec,nosuid \
  -v /data/output:/output:rw \
  ocr-provenance-mcp:latest
```

**Cost/effort**: Low.
**Client-verifiable**: YES - `docker inspect` shows ReadonlyRootfs=true.
**Standards satisfied**: CIS Docker Benchmark 5.12, NIST 800-190.

### 4.2 Capability Drop (Least Privilege)

**What it proves**: The container has no Linux kernel capabilities beyond the absolute minimum. Cannot create raw sockets, modify network config, or perform privileged operations.

**How to implement**:
```bash
docker run \
  --cap-drop=ALL \
  --cap-add=SETUID --cap-add=SETGID \  # Only if needed for user switching
  --security-opt=no-new-privileges:true \
  ocr-provenance-mcp:latest
```

**Verification**:
```bash
docker exec <container> cat /proc/1/status | grep Cap
# CapEff should show minimal capabilities

# Verify no-new-privileges
docker exec <container> grep NoNewPrivs /proc/1/status
# Expected: NoNewPrivs: 1
```

**Cost/effort**: Zero.
**Client-verifiable**: YES.
**Standards satisfied**: CIS Docker Benchmark 5.3/5.4, NIST 800-190, OWASP Docker Security.

### 4.3 Custom Seccomp Profile (Syscall Restriction)

**What it proves**: The container can only execute a whitelist of system calls. Network-related syscalls (beyond what is needed for localhost) can be explicitly blocked.

**How to implement**:
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "syscalls": [
    {
      "names": ["read", "write", "open", "close", "stat", "fstat",
                "mmap", "mprotect", "munmap", "brk", "ioctl",
                "access", "pipe", "clone", "execve", "exit_group",
                "futex", "epoll_wait", "epoll_ctl"],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": ["socket"],
      "action": "SCMP_ACT_ALLOW",
      "args": [
        {"index": 0, "value": 1, "op": "SCMP_CMP_EQ"}
      ],
      "comment": "Allow AF_UNIX sockets only"
    }
  ]
}
```

```bash
docker run --security-opt seccomp=/path/to/ocr-seccomp.json \
  ocr-provenance-mcp:latest
```

**Cost/effort**: Medium. Requires testing to ensure OCR/ML workloads function correctly.
**Client-verifiable**: YES - client can inspect the seccomp profile JSON.
**Standards satisfied**: CIS Docker Benchmark 5.21, NIST 800-53 SC-7.

### 4.4 AppArmor / SELinux Mandatory Access Control

**What it proves**: Kernel-level mandatory access control prevents the container from accessing any resource not explicitly allowed, regardless of what the application code attempts.

**How to implement (AppArmor)**:
```
# /etc/apparmor.d/docker-ocr-provenance
profile docker-ocr-provenance flags=(attach_disconnected) {
  # Deny all network access
  deny network,

  # Allow only specific file paths
  /input/** r,
  /output/** rw,
  /tmp/** rw,
  /usr/lib/** r,
  /usr/local/lib/** r,

  # Deny sensitive host paths
  deny /proc/*/environ r,
  deny /etc/shadow r,
  deny /etc/passwd w,
}
```

```bash
docker run --security-opt apparmor=docker-ocr-provenance \
  ocr-provenance-mcp:latest
```

**Cost/effort**: Medium.
**Client-verifiable**: YES - client inspects AppArmor profile.
**Standards satisfied**: CIS Docker Benchmark 5.1, NIST 800-53 AC-3/AC-4.

### 4.5 gVisor (Application Kernel Sandbox)

**What it proves**: The container runs inside a userspace kernel (Sentry) that intercepts ALL system calls. The container never directly touches the host kernel, providing defense-in-depth even against kernel exploits.

**How to implement**:
```bash
# Install gVisor runtime
apt-get install -y runsc

# Configure Docker to use gVisor
# /etc/docker/daemon.json
{
  "runtimes": {
    "runsc": {
      "path": "/usr/bin/runsc"
    }
  }
}

# Run with gVisor
docker run --runtime=runsc \
  --network=none \
  ocr-provenance-mcp:latest
```

**Limitation**: gVisor may have performance implications for GPU/CUDA workloads. Needs testing.
**Cost/effort**: Medium. Open source but requires runtime change.
**Client-verifiable**: YES.
**Standards satisfied**: NIST 800-190 (defense in depth).

### 4.6 Kata Containers (Hardware-Level VM Isolation)

**What it proves**: Each container runs in its own lightweight VM with a dedicated kernel. Network, I/O, and memory are hardware-isolated via CPU virtualization extensions (VT-x/VT-d).

**How to implement**:
```bash
# Install Kata Containers runtime
apt-get install -y kata-runtime

# Run with Kata
docker run --runtime=kata \
  --network=none \
  ocr-provenance-mcp:latest
```

**Limitation**: GPU passthrough with Kata requires VFIO/IOMMU configuration. More complex than standard Docker.
**Cost/effort**: High. Hardware VM overhead.
**Client-verifiable**: YES.
**Standards satisfied**: DoD IL4/IL5 boundary protection requirements.

### 4.7 Docker Rootless Mode

**What it proves**: The Docker daemon and all containers run without root privileges. Even a container escape cannot gain root access to the host.

**How to implement**:
```bash
# Install rootless Docker
dockerd-rootless-setuptool.sh install

# Verify rootless mode
docker info | grep "Root Dir"
# Should show ~/.local/share/docker (not /var/lib/docker)
```

**Cost/effort**: Low-Medium.
**Client-verifiable**: YES.
**Standards satisfied**: CIS Docker Benchmark 2.1, NIST 800-190.

---

## Tier 5: Compliance Certifications and Third-Party Audits

### 5.1 SOC 2 Type II Audit

**What it proves**: An independent CPA firm has verified that your security controls operate effectively over a 6-12 month period. Covers five trust service criteria: security, availability, processing integrity, confidentiality, privacy.

**What the audit covers for data isolation**:
- Technical segregation controls
- Network access restrictions and monitoring
- Access management and authentication
- Logging and monitoring mechanisms
- Change management procedures
- Incident response processes

**How to obtain**:
1. Select a CPA firm (Deloitte, EY, KPMG, PwC, or smaller firms like A-LIGN, Schellman)
2. Define scope (data isolation and processing integrity are key)
3. Implement controls and operate for 6-12 months
4. Undergo audit examination
5. Receive SOC 2 Type II report

**Cost/effort**: High. $30,000-$150,000 depending on scope and firm. 6-12 month observation period.
**Client-verifiable**: YES - client receives the audit report.
**Standards satisfied**: AICPA Trust Services Criteria.

### 5.2 ISO 27001 Certification

**What it proves**: An accredited certification body has verified that your Information Security Management System (ISMS) meets international standards for confidentiality, integrity, and availability.

**Relevant controls**:
- A.8 Asset management
- A.10 Cryptography
- A.13 Communications security (network isolation)
- A.14 System acquisition, development, and maintenance
- A.18 Compliance

**Cost/effort**: High. $20,000-$100,000+. Annual surveillance audits required.
**Client-verifiable**: YES - certificate is publicly verifiable.
**Standards satisfied**: ISO/IEC 27001:2022.

### 5.3 NIST 800-171 Compliance (for CUI/CMMC)

**What it proves**: Compliance with 110 security requirements for protecting Controlled Unclassified Information (CUI). Required for DoD contractors (mapped to CMMC).

**Relevant control families**:
- **3.1 Access Control** - Limit system access to authorized users
- **3.3 Audit and Accountability** - Create, protect, retain system audit logs
- **3.5 Identification and Authentication** - Authenticate users, devices, processes
- **3.13 System and Communications Protection** - Monitor, control, protect communications at system boundaries
- **3.14 System and Information Integrity** - Identify, report, correct security flaws

**CMMC Levels (v2.0)**:

| Level | Requirements | Assessment | Applicable To |
|-------|-------------|-----------|---------------|
| Level 1 (Foundational) | 17 practices (basic cyber hygiene) | Self-assessment | FCI handling |
| Level 2 (Advanced) | 110 NIST 800-171 practices | Third-party C3PAO assessment | CUI handling |
| Level 3 (Expert) | NIST 800-171 + 800-172 enhanced | Government-led assessment | Highest priority CUI |

**Cost/effort**: Medium-High. Level 2 C3PAO assessment: $50,000-$200,000.
**Client-verifiable**: YES - assessment results shared with client.
**Standards satisfied**: NIST SP 800-171, DFARS 252.204-7012, CMMC 2.0.

### 5.4 FedRAMP Authorization

**What it proves**: US government authorization that cloud/hosted services meet rigorous security requirements. FedRAMP High addresses 421 security controls.

**Impact levels**:
- **Low**: 125 controls (low-impact systems)
- **Moderate**: 325 controls (most government data)
- **High**: 421 controls (critical systems, law enforcement, CUI)

**Note**: FedRAMP is designed for cloud services. For on-premise software, NIST 800-171 / CMMC is more directly applicable. However, FedRAMP High authorization of the underlying platform demonstrates security rigor.

**Cost/effort**: Very High. $500,000-$2M+. 12-18 month process.
**Client-verifiable**: YES - authorization is public on FedRAMP Marketplace.
**Standards satisfied**: NIST 800-53, FedRAMP.

### 5.5 DoD Impact Level 4/5 (IL4/IL5)

**What it proves**: Authorization to process Controlled Unclassified Information (IL4) or National Security Systems data (IL5) per the DoD Cloud Computing Security Requirements Guide.

**IL4 covers**: CUI, including export-controlled data, financial data, PII, law enforcement data, defense information.

**IL5 adds**: Higher-impact CUI, National Security Systems, data requiring US-person access restrictions.

**Key requirements**:
- FedRAMP High as minimum baseline
- Personnel restrictions (US citizens only for IL4/IL5 access)
- Physical location restrictions (US-based infrastructure)
- Enhanced access controls and monitoring

**Cost/effort**: Very High. Requires DISA PA (Provisional Authorization).
**Client-verifiable**: YES - PA letter from DISA.
**Standards satisfied**: DoD Cloud Computing SRG, NIST 800-53, CNSSI 1253.

### 5.6 Independent Penetration Testing

**What it proves**: A qualified third-party security firm has attempted to break the air-gap, exfiltrate data, escape the container, or compromise the system, and failed.

**Scope for air-gap verification**:
1. Container escape attempts
2. Network egress testing (covert channels, DNS tunneling, ICMP tunneling)
3. Side-channel data exfiltration attempts
4. Privilege escalation testing
5. Supply chain tampering attempts
6. GPU memory isolation testing

**How to obtain**:
- Engage firms: NCC Group, Trail of Bits, Cure53, Bishop Fox, Crowdstrike
- Scope: "Prove our container cannot exfiltrate data under any conditions"
- Deliverable: Penetration test report with findings

**Cost/effort**: Medium-High. $20,000-$100,000 per engagement.
**Client-verifiable**: YES - client receives the report (or commissions their own test).
**Standards satisfied**: SOC 2 CC4.1, PCI-DSS 11.3, NIST 800-53 CA-8.

### 5.7 CIS Docker Benchmark Assessment

**What it proves**: Container configuration meets the Center for Internet Security's Docker benchmark, which covers 7 sections with 100+ security checks.

**Key sections**:
1. Host Configuration
2. Docker Daemon Configuration
3. Docker Daemon Configuration Files
4. Container Images and Build File
5. Container Runtime (including network, capabilities, filesystems)
6. Docker Security Operations
7. Docker Swarm Configuration

**How to implement**:
```bash
# Run CIS Docker Benchmark assessment
docker run --net host --pid host --userns host --cap-add audit_control \
  -v /var/lib:/var/lib:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /usr/lib/systemd:/usr/lib/systemd:ro \
  -v /etc:/etc:ro \
  docker/docker-bench-security
```

**Cost/effort**: Low. Free tool, automated assessment.
**Client-verifiable**: YES - client runs the benchmark themselves.
**Standards satisfied**: CIS Benchmark, maps to NIST 800-190.

### 5.8 OpenSCAP Compliance Scanning

**What it proves**: Automated compliance assessment against NIST SCAP standards, DISA STIGs, and CIS benchmarks.

**How to implement**:
```bash
# Install and run OpenSCAP
oscap-docker container <container_id> xccdf eval \
  --profile xccdf_org.ssgproject.content_profile_cis \
  --results scan_results.xml \
  --report scan_report.html \
  /usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml
```

**Cost/effort**: Low. Free, open source. NIST SCAP 1.2 certified.
**Client-verifiable**: YES.
**Standards satisfied**: NIST SCAP, DISA STIGs, CIS.

---

## Tier 6: Canary and Honeypot Methods

These methods provide cryptographic proof that data has NOT been exfiltrated, by embedding detectable markers that would trigger alerts if data left the system.

### 6.1 DNS Canary Tokens

**What it proves**: If any document content is transmitted to an external server, the embedded canary triggers a callback, providing proof of exfiltration. If no callback occurs, it proves data stayed local.

**How to implement**:
1. Generate a unique DNS canary token (e.g., via canarytokens.org or self-hosted)
2. Embed the canary URL in test documents processed through the system
3. Monitor the canary dashboard for triggers

```
# Embed in test document metadata or content:
http://<unique-id>.canarytokens.com/tags/articles/traffic/post.jsp

# If ANY external request is made with this content, the canary fires
```

**Types of canary tokens**:
- **DNS canary**: Triggers on DNS resolution of embedded hostname
- **HTTP canary**: Triggers on HTTP request to embedded URL
- **PDF canary**: Embedded in PDF metadata, triggers on open by unauthorized system
- **Custom DNS**: `<token>.yourdomain.com` - any DNS query proves exfiltration

**Cost/effort**: Very low. Free self-hosted or SaaS options.
**Client-verifiable**: YES - client creates and monitors their own canaries.
**Standards satisfied**: Supports SOC 2 CC6.1 (logical access controls verification).

### 6.2 Honeypot Documents

**What it proves**: Specifically crafted documents with known unique content are processed. If that unique content appears anywhere on the internet (monitored via search engines, paste sites, dark web monitoring), exfiltration is proven. Absence proves isolation.

**How to implement**:
```bash
# Create documents with unique, searchable markers
echo "CONFIDENTIAL-MARKER-$(uuidgen)-$(date +%s)" > honeypot_doc.txt

# Process through the system
docker exec <container> process /input/honeypot_doc.txt

# Monitor for the marker
# - Google Alerts for the UUID
# - Dark web monitoring services
# - Paste site monitoring (PasteBin, etc.)
```

**Cost/effort**: Low.
**Client-verifiable**: YES - client creates their own honeypot content.

### 6.3 Network Canary (Egress Detection)

**What it proves**: A lightweight service monitors for ANY network connection attempt from the container, regardless of whether it succeeds.

**How to implement**:
```bash
# Run a packet sniffer that alerts on any container egress
docker run --net=host --name=egress-monitor \
  -v /alerts:/alerts \
  tcpdump -i docker0 -l \
  'src net 172.17.0.0/16 and not dst net 172.17.0.0/16' \
  | while read line; do
    echo "$(date): EGRESS DETECTED: $line" >> /alerts/violations.log
    # Send alert (email, Slack, PagerDuty, etc.)
  done
```

**Cost/effort**: Very low.
**Client-verifiable**: YES.

---

## Tier 7: Architectural Proof Mechanisms

### 7.1 Source Code Availability / Open Source

**What it proves**: Clients (or their security teams) can read every line of code. No hidden telemetry, no obfuscated data transmission, no "phone home" functionality.

**How to implement**:
- Publish source code on GitHub
- Tag releases corresponding to Docker image versions
- Provide build instructions for client verification

**What clients look for in code review**:
```bash
# Search for network libraries / HTTP clients
grep -r "fetch\|axios\|http\|https\|net\|socket\|dns" src/ --include="*.ts" --include="*.py"

# Search for telemetry / analytics
grep -r "telemetry\|analytics\|tracking\|sentry\|datadog\|segment\|beacon" src/

# Search for encoded/obfuscated strings (potential hidden endpoints)
grep -r "atob\|btoa\|base64\|Buffer.from" src/ --include="*.ts"

# Search for environment variable exfiltration
grep -r "process.env\|os.environ" src/ | grep -v "LOCAL\|PORT\|PATH\|HOME"
```

**Cost/effort**: Low (if already open source). Medium if proprietary code must be made available under NDA.
**Client-verifiable**: YES - highest level of transparency.
**Standards satisfied**: Supports SLSA, supports all audit frameworks.

### 7.2 Deterministic Processing Pipeline

**What it proves**: Given the same input document and model weights, the system produces the same output every time. This proves no external data is being injected or results modified by remote services.

**Verification**:
```bash
# Process same document twice
docker exec <container> process /input/test.pdf --output /output/run1/
docker exec <container> process /input/test.pdf --output /output/run2/

# Compare outputs (should be identical for deterministic models)
diff -r /output/run1/ /output/run2/
sha256sum /output/run1/* /output/run2/*
```

**Note**: Some ML models have non-deterministic elements (GPU floating-point order). Document which outputs are deterministic and which have acceptable variance.

**Cost/effort**: Low.
**Client-verifiable**: YES.

### 7.3 Air-Gap Deployment Mode (Offline-Only Image)

**What it proves**: The Docker image contains ALL models, weights, and dependencies. No downloads required at runtime. The system can operate on a machine with no internet connection whatsoever.

**Current architecture supports this**:
- Marker-pdf models: pre-cached at `~/.cache/datalab/models/` (3.3GB)
- Chandra VLM models: bundled in models image
- Nomic embeddings: bundled in models image
- Two-image architecture: models base (~24GB) + app (~500MB)

**Verification**:
```bash
# 1. Pull images while online
docker pull leapable/ocr-provenance-models:v1
docker pull leapable/ocr-provenance-mcp:latest

# 2. Disconnect from internet (physically or via firewall)
sudo iptables -A OUTPUT -j DROP  # Nuclear option

# 3. Process documents
docker run --network=none leapable/ocr-provenance-mcp:latest \
  process /input/test.pdf

# 4. Verify success
# If processing completes, ALL resources are local
```

**Cost/effort**: Zero. Already the architecture.
**Client-verifiable**: YES - client disconnects their network and tests.
**Standards satisfied**: Supports all air-gap requirements (IL4/IL5, CMMC, FedRAMP High).

### 7.4 GPU Memory Isolation Verification

**What it proves**: GPU memory used for ML inference is not shared with or accessible by other processes, and is properly cleared after processing.

**How to verify**:
```bash
# Check GPU memory before processing
nvidia-smi --query-gpu=memory.used --format=csv

# Process documents
docker exec <container> process /input/sensitive.pdf

# Verify GPU memory is released after processing
nvidia-smi --query-gpu=memory.used --format=csv
# Should return to baseline

# Check no other processes have GPU access
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
# Should show ONLY the OCR container's processes
```

**Cost/effort**: Low.
**Client-verifiable**: YES.

---

## Tier 8: What Enterprise Security Teams Actually Want

Based on vendor risk assessment frameworks (SIG Questionnaire, CAIQ, VSA), enterprise security teams evaluate vendors across these categories. Here is what they want to see, mapped to our air-gap proof methods:

### 8.1 The Vendor Security Assessment Checklist

| What They Ask | What Proves It | Priority |
|--------------|---------------|----------|
| "Where is our data processed?" | `--network=none`, localhost binding, architecture docs | CRITICAL |
| "Does data leave our environment?" | Packet capture, Tetragon logs, canary tokens | CRITICAL |
| "What third-party code is in the product?" | SBOM, Trivy scan, source code access | HIGH |
| "Is the software signed/verified?" | Cosign signatures, Docker Content Trust, SLSA provenance | HIGH |
| "Do you have SOC 2 Type II?" | SOC 2 report | HIGH |
| "Do you have ISO 27001?" | ISO certificate | MEDIUM-HIGH |
| "What happens to data after processing?" | Audit logs, data lifecycle docs, GPU memory clearing | HIGH |
| "Can we audit your code?" | Source code access (open source or under NDA) | HIGH |
| "What are your vulnerability management practices?" | Trivy CI/CD scans, patch policy, SBOM updates | MEDIUM |
| "What encryption is used?" | AES-256 at rest, TLS 1.2+ in transit (for MCP HTTP), Ed25519 signatures | HIGH |
| "What access controls exist?" | RBAC, license key auth, rate limiting | MEDIUM |
| "What logging/monitoring is in place?" | Provenance chain, audit logs, Falco/Tetragon | HIGH |
| "Have you had a penetration test?" | Third-party pentest report | HIGH |
| "What is your incident response plan?" | IR documentation, escalation procedures | MEDIUM |
| "Do you have cyber insurance?" | Policy documentation | LOW-MEDIUM |

### 8.2 The "Zero Trust" Proof Stack (Most Convincing to CISOs)

These are the methods that require NO trust in the vendor. The client verifies everything themselves:

**Level 1 -- Mathematical/Cryptographic Proof** (Strongest):
1. `--network=none` -- kernel-level network isolation (client verifies)
2. Packet capture showing 0 outbound packets (client captures)
3. Cosign image signature verification (client verifies)
4. SBOM inspection for zero telemetry dependencies (client inspects)
5. Reproducible build from source (client rebuilds)

**Level 2 -- Runtime Monitoring** (Strong):
6. Tetragon/Falco eBPF monitoring (client deploys on their infrastructure)
7. iptables egress rules with logging (client configures)
8. DNS canary tokens (client creates their own)
9. CIS Docker Benchmark (client runs assessment)

**Level 3 -- Third-Party Verification** (Trusted):
10. SOC 2 Type II report
11. Independent penetration test report
12. ISO 27001 certificate

**Level 4 -- Vendor-Provided Evidence** (Moderate trust):
13. Source code access
14. Architecture documentation
15. Security white paper

### 8.3 The CISO Decision Matrix

What a CISO weighs when approving software:

| Factor | Weight | How We Address It |
|--------|--------|------------------|
| Data residency guarantee | 30% | `--network=none`, local GPU, all models bundled |
| Independent audit/certification | 25% | SOC 2 Type II, pentest reports, CIS benchmark |
| Verifiable security controls | 20% | Cosign, SBOM, Tetragon, source code access |
| Incident history / reputation | 10% | Clean record, responsible disclosure policy |
| Insurance / liability | 10% | Cyber insurance, contractual guarantees |
| Ease of deployment / maintenance | 5% | Single Docker image, automated setup |

---

## Tier 9: Competitor Analysis

### 9.1 Hyperscience

**Security posture**:
- FedRAMP High Authorization (via Palantir FedSTART partnership, 400+ controls)
- SOC 2 Type II (annual independent audits)
- TX-RAMP Level 2
- Cyber Essentials Plus
- AES-256 encryption at rest, TLS 1.2+ in transit
- AWS KMS + HashiCorp Vault for key management
- Annual penetration testing, continuous vulnerability scanning

**On-premise claims**: Supports on-premise deployment via AWS, GCP, AWS GovCloud. For on-premise, "customers remain responsible for the physical and infrastructure security of their environment." Shared responsibility model.

**Gap**: Hyperscience relies heavily on cloud infrastructure certifications. Their on-premise story is "deploy on your cloud." They do NOT offer true air-gapped, zero-network processing.

### 9.2 ABBYY

**Security posture**:
- ISO 27001 certified
- SOC 2 Type II
- HIPAA compliant
- On-premise deployment available (FineReader Server)

**On-premise claims**: ABBYY FineReader Server is a traditional on-premise product. However, their newer Vantage platform is cloud-first. Security documentation is not prominently published.

**Gap**: ABBYY's on-premise products require traditional server infrastructure. They do not offer containerized air-gap verification tools. No public SBOM, no image signing, no runtime monitoring guidance.

### 9.3 Kofax (now Tungsten Automation)

**Security posture**:
- ISO 27001
- SOC 2 Type II
- On-premise deployment for Kofax Capture and Transformation

**Gap**: Traditional enterprise software deployment. No containerization, no air-gap verification tooling, no SBOM or supply chain security.

### 9.4 Our Competitive Advantage

| Capability | OCR Provenance | Hyperscience | ABBYY | Kofax |
|-----------|---------------|-------------|-------|-------|
| True air-gap (`--network=none`) | YES | No | Partial | Partial |
| Client-verifiable network isolation | YES | No | No | No |
| GPU processing 100% local | YES | No (cloud GPU) | Yes (server) | N/A |
| Signed container images (Cosign) | Planned | Unknown | No | No |
| SBOM published | Planned | Unknown | No | No |
| Open source / source-available | YES | No | No | No |
| SHA-256 provenance chain | YES | Unknown | No | No |
| eBPF runtime monitoring support | YES | No | No | No |
| FedRAMP High | No | Yes | No | No |
| SOC 2 Type II | Planned | Yes | Yes | Yes |

**Key differentiator**: We are the ONLY solution where the client can mathematically prove zero data egress using `--network=none` + packet capture + source code inspection. Competitors require the client to trust the vendor's cloud infrastructure.

---

## Implementation Priority Matrix

### Phase 1: Immediate (0-30 days, $0 cost)

These provide the strongest proof with zero cost:

| Method | Effort | Impact |
|--------|--------|--------|
| Document `--network=none` mode with verification script | 2 days | CRITICAL |
| Provide client-runnable `air_gap_test.sh` script | 1 day | CRITICAL |
| Publish SBOM for every release (Syft/Trivy in CI) | 1 day | HIGH |
| Sign images with Cosign in CI/CD | 1 day | HIGH |
| Add SLSA provenance to Docker builds | 1 day | HIGH |
| Document GPU memory isolation verification | 1 day | MEDIUM |
| Publish seccomp profile for OCR workloads | 2 days | MEDIUM |
| Create CIS Docker Benchmark self-assessment guide | 1 day | MEDIUM |

### Phase 2: Short-Term (30-90 days, <$5,000)

| Method | Effort | Impact |
|--------|--------|--------|
| Write Falco rules for air-gap monitoring | 3 days | HIGH |
| Write Tetragon policies for zero-egress enforcement | 3 days | HIGH |
| Create AppArmor profile for OCR container | 3 days | MEDIUM |
| Implement Docker Content Trust signing | 1 day | MEDIUM |
| Add canary token test suite to documentation | 2 days | MEDIUM |
| Publish reproducible build instructions | 5 days | MEDIUM |
| Enable `--provenance=mode=max` in Docker builds | 1 day | MEDIUM |

### Phase 3: Medium-Term (3-6 months, $30,000-$80,000)

| Method | Effort | Impact |
|--------|--------|--------|
| Commission independent penetration test | 4-6 weeks | CRITICAL |
| Begin SOC 2 Type II readiness assessment | 3-6 months | CRITICAL |
| Achieve SLSA L3 with hardened build pipeline | 2-4 weeks | HIGH |
| OpenSCAP compliance scanning in CI/CD | 1 week | MEDIUM |

### Phase 4: Long-Term (6-18 months, $100,000+)

| Method | Effort | Impact |
|--------|--------|--------|
| Complete SOC 2 Type II audit | 6-12 months | CRITICAL |
| ISO 27001 certification | 12-18 months | HIGH |
| CMMC Level 2 assessment (if pursuing DoD) | 12-18 months | HIGH (DoD) |
| FedRAMP authorization (if pursuing federal) | 18-24 months | HIGH (Federal) |

---

## Appendix: Compliance Framework Mapping

### A.1 NIST 800-53 Control Mapping

| Control | Description | Our Implementation |
|---------|------------|-------------------|
| AC-3 | Access enforcement | License key auth, RBAC, rate limiting |
| AC-4 | Information flow enforcement | `--network=none`, iptables, AppArmor |
| AU-2 | Event logging | Provenance chain, audit logs |
| AU-6 | Audit review and analysis | Falco/Tetragon monitoring |
| AU-10 | Non-repudiation | SHA-256 hash chains, Ed25519 signatures |
| CA-8 | Penetration testing | Third-party pentest (planned) |
| CM-7 | Least functionality | `--cap-drop=ALL`, seccomp, minimal base image |
| IA-2 | User identification | License key authentication |
| SA-12 | Supply chain protection | Cosign, SBOM, SLSA, in-toto |
| SC-7 | Boundary protection | `--network=none`, iptables, localhost binding |
| SC-8 | Transmission confidentiality | TLS 1.2+ for MCP HTTP transport |
| SC-28 | Protection of information at rest | SQLite encryption, HMAC balance integrity |
| SI-4 | System monitoring | Tetragon, Falco, tcpdump |
| SI-7 | Software/firmware integrity | Cosign signatures, Docker Content Trust |

### A.2 CIS Docker Benchmark Mapping

| Check | Description | Status |
|-------|------------|--------|
| 2.1 | Run Docker in rootless mode | Supported |
| 4.1 | Create user for container | Implemented |
| 4.5 | Enable Content Trust | Planned |
| 4.6 | Add HEALTHCHECK | Implemented |
| 5.1 | AppArmor profile | Planned |
| 5.3 | Restrict Linux capabilities | Implemented (`--cap-drop=ALL`) |
| 5.4 | Do not use privileged | Implemented |
| 5.12 | Read-only root filesystem | Supported |
| 5.13 | Bind incoming traffic to specific interface | Implemented (127.0.0.1) |
| 5.21 | Custom seccomp profile | Planned |
| 5.25 | Restrict container from gaining privileges | Implemented (no-new-privileges) |
| 5.29 | Do not use network mode host | Implemented |

### A.3 OWASP Docker Security Checklist

| Category | Recommendation | Status |
|----------|---------------|--------|
| Network | Custom Docker networks (not default bridge) | Implemented |
| Network | Bind published ports to localhost | Implemented |
| Image | Vulnerability scanning in CI/CD | Trivy in CI |
| Image | SBOM generation | Planned |
| Image | Image signing | Planned (Cosign) |
| Runtime | Run as non-root user | Implemented |
| Runtime | Drop ALL capabilities | Supported |
| Runtime | no-new-privileges | Implemented |
| Runtime | Read-only filesystem | Supported |
| Runtime | Resource limits | Configurable |
| Monitoring | Falco/Tetragon for anomaly detection | Planned |
| Secrets | Docker secrets management | Implemented (5 secrets architecture) |

### A.4 CMMC 2.0 Level 2 Relevant Practices

| Practice | Description | Applicability |
|----------|------------|---------------|
| AC.L2-3.1.1 | Limit system access to authorized users | License key auth |
| AC.L2-3.1.3 | Control CUI flow | `--network=none`, boundary protection |
| AU.L2-3.3.1 | Create and retain system audit logs | Provenance chain |
| AU.L2-3.3.2 | Ensure individual accountability | Audit trail with user tracking |
| CM.L2-3.4.6 | Employ least functionality | Minimal container, cap-drop |
| IA.L2-3.5.1 | Authenticate users, processes, devices | License key, session auth |
| SC.L2-3.13.1 | Monitor communications at system boundaries | Tetragon, Falco, tcpdump |
| SC.L2-3.13.5 | Implement subnetworks for public components | Docker network isolation |
| SI.L2-3.14.1 | Identify, report, correct flaws | Trivy scanning, SBOM |
| SI.L2-3.14.6 | Monitor organizational systems | Runtime monitoring |

---

## Summary: The Strongest Proof Package

For maximum CISO confidence, deliver this combined evidence package:

### Tier A: Self-Verifiable by Client (Zero Trust Required)
1. Ship `air_gap_verification.sh` script that client runs on their infrastructure
2. Run with `--network=none` and let client verify with `ip link show`
3. Client captures packets during processing (should be zero)
4. Client inspects SBOM for zero telemetry/analytics dependencies
5. Client verifies image signature with `cosign verify`
6. Client deploys Tetragon/Falco with provided rules
7. Client runs CIS Docker Benchmark assessment

### Tier B: Third-Party Verified
8. SOC 2 Type II report from accredited CPA firm
9. Penetration test report from qualified firm
10. SLSA L3 provenance chain (publicly auditable)

### Tier C: Vendor-Provided (Trust-But-Verify)
11. Full source code access (open source)
12. Security architecture documentation
13. Provenance chain audit export (SHA-256 verifiable)
14. GPU memory isolation test results

**The key message for CISOs**: "You do not need to trust us. Here are the tools to verify our claims yourself. Run `--network=none`, capture packets, inspect our SBOM, verify our signatures, deploy your own runtime monitors. If you find any data leaving your infrastructure, we want to know."

That is the most powerful security statement any vendor can make.
