# RTX 5090 32GB + CUDA 13.1 Technical Reference

## Quick Reference

| Spec | Value |
|------|-------|
| Architecture | Blackwell (GB202) |
| Process | 5nm TSMC |
| CUDA Cores | 21,760 (+33% vs 4090) |
| Tensor Cores | 680 (5th gen) |
| RT Cores | 170 (4th gen) |
| SMs | 170 |
| VRAM | 32GB GDDR7 |
| Bandwidth | 1,792 GB/s (+78% vs 4090) |
| Bus | 512-bit |
| L2 Cache | 98MB |
| TDP | 575W (peaks 600W+) |
| PCIe | 5.0 x16 |
| Compute Cap | 12.0 |

---

## Hardware Capabilities

### Tensor Core Precision Support
| Format | Use Case |
|--------|----------|
| FP64 | HPC, scientific |
| FP32/TF32 | Training |
| FP16/BF16 | Mixed precision training |
| FP8 (E4M3, E5M2) | Fast training/inference |
| INT8 | Quantized inference |
| FP6 | Compact inference |
| **FP4** | Blackwell-exclusive, max throughput |

### FP4 (NVFP4) Details
- 4-bit value + FP8 scale/16 values + FP32 scale/tensor = 4.5 bits effective
- 70% memory reduction vs FP16
- 3x throughput vs FP16
- 25-50x energy efficiency vs H100
- <1% accuracy loss on benchmarks

### Performance vs RTX 4090
| Metric | 5090 | 4090 | Delta |
|--------|------|------|-------|
| FP16 TFLOPS | 209.5 | 165.2 | +27% |
| INT8 TOPS | 3,352 | 1,321 | +154% |
| Memory BW | 1,792 GB/s | 1,008 GB/s | +78% |
| VRAM | 32GB | 24GB | +33% |

---

## CUDA 13.1 Core Features

### CUDA Tile (Major Innovation)
**What**: Tile-based programming abstraction over SIMT. Write operations on data chunks, compiler handles thread mapping, tensor cores, memory hierarchy.

**cuTile Python** (DSL):
```python
import cuda.tile as ct

@ct.kernel
def vector_add(a, b, c, tile_size: ct.Constant[int]):
    pid = ct.bid(0)
    a_tile = ct.load(a, index=(pid,), shape=(tile_size,))
    b_tile = ct.load(b, index=(pid,), shape=(tile_size,))
    ct.store(c, index=(pid,), tile=a_tile + b_tile)
```

**Benefits**:
- Automatic tensor core utilization
- Architecture-portable (future GPUs auto-optimize)
- 60-80% kernel dev time reduction
- Python-native GPU programming

**Requirements**: Compute cap 10.x/12.x, Driver R580+, Python 3.10+, `pip install cuda-tile`

### Green Contexts
**What**: Static SM partitioning for deterministic latency. Partition GPU at context creation.

**Use Case**: Real-time inference needs 20% SMs with guaranteed availability while background training uses 80%.

**Comparison**:
| Feature | Green Contexts | MIG | MPS |
|---------|---------------|-----|-----|
| Granularity | SM-level | GPU partition | Thread % |
| Reconfiguration | Dynamic | Restart | Dynamic |
| Scope | Single/multi process | Multi-process | Multi-process |

### MPS Enhancements
- **MLOPart**: Single GPU exposed as multiple logical devices (B200, B300)
- **Client limit**: 48 → 60 concurrent clients
- **Static partitioning**: Deterministic QoS allocation

---

## Math Libraries Performance

### cuBLAS
- **Grouped GEMM**: 4x speedup for MoE models (FP8, BF16/FP16)
- **FP4 GEMM**: Native block-scaled on Blackwell
- **FP64/FP32 emulation**: 2x faster via tensor cores
- **CUDA Graph support**: Host-sync-free grouped GEMM

### cuSOLVER
- Batched SYEV: ~2x speedup (eigenvalue problems)
- Dense/sparse/refactorization solvers

### cuSPARSE
- New SpMVOp API: Higher perf than CsrMV
- CSR 32-bit indexing, FP64, user-defined epilogues

### cuFFT
- Device API with host-side query/codegen
- Better Blackwell utilization

### CCCL 3.1 (CUB)
- **Deterministic FP reductions**: GPU-to-GPU or run-to-run bitwise identical
- **Single-phase APIs**: No temp storage query step

---

## AI/ML Capabilities

### LLM Training Memory
| Model | Params | RTX 4090 24GB | RTX 5090 32GB |
|-------|--------|---------------|---------------|
| 7B FP16 | 7B | Tight | Comfortable |
| 13B FP16 | 13B | Very tight | Possible |
| 20B FP16 | 20B | No | With optimization |
| 30B+ INT8 | 30B+ | Limited | Feasible |

### Supported Techniques
- LoRA, QLoRA (parameter-efficient fine-tuning)
- Gradient checkpointing
- Mixed precision (FP16/BF16 + FP32 accumulation)
- FP8 training (emerging)

### Transformer Optimization
- Grouped GEMM: 4x MoE speedup
- Attention auto-mapped to tensor cores via CUDA Tile
- Variable sequence handling

### Inference Benchmarks (Est.)
| Model | Precision | RTX 4090 | RTX 5090 |
|-------|-----------|----------|----------|
| Llama 2 7B | FP16 | 45 tok/s | 60 tok/s |
| Llama 2 13B | FP16 | 25 tok/s | 35 tok/s |
| Llama 2 70B | INT8 | 8 tok/s | 12 tok/s |
| Mixtral 8x7B | FP16 | 30 tok/s | 50 tok/s |

### Training Benchmarks (Est.)
| Task | RTX 4090 | RTX 5090 |
|------|----------|----------|
| ResNet-50 | 820 img/s | 1100 img/s |
| BERT Fine-tune | 185 seq/s | 250 seq/s |
| ViT-B/16 | 340 img/s | 470 img/s |

---

## Scientific Computing

### Molecular Dynamics
- NAMD: 1.4-2.2x speedup vs Ada
- System scales: 10K-10M atoms
- Apps: Protein folding, drug-target binding, materials

### Protein Folding
- AlphaFold2 + TensorRT + MMseqs2-GPU: **131.4x speedup**
- ColabFold: **5.94x speedup**
- 32GB enables full human proteome (42K+ proteins)
- Boltz-2 NIM for AlphaFold3-style predictions

### Other Domains
- **CFD**: Navier-Stokes, aerodynamics, weather
- **FEA**: Structural analysis, cuSOLVER/cuSPARSE
- **Quantum Chemistry**: DFT, Hartree-Fock, coupled cluster
- **Plasma Physics**: PIC methods, fusion research

---

## Neuromorphic & Knowledge Graphs

### SNN Simulation
- 32GB: Large cortical networks
- cuSPARSE: Sparse connectivity
- Tensor cores: Synaptic weight updates
- Green Contexts: Isolate neuromorphic from symbolic
- 10-100x faster than CPU Brian2

### Knowledge Graphs / GNNs
- Billion-edge graphs in memory
- cuSPARSE: Message passing, attention
- Full-batch training (no sampling needed)
- Node2Vec, TransE, RotatE embeddings
- Neo4j export → GPU processing → embeddings

### Hybrid Architecture Pattern
```
Green Context A (70% SMs): SNN Processing
     ↓
Spike Pattern Recognition
     ↓
Green Context B (30% SMs): Symbolic KG Query
     ↓
Action Selection
```

---

## Media Processing

### NVENC (Hardware Encoder)
| Codec | Max Res | Color Spaces | Bit Depth |
|-------|---------|--------------|-----------|
| H.264 | 4K | 4:2:0/4:2:2/4:4:4 | 8/10-bit |
| HEVC | 8K | 4:2:0/4:2:2/4:4:4 | 8/10-bit |
| AV1 | 8K | 4:2:0 | 8/10-bit + UHQ mode |

- 5x faster than x264
- Async (no CUDA interference)
- Multi-stream support

### Audio/Speech
- Kaldi GPU: 10x+ speedup, real-time ASR
- Whisper: Multi-language, fast transcription
- DSP: Convolution reverb, EQ, compression on GPU

---

## Climate & Weather

### NVIDIA Earth-2
- **cBottle**: 5km global resolution, 3000x data compression, minutes vs weeks
- **FourCastNet 3**: 15-day forecast in ~1 min
- **CorrDiff**: 25km→2km, 1000x faster, 3000x energy efficient

---

## Developer Tools

### Nsight Compute 2025.4
- CUDA Tile kernel profiling
- Tile statistics views
- Source-level metrics
- Roofline analysis
- Expert system recommendations

```bash
ncu --set full -o profile ./app
```

### Nsight Systems
- System-wide timeline
- CPU-GPU synchronization analysis
- Multi-GPU profiling

### Error Detection
- Compile-time memcheck in NVCC
- CUDA-GDB for kernel debugging
- Compute Sanitizer for race detection

---

## System Requirements

### Power
| Config | Min PSU | Recommended |
|--------|---------|-------------|
| Single GPU | 1000W | 1200W 80+ Platinum |
| Overclocking | 1200W | 1500W 80+ Titanium |
| Dual GPU | 2000W+ | 200-240V circuit |

**Connector**: 12V-2×6 (ATX 3.1)

### Cooling
- 2-slot FE handles 575W
- GPU: ~72°C under load
- VRAM: 89-90°C (warm but in spec)
- Liquid cooling: -5-15°C, quieter, OC headroom

### Software
- OS: Windows 10/11, Linux (Ubuntu 22.04+, RHEL 8+)
- Driver: R580+ (R590 for full Tile support)
- Compilers: MSVC 2022, GCC 15, Clang 20

### Recommended Pairing
| Use Case | CPU | RAM |
|----------|-----|-----|
| AI/ML | Core Ultra 9 285K / Ryzen 9 9950X | 64-128GB DDR5-6000 |
| Scientific | i9-14900KS / TR 7970X | 128GB+ |
| Content | Core Ultra 9 285K / Ryzen 9 9950X3D | 64GB DDR5-5600 |

---

## CUDA Best Practices

### Memory
```cuda
// Good: Async transfer + stream
cudaMemcpyAsync(d_data, h_data, size, cudaMemcpyHostToDevice, stream);
kernel<<<grid, block, 0, stream>>>(d_data);

// Bad: Sync blocking
cudaMemcpy(d_data, h_data, size, cudaMemcpyHostToDevice);
kernel<<<grid, block>>>(d_data);
cudaDeviceSynchronize();
```

### Launch Config
- Block: 128-256 threads (multiples of 32)
- Grid: Fill GPU
- Target 80-100% occupancy

### Access Patterns
```cuda
// Good: Coalesced
int idx = threadIdx.x + blockIdx.x * blockDim.x;
output[idx] = input[idx];

// Bad: Strided
int idx = threadIdx.x * stride;
```

### Optimization Checklist
- [ ] Profile with Nsight Compute
- [ ] >80% occupancy
- [ ] Coalesced memory access
- [ ] Minimize host-device transfers
- [ ] Use streams for concurrency
- [ ] Shared memory for reused data
- [ ] FP16/BF16 when possible
- [ ] Minimize warp divergence
- [ ] __restrict__ pointers

---

## Performance Summary

### Memory-Bound Ops (1.78x BW advantage)
| Op | RTX 4090 | RTX 5090 | Speedup |
|----|----------|----------|---------|
| Vector Add | 850 GB/s | 1500 GB/s | 1.76x |
| Reduction | 680 GB/s | 1250 GB/s | 1.84x |

### Compute-Bound Ops
| Op | RTX 4090 | RTX 5090 | Speedup |
|----|----------|----------|---------|
| FP32 GEMM | 82.6 TFLOPS | ~110 TFLOPS | 1.33x |
| Grouped GEMM (MoE) | baseline | 4x | 4.0x |

### Power Efficiency
- INT8 TOPS/W: 5.83 (2x improvement)
- FP4 on Blackwell: 25-50x vs H100 FP16

---

## Value Proposition

| vs | Comparison |
|----|------------|
| RTX 4090 | +33% cores, +78% BW, +33% VRAM, FP4 support |
| RTX PRO 6000 | 80-90% capability at 25% price |
| H100 | Desktop-scale dev, portable CUDA Tile code |
| A100 | Better for dev/research, deploy to cloud |

### Future-Proofing
- CUDA Tile code auto-optimizes for future GPUs
- 32GB handles next-gen model growth
- FP4 ecosystem maturing
- 5th-gen Tensor Cores

---

## Key Takeaways

1. **CUDA Tile** = Write once, run optimized everywhere
2. **Green Contexts** = Deterministic latency for real-time
3. **FP4** = 4x compression, minimal accuracy loss
4. **78% bandwidth increase** = Memory-bound ops fly
5. **32GB** = Train bigger models, larger graphs
6. **cuBLAS grouped GEMM** = 4x MoE speedup
7. **AlphaFold2** = 131x speedup with full pipeline

---

*Compressed from ~25,000 words. All specs, benchmarks, and capabilities preserved.*
*Original: 190 sources. Updated: 2025-12-18*
