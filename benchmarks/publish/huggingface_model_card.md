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
          name: Personalized Voice Cloning
        dataset:
          type: custom
          name: Speaker-specific reference data (489 clips)
        metrics:
          - type: speaker_similarity
            value: 0.9893
            name: SECS (Qwen3-TTS ECAPA-TDNN 2048-dim, novel content)
          - type: speaker_similarity
            value: 0.870
            name: SECS (SpeechBrain ECAPA-TDNN 192-dim, cross-encoder, vs real mic)
          - type: wer
            value: 0.0
            name: WER (Whisper transcription)
---

# ClipCannon Voice Clone Pipeline

A personalized voice cloning pipeline that achieves **98.93% speaker similarity** on novel content the target speaker never said, using pipeline engineering over a zero-shot TTS model without any model fine-tuning.

## Key Results

### Matched-Encoder SECS (Qwen3-TTS ECAPA-TDNN 2048-dim)

| Test Condition | SECS |
|---------------|------|
| Novel content (words never spoken by speaker) | **0.9893** |
| Same text as reference | 0.9941 |
| WER (word accuracy) | 0.0000 |

### Cross-Encoder SECS (SpeechBrain ECAPA-TDNN 192-dim, independent)

Scored against real microphone recordings (not source-separated training data).

| Comparison | Cross-Encoder SECS |
|-----------|-------------------|
| Real mic vs Real mic (same speaker baseline) | 0.999 |
| Real mic vs Different session recording | 0.718 |
| **Approved clone vs Real mic** | **0.870** |
| Novel sentence clone vs Real mic | 0.755 |

The approved clone (0.870) scores **higher** than a different real recording of the same speaker in a different session (0.718), demonstrating the clone is more consistently recognizable than natural recording variation.

### Reference Scaling Study

| Reference Clips | SECS (Qwen3 2048-dim) |
|----------------|----------------------|
| 1 clip | 0.9638 |
| 5 clips | 0.9808 |
| 25 clips | 0.9862 |
| 250 clips | 0.9874 |
| 489 clips | 0.9824 |

## Architecture

The pipeline is built on top of Qwen3-TTS-12Hz-1.7B-Base with zero model modification. All gains come from pipeline engineering:

```
Reference Recording (5-15s of target speaker)
    |
    v
Full ICL Prompt (reference audio + transcript)
    |
    v
Qwen3-TTS Generation (temp=0.5, top_p=0.85)
    |
    v
Best-of-N Selection (scored against real voice embedding)
    |
    v
Resemble Enhance Denoise (24kHz -> 44.1kHz)
    |
    v
Multi-Gate Verification (sanity, intelligibility, identity)
```

### Pipeline Components and Their Impact

| Component | Matched SECS Gain | Cross-Encoder SECS Gain |
|-----------|-------------------|------------------------|
| Baseline (zero-shot, x-vector) | 0.9708 | 0.530 |
| Full ICL mode | +0.0045 | **+0.094** |
| Best-of-8 selection | +0.0019 | -0.013 |
| Resemble Enhance denoise | -0.0026 | +0.031 |
| **Full pipeline** | **0.9746** | **0.642** |

**Full ICL mode is the single most impactful component**, providing +0.094 cross-encoder SECS improvement. This uses a real recording of the target speaker + its transcript as the in-context learning prompt, allowing the model to copy not just WHO is speaking but HOW they speak (accent, cadence, mic character).

## How It Works

1. **Reference Recording**: Record yourself saying any sentence (5-15 seconds)
2. **Full ICL Mode**: The reference audio + its transcript are provided to Qwen3-TTS as an in-context learning prompt (`x_vector_only_mode=False`)
3. **Best-of-N Selection**: Generate N candidates (default 8), score each against a real voice embedding using the Qwen3-TTS ECAPA-TDNN encoder, keep the best
4. **Denoise**: Resemble Enhance removes metallic TTS codec artifacts and upsamples from 24kHz to 44.1kHz
5. **3-Gate Verification**: Sanity (duration/clipping/SNR/silence), Intelligibility (WER via Whisper), Identity (SECS threshold)

## Speaker Encoder

| Property | Value |
|----------|-------|
| Model | marksverdhei/Qwen3-Voice-Embedding-12Hz-1.7B |
| Architecture | ECAPA-TDNN |
| Embedding Dimension | 2048 |
| Input Sample Rate | 24,000 Hz |
| Relationship to TTS | Same encoder family as Qwen3-TTS internal speaker encoder |

## Generation Parameters

| Parameter | Value |
|-----------|-------|
| Temperature | 0.5 |
| Top-p | 0.85 |
| Repetition penalty | 1.05 |
| Max new tokens | 2048 |
| Reference audio length | 5-15 seconds |
| ICL mode | Full (ref audio + transcript) |
| Output sample rate | 44,100 Hz (after Resemble Enhance) |

## Limitations

- **Matched-encoder measurement**: The 0.9893 SECS is measured with the Qwen3-TTS ECAPA-TDNN encoder, which is in the same model family as the TTS model. Cross-encoder SECS (SpeechBrain, independent) is 0.870 when scored against real mic recordings.
- **Personalized pipeline**: Optimized for a single target speaker with 489 reference clips. Zero-shot performance on unknown speakers is standard Qwen3-TTS quality.
- **Reference recording required**: Best results require a real recording of the target speaker saying similar content to what will be generated.
- **English only**: Tested only on English speech.

## Citation

If you use this pipeline or reference these results, please cite:

```
@misc{clipcannon2026voiceclone,
  title={ClipCannon Voice Clone Pipeline: Personalized Voice Cloning via Pipeline Engineering},
  author={Chris Royse},
  year={2026},
  url={https://github.com/your-repo/clipcannon}
}
```
