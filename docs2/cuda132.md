NVIDIA CUDA Toolkit 13.2, released on March 8, 2026, represents one
of the most consequential updates in the CUDA platform's 20-year
history. The headline feature is the expansion of CUDA Tile —
NVIDIA's paradigm-shifting tile-based programming model — from
Blackwell-only to Ampere and Ada architectures (compute
capability 8.x), instantly making this technology available to millions
of existing GPUs. Alongside this, the release delivers major upgrades
to math libraries (cuBLAS, cuSOLVER), a modernized C++ runtime,
new Python-first developer tools, and deep optimizations for AI
workloads running on Blackwell hardware.[1][2][3]
The practical impact is enormous: Grouped GEMM APIs now support
MXFP8 and deliver 4× speedups for Mixture-of-Experts models; FP64
emulation on Tensor Cores achieves up to 2× speedups for scientific
computing; and the cuTile Python DSL lets developers write GPU
kernels in 15 lines of Python that rival 200 lines of hand-tuned CUDA
C++. When combined with NVFP4 precision on Blackwell Ultra GPUs
— delivering 3× the dense compute of FP8 — the full CUDA 13.x
stack powers inference speedups of 36× for DeepSeek-R1 and 6.3×
for image generation workloads.[4][5][6][3][7]
This report covers every major component of CUDA 13.2, explains the
technical innovations, and provides real-world performance
benchmarks demonstrating profitable applications.
NVIDIA CUDA Toolkit 13.2:
Complete Deep Dive — What's
New, What It Enables, and Why
It's So Powerful
Executive Summary
CUDA Tile is the most fundamental change to GPU programming since
CUDA's inception in 2006. Traditional CUDA programming uses the
SIMT (Single-Instruction Multiple-Thread) model, requiring
developers to manually manage thread indices, thread blocks, shared
memory layouts, warp scheduling, and synchronization. CUDA Tile
replaces this with a tile-centric abstraction where developers
describe operations on structured blocks of data (tiles), and the
compiler automatically maps those operations onto threads, Tensor
Cores, tensor memory accelerators, and the GPU memory hierarchy.
[8][6][9]
The practical consequence: a Flash Attention implementation in
cuTile Python achieves within 10% of peak GPU performance in
roughly 10 lines of code, compared to hundreds of lines of handtuned CUDA C++. This is not just a convenience — it ensures
performance portability across GPU generations, since the compiler
handles the hardware-specific mapping.[10][9]
Prior to CUDA 13.2, CUDA Tile was restricted to Blackwell GPUs
(compute capabilities 10.x and 12.x). CUDA 13.2 expands support to
Ampere (A100, RTX 3000 series) and Ada (RTX 4000 series, L40S)
architectures — compute capability 8.x. NVIDIA has stated that in an
upcoming release, all GPU architectures starting with Ampere will be
fully supported. This instantly democratizes tile-based programming
for the vast installed base of data center and consumer GPUs.[2][3]
The cuTile Python DSL receives significant language feature additions
in 13.2:[3]
Recursive functions — enabling divide-and-conquer algorithms
directly in tile kernels
CUDA Tile: The Paradigm Shift Reaches the
Mainstream
From SIMT to Tile-Based Programming
CUDA 13.2: Ampere and Ada Support
cuTile Python DSL Enhancements
Closures with capture — nested functions and lambda
functions for more expressive code
Custom reduction and scan functions — user-defined parallel
reduction and prefix scan operations
Type-annotated assignments — stronger typing for improved
code clarity
Array.slice — creating views on subarrays without data
copying
pip-installable: pip install cuda-tile[tileiras] — no system-wide
CUDA Toolkit installation required[3]
NVIDIA published a detailed implementation of Flash Attention using
cuTile Python, targeting the B200 GPU. The implementation
demonstrates:[11]
A complete Flash Attention kernel with causal masking and
Grouped Query Attention (GQA) in Python
Advanced optimizations including FMA patterns, fast math, loop
splitting, and adaptive tiling
10–20% performance gains over the baseline for longer
sequences after tuning[11]
The kernel achieves competitive performance against handoptimized Triton and CUDA C++ implementations, with CUDA
implementations showing 10–40% lower runtimes than Triton
on equivalent hardware[12]
This is significant because Flash Attention is the single most critical
kernel in modern LLM inference and training.
The cuBLAS update in CUDA 13.2 is transformative for AI workloads.
Key additions include:[3]
Flash Attention in cuTile: A Case Study
Math Library Upgrades: cuBLAS, cuSOLVER,
and Precision Innovation
cuBLAS 13.3: Grouped GEMM, MXFP8, and NVFP4
Feature Details Impact
Grouped
GEMM
with
MXFP8
Extended experimental
API for Blackwell GPUs
(CC 10.x, 11.0)
4× speedup over multistream GEMM for MoE
models
RTX PRO
6000
optimizatio
n
FP8, FP16/BF16, TF32,
INT8
Up to 20% speedup
DGX Spark
MXFP8/NV
FP4
Large M and N
problem sizes
Up to 3× improvement
FP64 fixedpoint
emulation
Extended to SYRK,
SYR2K, HERK, HER2K
routines
Automatic dispatch for
large problems
Special
values
control
CUBLAS_EMULATION_
SPECIAL_VALUES_SUP
PORT_MASK=0
Performance gain
when infinity/NaN
preservation not
needed
Mixture-of-Experts (MoE) architectures like DeepSeek-V3 (256
experts) have become the dominant design for scaling LLMs without
proportionally increasing compute cost. The core challenge is that
each token is routed to different experts, producing many small
independent GEMMs. Iterating through these with individual kernel
launches creates massive overhead.[13][14][15]
cuBLAS's Grouped GEMM API solves this by executing all expert
GEMMs in a single kernel launch with device-side shapes,
eliminating host synchronization entirely. Combined with CUDA
Graphs support, this delivers 4× speedup over conventional multistream implementations — a direct translation to lower inference
latency and higher throughput for production MoE serving.[3]
Why Grouped GEMM Matters: The MoE Revolution
One of the most innovative features in the CUDA 13.x series is
floating-point emulation, which uses lower-precision Tensor Cores
to emulate higher-precision arithmetic:[7]
FP32 emulation via Blackwell BF16 Tensor Cores (BF16x9
algorithm): Provides 2.4× speedup in the ecTrans weather
forecasting model's matrix product computations while
preserving FP32 accuracy[7]
FP64 emulation via Blackwell INT8 Tensor Cores (Ozaki
Scheme): Delivers 1.5× end-to-end speedup with full accuracy
and up to 3× with tuned mantissa bits (39-bit) in Quantum
Espresso materials science simulations[7]
CUDA 13.2 extends this to cuSOLVER with new FP64-emulated APIs
for QR, LU, and Cholesky factorizations, achieving up to 2× speedup
for QR factorization on B200 GPUs as matrix sizes approach 80K.[3]
While NVFP4 support was introduced in CUDA 12.9/13.0, the full stack
in CUDA 13.2 realizes its potential. NVFP4 delivers:[16][4]
3× more dense compute versus FP8 on Blackwell Ultra GPUs
15 petaFLOPS peak NVFP4 throughput on Blackwell Ultra
Accuracy validated across MLPerf Training and Inference
benchmarks — meeting strict closed-division requirements for
DeepSeek-R1, Llama 3.1 8B/405B, and Llama 2 70B[4]
Industry adoption by Black Forest Labs, Radical Numerics,
Cognition, and Red Hat[4]
The combination of CUDA 13.2's features and Blackwell hardware
creates dramatic performance gains with direct financial
implications:
FP64 Emulation: Unlocking Tensor Cores for Scientific
Computing
NVFP4: The 4-Bit Precision Breakthrough
Highly Profitable Real-World Performance
Examples
Workload Hardware Speedup
Sou
rce
DeepSeek-R1
(671B)
inference
Blackwell
architecture
36× faster, 32× cost
reduction
[5]
FLUX.2 image
generation
Single B200
6.3× speedup with
NVFP4 + CUDA
Graphs
[4]
Llama 3.1 405B
pre-training
512 Blackwell
Ultra GPUs
64.6 minutes (1.9×
faster than FP8)
[4]
ecTrans
weather
forecasting
Blackwell BF16
Tensor Cores
2.4× speedup in
matrix products
[7]
Quantum
Espresso
(Ausurf )
RTX PRO 6000
Blackwell
Server
1.5–3× end-to-end
speedup
[7]
MoE model
inference
Blackwell with
Grouped
GEMM
4× speedup over
multi-stream
[3]
Stable
Diffusion
(Flux)
RTX 5070 Ti
2× faster per
iteration
[17]
Top-K
selection
Any supported
GPU
5× over full radix
sort
[3]
Segmented
reduction
(small)
Any supported
GPU
Up to 66× faster [3]
These performance gains translate directly to profitability:
Inference cost reduction: A 36× inference speedup for
DeepSeek-R1 means serving the same traffic with ~97% fewer
Financial Impact Analysis
GPU-hours, potentially saving millions of dollars per month at
scale.[5]
Training time compression: Training Llama 3.1 405B in ~65
minutes versus hours means researchers can iterate on model
architectures dramatically faster, accelerating time-to-market
for AI products.[4]
Image generation throughput: A 6.3× speedup for FLUX.2 on a
single B200 means a single GPU can serve the workload
previously requiring 6+ GPUs, reducing hardware capex by
~84%.[4]
HPC cost savings: 2–3× speedups in scientific simulations
(weather, materials science) reduce compute budgets
proportionally while enabling higher-resolution models that
were previously infeasible.[7]
CUDA 13.2 ships with CCCL (CUDA Core Compute Libraries) version
3.2, which fundamentally modernizes the C++ interface to CUDA.[3]
The new vocabulary types replace decades of C-style API wrappers
with idiomatic C++:[3]
cuda::stream — RAII stream management
cuda::event — type-safe event handling
cuda::buffer — automatic memory management with pool
support
cuda::launch — simplified kernel launch
cuda::device_ref and cuda::devices — device enumeration and
attribute queries
A complete vector-add example using the new APIs requires roughly
half the code of the traditional approach and eliminates entire
categories of resource-management bugs.[3]
CCCL 3.2: Modern C++ for CUDA
Modern Runtime APIs
Algorithm Description
Performance
Gain
Top-K
(DeviceTopK)
Select K largest/smallest
without full sort
5× over radix
sort for small K
Fixed-size
Segmented
Reduction
Uniform segment_size
eliminates offset
overhead
Up to 66×
(small), 14×
(large)
Segmented Scan
Parallel scan over
independent segments
New capability
Binary Search
Parallel multi-value
search in ordered
sequence
New capability
FindIf
First element satisfying
condition, with early exit
Up to 7× faster
than full search
The Top-K algorithm is particularly important for MoE routing, sparse
attention, and database workloads.[18][3]
CUDA 13.2 introduces Nsight Python, a new profiling interface that
brings NVIDIA's profiling tools directly to Python developers. With
just a few decorators, developers can profile CUDA kernels launched
through Python frameworks, configure sweeps across multiple
parameters, and plot performance comparisons — all without leaving
the Python ecosystem.[3]
For the first time, developers can debug Numba-CUDA GPU kernels
with CUDA-GDB command-line debugging and Nsight Visual
Studio Code Edition. This includes breakpoints, stepping through
New High-Performance Algorithms
Developer Tools Renaissance
Nsight Python: Profiling from Python
Numba-CUDA Debugging
statements, and inspecting program state — capabilities previously
available only for native CUDA C++ kernels.[3]
Report clustering and merging: Understand data from
repeated experiments and multiprocess applications
Register Dependency correlation: Identify source-line
dependencies to locate bottlenecks
CUDA Graphs viewer: Visualize graphs as they're built and
profiled, with visual correlation to collected results[3]
A free AI-powered CUDA coding assistant now available to
everyone with an NVIDIA Developer account.[3]
CUPTI introduces user-defined activity records, allowing developers
to select specific profiling fields instead of collecting entire predefined
records. This provides significant memory efficiency and improved
performance through compact data structures. The feature also adds
MLOPart device tracing and green context allocation tracing for finegrained GPU resource management.[19]
CuPy now supports CUDA 13.x with PyPI wheels (pip install cupycuda13x) and implements the CUDA Stream Protocol for zero-copy
stream sharing with PyTorch and JAX:[3]
# Share a CuPy stream with PyTorch
pytorch_stream = torch.cuda.ExternalStream(cupy_stream)
# Or import an external stream into CuPy
cupy_stream = cupy.cuda.Stream.from_external(pytorch_stream)
Additional Python ecosystem updates include:[3]
Nsight Compute 2026.1
Nsight Copilot
CUPTI 13.2
CUDA Python Ecosystem
CuPy Interoperability
ml_dtypes.bfloat16 support in CuPy for native reducedprecision computation
cuda::std::mdspan views through ndarray.mdspan with 32/64-
bit indexing control
cuda.core 0.6: NVML bindings for GPU monitoring, nvFatbin
bindings, and Pythonic system information access
CUDA Graphs building graduated from experimental —
supporting conditional execution (if_cond, while_loop), fork-join
patterns
CUDA 13.2 continues the unification of the ARM ecosystem. The same
ARM SBSA CUDA Toolkit now works across all ARM targets — from
NVIDIA DGX server-class GPUs down to Jetson Thor and Jetson Orin
embedded devices. This eliminates the need for separate SDKs,
simplifies CI pipelines, and removes subtle bugs from juggling
different toolkits.[3]
CUDA 13.2 introduces MIG (Multi-Instance GPU) support for Jetson
Thor, enabling the integrated GPU to be partitioned into two fully
isolated instances with dedicated memory, cache, and compute
resources. This is designed for mixed-criticality applications in
robotics — isolating safety-critical motor control from heavier
perception or language model workloads.[3]
Windows GPUs now default to MCDM instead of TCC. MCDM brings
features previously reserved for WDDM: WSL2 support, native
containers, advanced memory management APIs (cuMemCreate,
cudaMallocAsync), RDMA, and memory oversubscription.[3]
Platform and Compiler Updates
Unified ARM Ecosystem
Multi-Instance GPU for Jetson Thor
Windows Compute Driver Model (MCDM)
CUDA 13.2 adds official support for AlmaLinux and other enterprise
Linux-compatible distributions, with NVIDIA packages now
distributable directly from AlmaLinux repositories — ensuring driver
and CUDA versions stay in sync.[20][21]
Support for Microsoft Visual Studio 2026 as a host compiler
ACLE (ARM C Language Extensions) support for GCC
Improved C++20 standards conformance including fixes for
constraints, requires-expressions, lambdas, and noexcept
specifications[1]
Enterprise Linux Support
Compiler Updates
Component Version Matrix
Component Version Key Change
CUDA Runtime
(cudart)
13.2.51
Spin-wait dispatch, memcpy
attributes
NVCC Compiler 13.2.51 VS2026, ACLE, unified Tegra
cuBLAS 13.3.0.5
Grouped GEMM MXFP8, FP64
emulation
cuSOLVER 12.1.0.51
FP64 emulation for
QR/LU/Cholesky
cuFFT 12.2.0.37 LTO kernels require NVRTC
cuSPARSE 12.7.9.17
Improved SpMVOp buffer
sizing
CCCL
(Thrust/CUB/libcu+
+)
3.2.0 Top-K, modern C++ APIs
Nsight Compute
2026.1.0.
9
Report merging, register
dependencies
Nsight Systems
2025.6.3.
343
PyTorch profiling, Python
3.14
CUPTI 13.2.23 User-defined activity records
Minimum Linux
Driver
≥595.45.0
4
Required for CUDA 13.2
Several legacy features are cleaned up in CUDA 13.x:[1]
Maxwell, Pascal, and Volta architectures: Offline compilation
and library support removed in CUDA 13.0
Ubuntu 20.04: Support dropped starting with CUDA 13.2
Legacy vector types (double4, long4, ulong4, etc.): Deprecated,
replaced by aligned variants (*_16a, *_32a), removal planned for
CUDA 14.0
Deprecated and Removed Features
Multi-device cooperative launch APIs: Fully removed
(cudaLaunchCooperativeKernelMultiDevice, multi_grid_group)
Legacy texture/surface headers: Removed
(cuda_surface_types.h, cuda_texture_types.h, etc.)
Windows display driver bundling: No longer included; must be
installed separately
Nsight Eclipse Edition plugins: Deprecated, to be dropped in a
future release
CUDA 13.2 is strategically significant for three reasons:
1. Democratization of Tile programming: By extending CUDA
Tile to Ampere and Ada, NVIDIA ensures that the new
programming model — and its performance portability
guarantees — reaches the hundreds of millions of GPUs
already deployed, not just the latest Blackwell hardware. This
locks in CUDA's ecosystem advantage while making GPU
programming accessible to a broader developer base.[9][2]
2. Python as a first-class GPU programming language: Between
cuTile Python, Nsight Python profiling, Numba-CUDA debugging,
CuPy's CUDA 13.x support, and pip-installable tooling, CUDA 13.2
treats Python not as a wrapper language but as a primary
development environment for GPU computing.[8][3]
3. Precision-flexible computing: The FP64/FP32 emulation
techniques, combined with NVFP4 and MXFP8 support, create a
spectrum of precision options that allow developers to trade
precision for performance at extremely fine granularity.
This is the foundation for the next wave of efficiency gains in
both AI and scientific computing.[7][4]
For developers with RTX 5090 hardware like Chris's setup, CUDA 13.2
immediately unlocks cuTile programming, NVFP4 inference
acceleration, and the full suite of new Python-first development tools
— making it one of the most impactful single-toolkit upgrades for
AI/ML development workflows.
Strategic Significance
1. CUDA Toolkit 13.2 - Release Notes - NVIDIA Documentation -
CUDA Math: Release 13.2 . New Features. Accuracy and
performance improvements were made to the follo...
2. CUDA Toolkit - Free Tools and Training | NVIDIA Developer -
Featured Blogs. March 9, 2026. Implementing Falcon-H1 Hybrid
Architecture in NVIDIA Megatron Core.
3. CUDA 13.2 Introduces Enhanced CUDA Tile Support and New ... -
If you're using Ampere, Ada, or Blackwell GPU architectures,
check out the cuTile Python Quickstart ...
4. 3 Ways NVFP4 Accelerates AI Training and Inference - NVidia -
“By layering optimizations like CUDA Graphs, torch.compile,
NVFP4 precision, and TeaCache, we achiev...
5. Blackwell Architecture and CUDA 13.0: Breakthrough Advances
in ... - The Blackwell architecture brings significant performance
improvements to scientific computing and h...
6. NVIDIA Breaks Its Own CUDA Threshold: Write GPU Kernels in
15 ... - The core change is the introduction of the brand - new
CUDA Tile programming model, which allows dev...
7. Unlocking Tensor Core Performance with Floating Point
Emulation ... - FP32 emulation with Blackwell BF16 tensor cores
that provide increased performance over native FP32 ...
8. Simplify GPU Programming with NVIDIA CUDA Tile in Python -
cuTile is a programming model for writing parallel kernels for
NVIDIA GPUs. In this model: Arrays ar...
9. Nvidia's CUDA Tile examined: AI giant releases programming
style ... - Nvidia's CUDA Tile IR provides abstraction that enables
architectural stability needed for future ge...
10. Unlocking GPU Performance with CUDA Tile - YouTube - ...
feature usage. Using cuTile Python for data-parallel workloads,
especially AI and ML application...
11. Tuning Flash Attention for Peak Performance in NVIDIA CUDA
Tile - We benchmark on the following configuration: Hardware:
NVIDIA B200; Batch: 4, Heads: 32, Head dimens...
12. Comparing CUDA vs Triton for FlashAttention-1 Performance -
CUDA Tile makes it much easier to: ↳ Prototype and deploy
custom layers that aren't covered by exist...
References
13. Add grouped GEMM kernel for faster MoE computation · Issue
#40582 - By leveraging a grouped GEMM kernel, we can perform
the matrix multiplications for all activated exp...
14. Accelerating MoE's with a Triton Persistent Cache-Aware
Grouped ... - In this post, we present an optimized Triton BF16
Grouped GEMM kernel for running training and infer...
15. Grouped GEMMs and MoE - Ian's Blog - A grouped GEMM allows
you to do this process on-device, taking in a list of tokens and
experts and e...
16. NVFP4 boosts AI efficiency with ultra-low precision across the
stack - NVFP4 transforms AI training and inference with
ultra‑low‑precision efficiency across every layer of...
17. r/StableDiffusion on Reddit: NVIDIA recently announced
significant ... - NVIDIA recently announced significant
performance improvements for open-source models on
Blackwell G...
18. [EPIC] Add family of top-k algorithms to CUB #5673 - GitHub -
Tracking Issue: Top-K Algorithms. This issue serves as the
central hub for the implementation of a f...
19. CUDA Profiler Tools Interface (CUPTI) 13.2 is now available - Key
benefits include optimized memory usage by eliminating unused
fields and padding, improved perfo...
20. AlmaLinux and NVIDIA Streamline Driver and CUDA Updates -
Today we are excited to share that with the release of version
13.2, NVIDIA has added official suppo...
21. CUDA Installation Guide for Linux - NVIDIA Documentation - The
guide supports major Linux distributions including Ubuntu, Red
Hat Enterprise Linux, SUSE, Debia...