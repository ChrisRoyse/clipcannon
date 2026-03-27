# Voice Cloning Optimization Report: Path to 99.99% SECS

## Current State

**Pipeline**: Qwen3-TTS-12Hz-1.7B-Base + Qwen3-Voice-Embedding-12Hz-1.7B (2048-dim ECAPA-TDNN)
**Current Score**: 0.9893 SECS on novel content (words the speaker never said)
**Target**: 0.9999 SECS

## Executive Summary

Reaching 99.99% (0.9999) SECS is likely **not achievable** in a meaningful way. The theoretical ceiling for matched-encoder SECS is approximately 0.995-0.999, bounded by intra-speaker variability, content-dependent embedding leakage, and encoder representation bottleneck. Two recordings of the same real person in different sessions score 0.92-0.98, not 1.0.

However, reaching **0.995-0.997** is realistic by combining 4-5 techniques. This report evaluates 10 approaches with pros, cons, expected impact, and implementation guidance.

---

## Technique 1: Multi-Encoder Fusion Scoring

**Concept**: Score each candidate with 2-3 independent speaker encoders (Qwen3 ECAPA-TDNN + WavLM-Large + SpeechBrain ECAPA) and take a weighted composite. Inspired by the Cognitive Radar PRD's hexa-modal weighted composite (Voice 60% + Semantic 10% + Emotion 10% + Style 10% + Action 5% + Chronemic 5%).

**Expected Impact**: +0.002 to +0.005 on composite metric

**Pros**:
- Prevents "gaming" one encoder while sounding wrong to others
- More perceptually robust selection
- Purely a selection-side change, does not alter generation
- Low risk of degrading quality

**Cons**:
- Does not directly increase Qwen3 ECAPA-TDNN SECS
- Adds inference latency for additional encoder(s)
- WavLM-Large is ~300M params, adds VRAM usage

**Implementation**: Low-medium complexity. Add WavLM scoring as a second gate in verify.py:
```python
composite = 0.60 * secs_qwen3 + 0.25 * secs_wavlm + 0.15 * secs_ecapa_sb
```

**Literature**: Amazon's post-training embedding alignment (arXiv:2401.12440), WavLM ensemble deepfake detection (arXiv:2408.07414).

**Verdict**: Cheap win for robustness. Implement.

---

## Technique 2: Speaker Consistency Loss (SCL) Fine-Tuning

**Concept**: Add an auxiliary loss during Qwen3-TTS fine-tuning that directly maximizes SECS between generated audio and reference embedding.

**Expected Impact**: +0.01 to +0.04 (single highest-impact technique)

**Pros**:
- Directly optimizes the target metric during training
- YourTTS (ICML 2022) pioneered this achieving ~0.86 SECS
- DMOSpeech achieved SIM exceeding ground truth (0.69 vs 0.67)
- GLM-TTS uses multi-reward GRPO balancing SIM with CER, emotion, naturalness

**Cons**:
- Requires differentiable path from TTS output through codec decoder to speaker encoder
- Qwen3-TTS uses discrete 12Hz tokens, making gradients non-trivial (needs straight-through estimator)
- Excessive SCL optimization leads to overfitting - model learns to produce embeddings that score high but degrade naturalness
- High risk without SECS Conditional Loss Suppression (CLS) safeguard
- High implementation complexity

**Implementation**: Must balance SCL weight against reconstruction loss (lambda=0.01 initially, anneal up). Must implement CLS to deactivate SCL once it surpasses threshold to prevent collapse.

**Literature**: YourTTS (ICML 2022), GLM-TTS (arXiv:2512.14291), DMOSpeech (arXiv:2410.11097), Makishima et al. Interspeech 2022.

**Verdict**: Highest potential but highest risk. Phase C implementation.

---

## Technique 3: LoRA Fine-Tuning on Target Speaker

**Concept**: Fine-tune a small number of parameters (LoRA rank 4-16 on attention layers) specifically on your voice data rather than relying on zero-shot ICL.

**Expected Impact**: +0.005 to +0.010

**Pros**:
- Qwen already provides CustomVoice variant designed for this (Qwen3-TTS-12Hz-1.7B-CustomVoice)
- Companion repo exists (cheeweijie/qwen3-tts-lora-finetuning on GitHub)
- Best effort-to-improvement ratio of any technique
- Uses your existing 489 prepared training clips
- LoRP-TTS reports up to +30 percentage points on degraded/noisy prompts

**Cons**:
- Risk of "catastrophic narrowing" with low-diversity data (monotone output)
- Adds model management complexity (need to load/switch adapters)
- LoRA checkpoint adds ~50-100MB storage
- Training requires 2-4 hours on RTX 5090
- DNS-MOS gains depend on acoustic variability in training data

**Implementation**: Medium complexity. Use CustomVoice base with LoRA rank 8 on q_proj/v_proj, train 500-2000 steps.

**Literature**: LoRP-TTS (arXiv:2502.07562), FED-PISA (arXiv:2509.16010), StyleSpeech (arXiv:2408.14713).

**Verdict**: Best ROI. Implement in Phase B.

---

## Technique 4: Latent Space Optimization

**Concept**: Instead of random best-of-N sampling, use gradient-based optimization to maximize SECS in the generation's latent/noise space.

**Expected Impact**: +0.005 to +0.015

**Pros**:
- Eliminates randomness of best-of-N
- DMOSpeech achieved SIM exceeding ground truth using direct metric optimization
- Can produce the globally optimal candidate rather than the best of a random sample

**Cons**:
- Architecturally incompatible with Qwen3-TTS's autoregressive discrete token generation
- Would require Gumbel-Softmax or straight-through estimator for differentiable token selection
- Risk of adversarial collapse (audio that "fools" encoder but sounds unnatural)
- High implementation complexity
- Better suited for flow-matching architectures

**Implementation**: Would require significant rework of the generation pipeline.

**Literature**: DMOSpeech (arXiv:2410.11097), TLA-SA (arXiv:2511.09995), User-Driven Voice Generation (arXiv:2408.17068).

**Verdict**: Skip unless migrating to a flow-matching backbone.

---

## Technique 5: Multi-Reference Concatenation

**Concept**: Use 3-5 reference clips concatenated (up to 15s total) instead of a single best clip, giving the model a richer speaker signal.

**Expected Impact**: +0.003 to +0.008

**Pros**:
- Very low risk - purely additive
- Qwen3-TTS supports multi-reference prompting
- Covers more phonetic variation of the target speaker
- Easy to implement on existing select_best_reference()

**Cons**:
- 15s reference limit constrains how many clips can be included
- Diminishing returns beyond 3-5 clips
- Longer prompts slightly increase generation time

**Implementation**: Low complexity. Modify select_best_reference() to return top-3 clips, concatenate as longer reference (trimmed to 15s).

**Literature**: MRMI-TTS (ACM TALLIP 2024), Qwen3-TTS technical report (arXiv:2601.15621).

**Verdict**: Easy win. Implement in Phase A.

---

## Technique 6: Vocoder Re-synthesis

**Concept**: Extract mel spectrogram from Qwen3-TTS output, re-synthesize with BigVGAN or Vocos to remove codec artifacts.

**Expected Impact**: +0.001 to +0.005

**Pros**:
- Vocos (Fourier-based) avoids periodicity artifacts of time-domain vocoders
- BigVGAN uses anti-aliased activations for better harmonic reconstruction
- Can improve the clarity of the audio presented to the speaker encoder

**Cons**:
- Resemble Enhance already handles most of what this would do
- Three cascaded processing stages (TTS -> vocoder -> enhance) risk compounding artifacts
- Mel spectrogram extraction is lossy
- Marginal gains over current denoise-only pipeline

**Implementation**: Medium complexity. Match mel parameters between extraction and vocoder.

**Literature**: Vocos (arXiv:2306.00814), BigVGAN (ICLR 2023 NVIDIA).

**Verdict**: Skip. Resemble Enhance denoise already covers this.

---

## Technique 7: Prosodic Matching

**Concept**: Match F0 contour, energy envelope, and speaking rate between generated and reference audio using WORLD vocoder or Parselmouth.

**Expected Impact**: +0.002 to +0.008

**Pros**:
- Addresses the accent/cadence issue that caused the "British voice" problem
- Speaker encoders partially capture prosody, so matching it helps SECS
- Bigger win is perceptual - sounds more like the target person
- Well-established tools (Parselmouth, WORLD)

**Cons**:
- Full ICL mode already captures prosodic style from reference
- Aggressive F0 manipulation creates audible artifacts
- Post-hoc prosody transfer on top of ICL may conflict with model's own prosodic modeling
- More useful in x-vector mode (which we already abandoned)

**Implementation**: Medium complexity. Extract F0 from reference, apply mean-variance normalization to generated audio.

**Literature**: AutoVC, RADTTS++ (NVIDIA), Stable-TTS (arXiv:2412.20155).

**Verdict**: Low priority. Full ICL mode handles prosody. Only if subjective evaluation shows prosody mismatch.

---

## Technique 8: Embedding Space Alignment

**Concept**: Train a small MLP to map between encoder spaces for more accurate cross-validation.

**Expected Impact**: +0.001 to +0.003

**Pros**:
- Amazon showed 3-layer MLP achieves near-identical verification performance across spaces
- Very low risk
- Enables meaningful cross-encoder comparison

**Cons**:
- Only useful if you adopt multi-encoder fusion (Technique 1)
- Marginal standalone gain
- Requires paired training data (same utterance through both encoders)

**Implementation**: Low-medium complexity.

**Literature**: Amazon (arXiv:2401.12440).

**Verdict**: Skip unless building multi-encoder fusion.

---

## Technique 9: Iterative Refinement

**Concept**: Use the best candidate from round 1 as the reference audio for round 2, bootstrapping toward higher similarity.

**Expected Impact**: +0.003 to +0.010 per iteration (diminishing after 2-3 rounds)

**Pros**:
- Simple loop around existing best_of_n_speak()
- SelfVC (arXiv:2310.09653) demonstrated improvements in speaker similarity metrics
- Each round starts from a closer starting point
- Low implementation cost

**Cons**:
- Risk of "echo chamber" degradation after 3+ rounds - model clones its own artifacts
- Must always score against ORIGINAL reference, never update verification target with synthetic output
- Each round doubles generation time
- Can drift away from natural speech

**Implementation**: Low complexity. Add 2-round loop in optimize.py, use best output as new ICL prompt for next round.

**Literature**: SelfVC (arXiv:2310.09653), MOSS-TTSD voice continuation experiments.

**Verdict**: High potential, low cost. Implement with 2-round max and original reference verification.

---

## Technique 10: Temperature Annealing

**Concept**: Two-phase sampling: first generate at higher temperature (0.7) for diversity, then regenerate near the best candidates at lower temperature (0.3) for precision.

**Expected Impact**: +0.003 to +0.008

**Pros**:
- Zero architecture changes
- Combines exploration (finding the right "region") with exploitation (refining it)
- Standard technique from bandit theory
- Low risk

**Cons**:
- Lower temperature may produce less expressive output
- Seed proximity doesn't guarantee similar output in autoregressive models
- Marginal gains over current fixed-temperature approach

**Implementation**: Low complexity. Modify best_of_n_speak() loop in optimize.py.

**Literature**: Standard LLM sampling literature, Qwen3-TTS recommended range 0.3-0.9.

**Verdict**: Easy win. Implement alongside existing best-of-N.

---

## Why 99.99% (0.9999) Is Not Achievable

Five fundamental barriers:

1. **Intra-speaker variability**: Different recordings of the same real person score 0.92-0.98, not 1.0. The encoder captures session-dependent factors (mic, room, emotion, fatigue) that vary between recordings.

2. **Content-dependent embedding leakage**: Speaker encoders are not perfectly content-invariant. Different phonemes produce different embeddings even for the same speaker. Research shows 0.02-0.05 SECS variation based on phonetic content alone.

3. **Encoder representation bottleneck**: The 2048-dim ECAPA-TDNN compresses a variable-length waveform into a fixed vector. This compression is lossy by design.

4. **Adversarial collapse risk**: A system optimized purely to maximize SECS eventually produces audio that "fools" the encoder but sounds wrong to humans. DMOSpeech achieved synthetic SIM exceeding ground truth (0.69 vs 0.67), which means the metric itself is being gamed.

5. **Measurement noise**: Resampling, windowing, and floating-point precision introduce approximately +/-0.001 noise in cosine similarity calculations.

**Practical ceiling**: 0.995-0.999 for matched-encoder measurement. Beyond this, improvements in SECS do not correspond to perceptual improvements.

---

## Recommended Implementation Plan

### Phase A: Quick Wins (1-2 days, ~+0.005-0.010)

| Technique | Change | File |
|-----------|--------|------|
| Temperature annealing | Two-phase sampling (0.7 explore, 0.3 exploit) | optimize.py |
| Multi-reference concatenation | Top-3 clips instead of single best | optimize.py |
| Iterative refinement (2 rounds) | Best candidate becomes round 2 reference | optimize.py |

**Expected result**: 0.989 -> 0.994-0.997

### Phase B: LoRA Fine-Tuning (1 week, ~+0.005-0.010)

| Technique | Change | File |
|-----------|--------|------|
| LoRA fine-tuning | Rank-8 LoRA on Qwen3-TTS-CustomVoice | inference.py, new training script |

**Expected result**: 0.994 -> 0.997-0.999

### Phase C: Advanced (2-3 weeks, ~+0.002-0.005)

| Technique | Change | File |
|-----------|--------|------|
| Multi-encoder fusion | Add WavLM scorer as second gate | verify.py |
| SCL fine-tuning | Add speaker consistency loss with CLS | training script |

**Expected result**: 0.997 -> 0.998-0.999

---

## Priority Matrix

| # | Technique | Expected Gain | Effort | Risk | Priority |
|---|-----------|--------------|--------|------|----------|
| 3 | LoRA Fine-Tuning | +0.005-0.010 | Medium | Medium | **1st** |
| 9 | Iterative Refinement | +0.003-0.010 | Low | Medium | **2nd** |
| 10 | Temperature Annealing | +0.003-0.008 | Low | Low | **3rd** |
| 5 | Multi-Reference Concat | +0.003-0.008 | Low | Very Low | **4th** |
| 1 | Multi-Encoder Fusion | +0.002-0.005 | Low-Med | Low | **5th** |
| 2 | SCL Fine-Tuning | +0.010-0.040 | High | High | **6th** |
| 7 | Prosodic Matching | +0.002-0.008 | Medium | Low-Med | **7th** |
| 4 | Latent Space Optimization | +0.005-0.015 | High | Med-High | **8th** |
| 8 | Embedding Alignment | +0.001-0.003 | Low-Med | Very Low | **9th** |
| 6 | Vocoder Re-synthesis | +0.001-0.005 | Medium | Low-Med | **10th** |

---

## Recommendation

**Stop optimizing SECS above 0.997.** At that point, add a **perceptual quality gate** (UTMOS or DNSMOS) alongside SECS. The gap from 0.997 to 0.999 is better spent optimizing naturalness than raw speaker similarity. The DMOSpeech result (synthetic speech exceeding ground truth on SIM) is a cautionary signal that metric optimization beyond a certain point diverges from actual quality.

The real-world goal isn't a higher number - it's making the clone indistinguishable from you. At 0.989, you're already past the point where trained listeners can reliably tell the difference. The remaining work should focus on perceptual quality (naturalness, expressiveness, mic character) rather than pushing a metric that has diminishing correlation with human perception.

---

## References

- Speaker consistency loss and step-wise optimization (Interspeech 2022, Makishima et al.)
- YourTTS: Zero-Shot Multi-Speaker TTS (ICML 2022, Casanova et al.)
- DMOSpeech: Direct Metric Optimization (arXiv:2410.11097)
- GLM-TTS Technical Report (arXiv:2512.14291)
- Qwen3-TTS Technical Report (arXiv:2601.15621)
- LoRP-TTS: Low-Rank Personalized TTS (arXiv:2502.07562)
- TLA-SA: Time-Layer Adaptive Speaker Alignment (arXiv:2511.09995)
- MRMI-TTS: Multi-Reference with Mutual Information (ACM TALLIP 2024)
- Post-training embedding alignment (arXiv:2401.12440, Amazon)
- SelfVC: Voice Conversion with Iterative Refinement (arXiv:2310.09653)
- Vocos: Fourier-based neural vocoder (arXiv:2306.00814)
- BigVGAN (NVIDIA, ICLR 2023)
- Voice Cloning: Comprehensive Survey (arXiv:2505.00579)
- Stable-TTS: Prosody Prompting (arXiv:2412.20155)
- FED-PISA: Federated Voice Cloning (arXiv:2509.16010)
- ClonEval: Open Voice Cloning Benchmark (arXiv:2504.20581)
- Cosine Scoring with Uncertainty (arXiv:2403.06404)
- Cognitive Radar PRD (internal, weighted composite scoring architecture)
- North Star Refinery PRD (internal, multi-dimensional reference vector calibration)
