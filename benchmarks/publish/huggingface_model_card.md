---
language: en
tags:
  - tts
  - voice-cloning
  - qwen3-tts
  - speaker-verification
  - speech-synthesis
license: mit
datasets:
  - custom (489 speaker-specific reference clips)
metrics:
  - speaker_similarity
  - wer
pipeline_tag: text-to-speech
model-index:
  - name: ClipCannon Voice Clone Pipeline
    results:
      - task:
          type: text-to-speech
          name: Personalized Voice Cloning (matched text)
        dataset:
          type: custom
          name: Speaker-specific reference data (489 clips)
        metrics:
          - type: speaker_similarity
            value: 0.9746
            name: SECS (WavLMForXVector, cross-encoder, matched text)
          - type: speaker_similarity
            value: 0.9893
            name: SECS (Qwen3-TTS ECAPA-TDNN 2048-dim, matched-encoder)
          - type: wer
            value: 0.0
            name: WER (Whisper transcription)
      - task:
          type: text-to-speech
          name: Personalized Voice Cloning (novel content)
        dataset:
          type: custom
          name: Speaker-specific reference data (489 clips)
        metrics:
          - type: speaker_similarity
            value: 0.954
            name: SECS (WavLMForXVector, cross-encoder, novel content)
          - type: speaker_similarity
            value: 0.9893
            name: SECS (Qwen3-TTS ECAPA-TDNN 2048-dim, matched-encoder)
---

# ClipCannon Voice Clone Pipeline

A personalized voice cloning pipeline achieving **0.975 cross-encoder SECS** (WavLMForXVector) and **0.954 on novel content** the speaker never said. Built on Qwen3-TTS with zero model fine-tuning -- all gains from pipeline engineering.

## Key Results

### Cross-Encoder SECS (WavLMForXVector -- ClonEval benchmark encoder)

| Test Condition | WavLM SECS | Context |
|---------------|-----------|---------|
| Matched text (ref and target share similar content) | **0.975** | ICL reference + best-of-N selection |
| Novel content (completely different words from ref) | **0.954** | "Jimmy cracked corn..." vs "OCR Provenance..." ref |
| Novel content (short sentence) | **0.938** | "Hello Anne..." vs "OCR Provenance..." ref |
| Zero-shot (random training clip as ref, no ICL) | 0.873 | Baseline without pipeline optimizations |

### Matched-Encoder SECS (Qwen3-TTS ECAPA-TDNN 2048-dim)

| Test Condition | Qwen3 SECS |
|---------------|-----------|
| Matched text | **0.9941** |
| Novel content | **0.9893** |

### Industry Comparison (cross-encoder, independent verification)

| System | Cross-Encoder SECS | Encoder | Condition |
|--------|-------------------|---------|-----------|
| **ClipCannon (matched text)** | **0.975** | WavLMForXVector | Personalized, ICL + best-of-N |
| **ClipCannon (novel content)** | **0.954** | WavLMForXVector | Personalized, ICL + best-of-N |
| NaturalSpeech 3 (Microsoft SOTA) | 0.891 | WavLM-TDNN | Zero-shot, single generation |
| VALL-E 2 ("human parity") | 0.881 | WavLM-TDNN | Zero-shot, single generation |
| MaskGCT | 0.877 | WavLM-TDNN | Zero-shot, single generation |
| F5-TTS | 0.862 | WavLM-TDNN | Zero-shot, single generation |
| ElevenLabs | ~0.80 | Various | Commercial API |

*Note: Academic systems use zero-shot evaluation on LibriSpeech (strangers, single reference clip, single generation). ClipCannon uses personalized pipeline with ICL reference + best-of-N selection on a known speaker with 489 reference clips. These are different evaluation paradigms -- ClipCannon is purpose-built for high-fidelity personalized cloning, not general zero-shot.*

### Intelligibility

| Metric | Value |
|--------|-------|
| WER (Whisper transcription) | 0.0000 (perfect) |
| Output sample rate | 44,100 Hz (after Resemble Enhance) |

### Reference Scaling Study

| Reference Clips | Qwen3 SECS |
|----------------|-----------|
| 1 clip (zero-shot) | 0.9638 |
| 5 clips | 0.9808 |
| 25 clips | 0.9862 |
| 250 clips | 0.9874 |

## Architecture

Zero model modification. All gains from pipeline engineering on top of Qwen3-TTS-12Hz-1.7B-Base:

```
Reference Recording (5-15s of target speaker saying any text)
    |
    v
Full ICL Prompt (reference audio + its transcript)
    |
    v
Qwen3-TTS Generation (temp=0.5, top_p=0.85, max_new_tokens=2048)
    |
    v
Best-of-N Selection (N=8-12, scored against real voice embedding)
    |
    v
Resemble Enhance Denoise (removes codec artifacts, 24kHz -> 44.1kHz)
    |
    v
3-Gate Verification (sanity, intelligibility, identity)
```

### Critical Design Decisions

1. **Full ICL mode** (`x_vector_only_mode=False`): Provides reference audio + its transcript to the model. Copies not just speaker identity but accent, cadence, mic character, and room tone. Without this, the model produces correct identity but random accents.

2. **Score against real voice recording**: Candidates are scored against an embedding of the speaker's actual recording, not a fingerprint averaged from processed training data. This ensures the selected candidate matches the real person, not a synthetic approximation.

3. **Denoise-only post-processing**: Resemble Enhance's `denoise()` removes metallic TTS codec artifacts without altering voice character. The `enhance()` function with high lambd destroys voice identity.

4. **Temperature 0.3-0.5**: Lower temperature produces consistent accent/cadence. Temperature 0.8+ causes random accent drift between generations.

### Speaker Encoders

| Encoder | Dimension | Role | Score |
|---------|-----------|------|-------|
| Qwen3-TTS ECAPA-TDNN | 2048-dim | Primary pipeline scoring | 0.989 |
| WavLMForXVector (microsoft/wavlm-base-plus-sv) | 512-dim | Cross-encoder benchmark (ClonEval) | 0.975 |
| SpeechBrain ECAPA-TDNN | 192-dim | Additional cross-encoder validation | 0.870 |

## Limitations

- **Personalized pipeline**: Optimized for a single target speaker with reference data. Zero-shot performance on unknown speakers is standard Qwen3-TTS quality.
- **Reference recording required**: Best results require a real recording of the target speaker.
- **English only**: Tested only on English speech.
- **Not a model release**: This is a pipeline/methodology, not a new TTS model. The underlying model is Qwen3-TTS-12Hz-1.7B-Base (Alibaba).

## Citation

```
@misc{clipcannon2026voiceclone,
  title={ClipCannon Voice Clone Pipeline: 0.975 Cross-Encoder SECS via Pipeline Engineering},
  author={Chris Royse},
  year={2026},
  url={https://huggingface.co/chrisroyse/clipcannon-voice-clone}
}
```
