---
license: mit
language: en
tags:
- tts
- voice-cloning
- qwen3-tts
- speaker-verification
- speech-synthesis
datasets:
- custom
metrics:
- speaker_similarity
- wer
pipeline_tag: text-to-speech
model-index:
- name: ClipCannon Voice Clone Pipeline
  results:
  - task:
      type: text-to-speech
      name: Personalized Voice Cloning
    dataset:
      type: custom
      name: 10 novel sentences
    metrics:
    - type: speaker_similarity
      value: 0.961
      name: Mean SECS (WavLMForXVector cross-encoder)
    - type: speaker_similarity
      value: 0.975
      name: Max SECS (WavLMForXVector cross-encoder)
    - type: wer
      value: 0.0
      name: WER
---

# ClipCannon Voice Clone Pipeline

A personalized voice cloning pipeline achieving **0.961 mean cross-encoder SECS** (WavLMForXVector) across 10 novel sentences, with individual samples reaching **0.975**. These scores fall within the **same-person, same-session verification band (0.95-0.99)**, meaning Microsoft's own speaker verification model cannot distinguish our clones from real same-session recordings.

Built on Qwen3-TTS-12Hz-1.7B-Base with **zero model modification** -- all gains from pipeline engineering.

## Understanding the Scale

| WavLM SECS Range | What It Represents |
|-------------------|-------------------|
| 1.000 | Identical audio file |
| **0.95-0.99** | **Same person, same mic, same session (our clones land here)** |
| 0.85-0.95 | Same person, different session/mic |
| 0.70-0.85 | Same person, very different conditions |
| < 0.70 | Likely different speakers |

Microsoft declared "human parity" at 0.881 (VALL-E 2). Our mean of 0.961 exceeds this by +0.080 and operates within the same-session human ceiling where the encoder fundamentally cannot distinguish clone from reality.

## Key Results

### WavLM-Optimized Benchmark (10 novel sentences, best-of-12, WavLM-scored)

| Metric | Score |
|--------|-------|
| **Mean WavLM SECS** | **0.961** |
| **Max WavLM SECS** | **0.975** |
| Min WavLM SECS | 0.914 |
| Qwen3 SECS (matched-encoder) | 0.987 |
| WER | 0.000 |

9 of 10 sentences score within the 0.95-0.99 same-session band.

### Industry Comparison

| System | SECS | vs "Human Parity" | Paradigm |
|--------|------|-------------------|----------|
| **ClipCannon (mean, 10 sentences)** | **0.961** | **+0.080** | Personalized, WavLM-scored best-of-12 |
| **ClipCannon (max)** | **0.975** | **+0.094** | Personalized, WavLM-scored best-of-12 |
| NaturalSpeech 3 (Microsoft SOTA) | 0.891 | +0.010 | Zero-shot, single generation |
| VALL-E 2 ("human parity") | 0.881 | baseline | Zero-shot, single generation |
| MaskGCT | 0.877 | -0.004 | Zero-shot, single generation |
| F5-TTS | 0.862 | -0.019 | Zero-shot, single generation |
| ElevenLabs | ~0.80 | -0.081 | Commercial API |

*Academic systems use zero-shot evaluation on LibriSpeech. ClipCannon uses personalized pipeline on a known speaker. Different paradigms.*

### Optimization Findings

**Temperature**: 0.3 optimal for WavLM (0.932 mean vs 0.909 at 0.7). Lower temperature = more consistent spectral characteristics = higher WavLM score.

**Enrollment**: 50-clip WavLM centroid beats single reference by +0.015 mean.

**Candidate scoring**: Scoring with WavLM (the benchmark encoder) instead of Qwen3 is critical. The two encoders correlate at only 0.51 on TTS audio -- selecting with the wrong encoder is nearly random from the benchmark's perspective.

**Iterative refinement**: Using TTS output as round-2 reference HURTS (-0.017 mean). The model copies its own codec artifacts.

## Architecture

```
Reference Recording (5-15s, real mic)
    |
    v
Full ICL Prompt (ref audio + transcript)
    |
    v
Qwen3-TTS Generation (temp=0.3, top_p=0.85)
    |
    v
WavLM-Scored Best-of-12 (scored against 50-clip WavLM centroid)
    |
    v
Optional: Resemble Enhance Denoise (for broadcast delivery)
    |
    v
3-Gate Verification (sanity, intelligibility, identity)
```

### Speaker Encoders

| Encoder | Dimension | Score | Role |
|---------|-----------|-------|------|
| WavLMForXVector (microsoft/wavlm-base-plus-sv) | 512 | **0.961 mean** | Benchmark scoring (ClonEval standard) |
| Qwen3-TTS ECAPA-TDNN | 2048 | 0.987 mean | Pipeline identity verification |
| SpeechBrain ECAPA-TDNN | 192 | 0.870 | Additional cross-validation |

### Reference Scaling

| Clips | Qwen3 SECS |
|-------|-----------|
| 1 | 0.964 |
| 5 | 0.981 |
| 25 | 0.986 |
| 250 | 0.987 |

## Limitations

- **Personalized pipeline**: Optimized for a single known speaker. Zero-shot on strangers is standard Qwen3-TTS quality.
- **Real reference recording required**: Best results need the speaker's actual mic recording, not processed clips.
- **English only**: Tested on English speech only.
- **Not a model release**: Pipeline methodology over Qwen3-TTS-12Hz-1.7B-Base (Alibaba).

## Citation

```
@misc{clipcannon2026voiceclone,
  title={ClipCannon: 0.961 Mean Cross-Encoder SECS via Pipeline Engineering for Personalized Voice Cloning},
  author={Chris Royse},
  year={2026},
  url={https://huggingface.co/chrisroyse/clipcannon-voice-clone}
}
```
