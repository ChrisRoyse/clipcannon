# ClipCannon Voice Cloning Guide

How to perfectly clone your voice with Qwen3-TTS. Achieves 0.9941 SECS (99.41% match) against your real voice.

## The Pipeline

```
1. Ingest your videos into ClipCannon projects
2. Run voice data prep (extracts + splits your vocal clips)
3. Build a 2048-dim voice fingerprint from all clips
4. Record yourself saying the target text (the KEY step)
5. Generate with Full ICL mode using your recording as reference
6. Best-of-N selection scored against your real voice
7. Denoise to remove metallic TTS artifacts
```

## Step 1: Build Voice Training Data

Ingest videos of yourself speaking, then extract voice clips:

```
clipcannon_prepare_voice_data:
  project_ids: ["proj_xxx", "proj_yyy", ...]
  speaker_label: "chris"
```

This creates `~/.clipcannon/voice_data/chris/wavs/` with hundreds of silence-split clips (1-12s each). More clips = better fingerprint. 400+ clips is ideal.

**Good training data:** Clear speech, your natural voice, multiple sessions/days, minimal background noise.

## Step 2: Build Voice Fingerprint

Averages all training clips into a single 2048-dim speaker embedding stored in the voice profile database:

```python
from clipcannon.voice.verify import build_reference_embedding
from clipcannon.voice.profiles import update_voice_profile
from pathlib import Path

clips = sorted(Path("~/.clipcannon/voice_data/chris/wavs").expanduser().glob("*.wav"))
ref_emb = build_reference_embedding(clips)

update_voice_profile(
    "~/.clipcannon/voice_profiles.db",
    "boris",  # profile name
    reference_embedding=ref_emb.tobytes(),
)
```

Uses `marksverdhei/Qwen3-Voice-Embedding-12Hz-1.7B` - the same ECAPA-TDNN encoder that lives inside Qwen3-TTS. This ensures SECS measurements are in the correct embedding space.

## Step 3: Record a Reference Clip (Most Important Step)

**Record yourself saying the exact text (or something similar) that you want the AI to say.** This is what makes the difference between "sounds like a random person with my voice" and "sounds exactly like me."

Requirements:
- Your real mic, your real room
- 5-15 seconds (longer causes runaway generation)
- Natural pace and tone
- Say the same words or similar words to what the AI will generate

**Why this is critical:** Without a reference recording, the model only gets your speaker embedding (WHO you are) but not HOW you speak. It will match your voice identity perfectly (high SECS) but may use a completely different accent, cadence, or intonation. With a reference recording + transcript, the model copies your exact speaking style via In-Context Learning.

## Step 4: Generate with Full ICL Mode

```python
from clipcannon.voice.inference import VoiceSynthesizer, _trim_reference
from pathlib import Path

synth = VoiceSynthesizer()
engine = synth._ensure_engine()

ref_path = _trim_reference(Path("your_reference.wav"))

# Full ICL: reference audio + what you said in it
prompt = engine.create_voice_clone_prompt(
    ref_audio=str(ref_path),
    ref_text="The exact words you said in the reference recording",
    x_vector_only_mode=False,   # MUST be False
)

wavs, sr = engine.generate_voice_clone(
    text="What you want the AI to say",
    language="English",
    voice_clone_prompt=prompt,
    max_new_tokens=2048,
    temperature=0.5,
    top_p=0.85,
    repetition_penalty=1.05,
)
```

## Step 5: Best-of-N Selection (Score Against Your Real Voice)

Generate 12 candidates and keep the one that sounds most like your actual recording:

```python
from clipcannon.voice.verify import _extract_embedding
import torch, numpy as np, soundfile as sf

real_emb = _extract_embedding(Path("your_reference.wav"))

best_secs, best_wav, best_sr = -1, None, 24000
for i in range(12):
    torch.manual_seed(int(torch.randint(0, 2**31, (1,)).item()))
    wavs, sr = engine.generate_voice_clone(
        text="What you want the AI to say",
        language="English",
        voice_clone_prompt=prompt,
        max_new_tokens=2048,
        temperature=0.5,
        top_p=0.85,
        repetition_penalty=1.05,
    )
    wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()
    sf.write("_tmp.wav", wav_np, sr)
    cand_emb = _extract_embedding(Path("_tmp.wav"))
    norm = np.linalg.norm(real_emb) * np.linalg.norm(cand_emb)
    secs = float(np.dot(real_emb, cand_emb) / norm)
    if secs > best_secs:
        best_secs, best_wav, best_sr = secs, wav_np, sr

sf.write("output_raw.wav", best_wav, best_sr)
```

**Score against your REAL recording, not the profile fingerprint.** The fingerprint is averaged from 489 Demucs-processed clips. Your real recording captures your actual mic and room character.

## Step 6: Denoise (Remove Metallic Artifacts)

Qwen3-TTS outputs at 24kHz with codec quantization artifacts that sound metallic. Resemble Enhance's denoiser removes them and upsamples to 44.1kHz:

```python
import torchaudio
from resemble_enhance.enhancer.inference import denoise

dwav, sr = torchaudio.load("output_raw.wav")
dwav = dwav.mean(dim=0).float()
dwav, sr = denoise(dwav, sr, "cuda")   # outputs 44.1kHz
torchaudio.save("output_final.wav", dwav.unsqueeze(0).cpu(), sr)
```

**Use denoise() ONLY. Do NOT use enhance().** The enhance function with lambd > 0.3 changes your voice character. Denoise removes the metallic texture while keeping your voice exactly as-is.

## Settings That Matter

| Setting | Value | What Happens If Wrong |
|---------|-------|-----------------------|
| `x_vector_only_mode` | **`False`** | `True` = random accents, may sound British/Australian/etc despite high SECS |
| `temperature` | **0.3 - 0.5** | 0.8+ = accent drifts randomly between generations |
| `ref_text` | **Transcript of your reference clip** | Without it, falls back to x-vector mode |
| `max_new_tokens` | **2048** | Without limit, generation can run for 10+ minutes producing 600s of audio |
| Reference length | **5-15 seconds** | Longer = runaway generation, shorter = less style information |
| Enhancement | **`denoise()` only** | `enhance(lambd=0.9)` destroys your voice character |
| Scoring target | **Your real recording** | Profile fingerprint doesn't capture accent/style differences |

## SECS Score Interpretation

SECS (Speaker Encoder Cosine Similarity) measures WHO is speaking, not HOW they speak. Two recordings of you with different accents can both score 0.99+.

| Score | Meaning |
|-------|---------|
| 0.99+ | Near-perfect match (ICL mode with real reference) |
| 0.96-0.98 | Good identity match but accent/style may differ (x-vector mode) |
| 0.90-0.95 | Same person, noticeably different recording conditions |
| < 0.85 | Different person |

## What Can Go Wrong

**"Sounds like a different accent"** - You used `x_vector_only_mode=True` or didn't provide `ref_text`. Switch to Full ICL with your real recording.

**"Metallic/robotic quality"** - Raw Qwen3-TTS codec artifacts. Apply `denoise()` from Resemble Enhance.

**"SECS is 0.99 but it doesn't sound like me"** - SECS only measures identity, not style. Score against your real recording and use Full ICL mode.

**"Voice sounds generic/different after enhancement"** - You used `enhance()` with high lambd. Only use `denoise()`.

**"Runaway generation (minutes of audio)"** - Reference clip is too long (>15s) or no `max_new_tokens` set. Always use `max_new_tokens=2048` and trim reference to 15s.

## Complete Working Recipe

```python
from pathlib import Path
from clipcannon.voice.inference import VoiceSynthesizer, _trim_reference
from clipcannon.voice.verify import _extract_embedding
import torch, numpy as np, soundfile as sf, torchaudio
from resemble_enhance.enhancer.inference import denoise

REFERENCE_WAV = "your_reference.wav"       # YOU saying the target text
REFERENCE_TEXT = "What you said"            # Transcript of the reference
TARGET_TEXT = "What you want the AI to say" # Can be different from reference
N_CANDIDATES = 12
TEMPERATURE = 0.5

synth = VoiceSynthesizer()
engine = synth._ensure_engine()
real_emb = _extract_embedding(Path(REFERENCE_WAV))

ref_path = _trim_reference(Path(REFERENCE_WAV))
prompt = engine.create_voice_clone_prompt(
    ref_audio=str(ref_path),
    ref_text=REFERENCE_TEXT,
    x_vector_only_mode=False,
)

best_secs, best_wav, best_sr = -1, None, 24000
for i in range(N_CANDIDATES):
    torch.manual_seed(int(torch.randint(0, 2**31, (1,)).item()))
    wavs, sr = engine.generate_voice_clone(
        text=TARGET_TEXT, language="English", voice_clone_prompt=prompt,
        max_new_tokens=2048, temperature=TEMPERATURE, top_p=0.85,
        repetition_penalty=1.05,
    )
    wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()
    sf.write("_tmp.wav", wav_np, sr)
    cand_emb = _extract_embedding(Path("_tmp.wav"))
    norm = np.linalg.norm(real_emb) * np.linalg.norm(cand_emb)
    secs = float(np.dot(real_emb, cand_emb) / norm)
    if secs > best_secs:
        best_secs, best_wav, best_sr = secs, wav_np, sr

sf.write("output_raw.wav", best_wav, best_sr)

dwav, dsr = torchaudio.load("output_raw.wav")
dwav, dsr = denoise(dwav.mean(dim=0).float(), dsr, "cuda")
torchaudio.save("output_final.wav", dwav.unsqueeze(0).cpu(), dsr)

print(f"SECS vs real voice: {best_secs:.4f}")
synth.release()
```

## Results

| Metric | Value |
|--------|-------|
| SECS vs real voice | **0.9941** |
| WER (word accuracy) | 0.0000 (perfect) |
| Output sample rate | 44,100 Hz |
| Generation time (12 candidates) | ~90s on RTX 5090 |
| Denoise time | ~5s |
