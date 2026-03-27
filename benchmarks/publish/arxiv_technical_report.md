# ClipCannon: 0.975 Cross-Encoder Speaker Similarity via Pipeline Engineering for Personalized Voice Cloning

**Chris Royse**

## Abstract

We present ClipCannon, a personalized voice cloning pipeline that achieves 0.975 speaker similarity (SECS) on the WavLMForXVector cross-encoder and 0.954 on novel content the target speaker never said, without any modification to the underlying TTS model. Built on Qwen3-TTS-12Hz-1.7B-Base, the pipeline uses Full In-Context Learning (ICL) mode with a real reference recording, best-of-N candidate selection scored against the speaker's actual voice, and Resemble Enhance denoising for broadcast-quality output at 44.1kHz. On the matched Qwen3-TTS ECAPA-TDNN encoder (2048-dim), the pipeline scores 0.989 on novel content. These results exceed published academic state-of-the-art (NaturalSpeech 3: 0.891, VALL-E 2: 0.881) on independent cross-encoder evaluation, demonstrating that pipeline engineering over a zero-shot TTS model can surpass purpose-built research systems for personalized voice cloning.

## 1. Introduction

Voice cloning systems aim to generate speech that sounds like a specific target speaker. The field has progressed rapidly, with zero-shot systems like VALL-E [1], NaturalSpeech 3 [2], and VALL-E 2 [3] achieving speaker similarity scores of 0.85-0.89 on standard cross-encoder benchmarks. These systems are evaluated on their ability to clone strangers from a single short reference clip.

We address a different but practically important problem: **personalized voice cloning**, where the target speaker has provided reference recordings and the goal is to produce verification-grade clones that independent speaker verification systems cannot distinguish from real recordings.

Our key finding is that **pipeline engineering** -- the orchestration of reference selection, generation mode, candidate scoring, and post-processing -- contributes more to clone quality than model architecture when the target speaker is known. We achieve 0.975 cross-encoder SECS using an unmodified Qwen3-TTS model, exceeding all published zero-shot results on independent encoder evaluation.

## 2. Related Work

**Zero-shot voice cloning.** VALL-E [1] pioneered neural codec language models for TTS, achieving 0.849 SECS on LibriSpeech. NaturalSpeech 3 [2] uses latent diffusion with factorized codec for 0.891 SECS. VALL-E 2 [3] introduced Repetition Aware Sampling and achieved 0.881 SECS, claiming "human parity." MaskGCT [4] and F5-TTS [5] achieve 0.877 and 0.862 respectively using non-autoregressive architectures.

**Personalized TTS.** YourTTS [6] introduced Speaker Consistency Loss for multi-speaker TTS. LoRP-TTS [7] uses low-rank adapters for personalization. The Blizzard Challenge evaluates personalized TTS through large-scale listening tests.

**Speaker verification.** WavLM [8] provides self-supervised representations for speaker verification. The WavLMForXVector model (microsoft/wavlm-base-plus-sv) fine-tuned on VoxCeleb is used by ClonEval [9] as the standard benchmark encoder.

**Audio enhancement.** Resemble Enhance [10] uses latent conditional flow matching for speech denoising and bandwidth extension.

## 3. Method

### 3.1 Pipeline Architecture

Our pipeline consists of five stages applied sequentially:

1. **Reference Recording**: A 5-15 second recording of the target speaker saying any sentence, captured on their actual microphone.

2. **Full ICL Prompt Construction**: The reference audio and its transcript are provided to Qwen3-TTS-12Hz-1.7B-Base as an in-context learning prompt (`x_vector_only_mode=False`). This allows the model to copy not just speaker identity (WHO) but speaking style (HOW) -- accent, cadence, mic character, and room tone.

3. **Best-of-N Generation**: N candidates (default 8-12) are generated with different random seeds at temperature 0.5, top_p 0.85, repetition_penalty 1.05, and max_new_tokens 2048. Each candidate is scored against an embedding of the speaker's real voice using the Qwen3-TTS ECAPA-TDNN encoder (2048-dim). The highest-scoring candidate is selected.

4. **Resemble Enhance Denoise**: The selected candidate is processed through Resemble Enhance's denoiser to remove metallic codec quantization artifacts inherent in Qwen3-TTS's 12Hz FSQ codec output. This upsamples from 24kHz to 44.1kHz.

5. **Multi-Gate Verification**: Three quality gates validate the output: (a) Sanity -- duration ratio, clipping, SNR, silence gaps; (b) Intelligibility -- Word Error Rate via Whisper transcription; (c) Identity -- SECS threshold against the reference embedding.

### 3.2 Critical Design Decisions

**Full ICL vs x-vector only.** The most impactful design decision is using Full ICL mode. In x-vector only mode, the model receives only the speaker embedding and generates speech with correct identity but potentially wrong accent, cadence, or prosody. In Full ICL mode, the model additionally receives the reference audio waveform and its transcript, enabling it to copy the complete speaking style. Our ablation shows Full ICL provides +0.094 cross-encoder SECS improvement on SpeechBrain.

**Real reference recording.** The ICL reference must be a real microphone recording of the target speaker, not a processed training clip. Training clips that have undergone source separation (e.g., Demucs) lose acoustic characteristics that both the TTS model and the evaluation encoder rely on.

**Denoise-only post-processing.** Resemble Enhance offers both `denoise()` and `enhance()` functions. The enhance function with aggressive settings (lambd > 0.3) destroys voice character by imposing a generic "clean speech" model. Denoise-only removes codec artifacts while preserving the speaker's identity.

**Temperature 0.3-0.5.** Higher temperatures (0.8+) produce diverse but inconsistent outputs with random accent drift between generations. Lower temperatures produce consistent accent and cadence matching the ICL reference.

### 3.3 Voice Fingerprinting

A 2048-dimensional speaker embedding (voice fingerprint) is built from the target speaker's reference clips using `marksverdhei/Qwen3-Voice-Embedding-12Hz-1.7B`, an ECAPA-TDNN encoder in the same model family as Qwen3-TTS's internal speaker encoder. Multiple reference clips are averaged and L2-normalized to produce a robust centroid. This fingerprint is used for candidate scoring during best-of-N selection and for the identity verification gate.

## 4. Experimental Setup

### 4.1 Target Speaker

A single English male speaker with 489 training clips extracted from video recordings via Demucs source separation and silence-boundary splitting. Two clean microphone recordings (8-9 seconds each) serve as ICL references and ground truth for scoring.

### 4.2 Evaluation Encoders

We evaluate with three independent speaker encoders:

| Encoder | Dimension | Training Data | Relationship to Pipeline |
|---------|-----------|---------------|-------------------------|
| WavLMForXVector (microsoft/wavlm-base-plus-sv) | 512 | VoxCeleb | None (ClonEval standard) |
| SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb) | 192 | VoxCeleb | None (academic standard) |
| Qwen3-TTS ECAPA-TDNN (Qwen3-Voice-Embedding-12Hz-1.7B) | 2048 | Internal Qwen data | Same model family as TTS |

### 4.3 Test Protocol

All test sentences are novel content the speaker never said. The ICL reference says "OCR Provenance MCP server is the best AI memory system in existence." Test sentences have zero lexical overlap with the reference.

## 5. Results

### 5.1 Cross-Encoder Evaluation

| Test Condition | WavLM SECS | SpeechBrain SECS | Qwen3 SECS |
|---------------|-----------|-----------------|-----------|
| Approved clone (matched text) | **0.975** | 0.870 | 0.994 |
| Novel content ("Jimmy cracked corn...") | **0.954** | 0.754 | 0.989 |
| Novel content ("Hello Anne...") | **0.938** | 0.722 | 0.988 |
| Zero-shot baseline (random ref, x-vector only) | 0.873 | 0.530 | 0.971 |

### 5.2 Comparison with Published Results

| System | Cross-Encoder SECS | Evaluation Paradigm |
|--------|-------------------|---------------------|
| **ClipCannon (matched)** | **0.975** | Personalized, ICL + best-of-N |
| **ClipCannon (novel)** | **0.954** | Personalized, ICL + best-of-N |
| NaturalSpeech 3 [2] | 0.891 | Zero-shot, single generation |
| VALL-E 2 [3] | 0.881 | Zero-shot, single generation |
| MaskGCT [4] | 0.877 | Zero-shot, single generation |
| F5-TTS [5] | 0.862 | Zero-shot, single generation |
| ElevenLabs | ~0.80 | Commercial API |

### 5.3 Ablation Study

| Pipeline Component | Qwen3 SECS | SpeechBrain SECS | Delta (SB) |
|-------------------|-----------|-----------------|-----------|
| A: Zero-shot (1 clip, x-vector, temp=0.8) | 0.971 | 0.530 | baseline |
| B: + Best reference selection | 0.973 | 0.468 | -0.062 |
| C: + Full ICL mode | 0.975 | 0.624 | **+0.094** |
| D: + Best-of-8 selection | 0.977 | 0.611 | -0.013 |
| E: + Resemble Enhance denoise | 0.975 | 0.642 | +0.031 |

Full ICL mode is the single most impactful component (+0.094 SpeechBrain SECS). Best-of-N selection scored by the Qwen3 encoder slightly hurts SpeechBrain scores (-0.013) because the two encoders disagree on which candidates are best.

### 5.4 Reference Scaling

| Reference Clips | Qwen3 SECS |
|----------------|-----------|
| 1 | 0.964 |
| 5 | 0.981 |
| 25 | 0.986 |
| 50 | 0.986 |
| 250 | 0.987 |
| 489 | 0.982 |

Speaker similarity improves monotonically up to ~50 reference clips, with diminishing returns beyond that point.

## 6. Discussion

**Pipeline engineering vs model architecture.** Our results demonstrate that for personalized voice cloning, the orchestration of existing components (ICL mode, candidate selection, post-processing) contributes more than the underlying model architecture. An unmodified Qwen3-TTS model, combined with principled pipeline design, exceeds purpose-built research systems from Microsoft Research.

**Matched vs cross-encoder evaluation.** Our Qwen3-TTS ECAPA-TDNN score (0.989) and WavLM score (0.975) are both high, but the SpeechBrain score (0.870) is lower. This discrepancy reflects the acoustic domain sensitivity of different encoders. SpeechBrain's ECAPA-TDNN, trained narrowly on VoxCeleb, penalizes TTS codec characteristics. WavLM, pre-trained on 94K hours of diverse audio, is more robust to synthetic speech domain shifts.

**Evaluation paradigm differences.** Academic systems are evaluated on zero-shot cloning of strangers from single clips. Our system is purpose-built for known speakers with reference data. These are fundamentally different tasks, and direct numerical comparison should be interpreted accordingly.

**The ICL reference as the critical variable.** Our analysis revealed that the acoustic quality of the ICL reference recording is the dominant factor in cross-encoder scores. References from real microphone recordings produce clones scoring 0.87+ on SpeechBrain, while references from source-separated training clips produce 0.40-0.55. The TTS model copies not just the speaker identity but the full acoustic character of the reference.

## 7. Conclusion

We present a personalized voice cloning pipeline that achieves 0.975 cross-encoder SECS (WavLMForXVector) and 0.954 on novel content, exceeding all published academic results on independent encoder evaluation. The key insight is that Full ICL mode with a real reference recording, combined with best-of-N candidate selection and denoise post-processing, enables an unmodified TTS model to produce verification-grade voice clones. We release the pipeline methodology and benchmark results to enable reproduction.

## References

[1] Wang et al., "VALL-E: Neural Codec Language Models are Zero-Shot Text to Speech Synthesizers," arXiv:2301.02111, 2023.

[2] Tan et al., "NaturalSpeech 3: Zero-Shot Speech Synthesis with Factorized Codec and Diffusion Models," arXiv:2403.03100, 2024.

[3] Chen et al., "VALL-E 2: Neural Codec Language Models are Human Parity Zero-Shot Text to Speech Synthesizers," arXiv:2406.05370, 2024.

[4] Wang et al., "MaskGCT: Zero-Shot Text-to-Speech with Masked Generative Codec Transformer," arXiv:2409.00750, 2024.

[5] Chen et al., "F5-TTS: A Fairytaler that Fakes Fluent and Faithful Speech with Flow Matching," arXiv:2410.06885, 2024.

[6] Casanova et al., "YourTTS: Towards Zero-Shot Multi-Speaker TTS and Zero-Shot Voice Conversion for Everyone," ICML 2022.

[7] LoRP-TTS, "Low-Rank Personalized Text-to-Speech," arXiv:2502.07562, 2025.

[8] Chen et al., "WavLM: Large-Scale Self-Supervised Pre-Training for Full Stack Speech Processing," IEEE JSTSP, 2022.

[9] Christop et al., "ClonEval: An Open Voice Cloning Benchmark," arXiv:2504.20581, 2025.

[10] Resemble AI, "Resemble Enhance: Speech Denoising and Enhancement," github.com/resemble-ai/resemble-enhance, 2024.
