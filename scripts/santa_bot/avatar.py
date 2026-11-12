"""Avatar face engines (state + init) and speak() for the Santa bot.

Owns the mutable avatar state (_face_warper, _physics_face, _semantic_model, the
_semantic_*_identity tensors and _ref_transcripts); other modules read it through this
module (avatar._physics_face), not through copied names.
"""
import asyncio
import logging
import re
import time
from pathlib import Path

import numpy as np

from .config import SANTA_IDLE_VIDEO, _y4m_writer, select_prosody_ref
from .models import get_tts

logger = logging.getLogger("santa_bot")

# ---------------------------------------------------------------------------
# Dynamic avatar setup
# ---------------------------------------------------------------------------
_face_warper = None  # DEPRECATED: replaced by PhysicsFaceEngine
_physics_face = None
_semantic_model = None  # SemanticCloneModel for meaning-aware face control
# Cached mean embeddings for runtime — computed from training data on model load.
# At runtime, prosody varies per-frame but identity embeddings stay constant.
_semantic_vis_identity = None   # (1152,) mean SigLIP for Santa
_semantic_emo_identity = None   # (1024,) mean Wav2Vec2 emotion for Santa
_semantic_sem_identity = None   # (768,) mean Nomic semantic for Santa
_semantic_spk_identity = None   # (512,) mean WavLM speaker for Santa
_semantic_sent_identity = None  # (384,) mean MiniLM sentence for Santa
_semantic_voice_identity = None # (192,) mean ECAPA voice for Santa


def init_face_warper():
    """Initialize the face warper from the reference frame (legacy fallback)."""
    global _face_warper
    import subprocess
    src_video = SANTA_IDLE_VIDEO
    if not Path(src_video).exists():
        return
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", src_video, "-vframes", "1",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0 or len(r.stdout) == 0:
            return
        ref_frame = np.frombuffer(r.stdout, dtype=np.uint8).reshape(720, 1280, 3)
        from phoenix.render.face_warper import FaceWarper
        _face_warper = FaceWarper(ref_frame, max_pixel_shift=20)
        if _face_warper.ready:
            logger.info("Face warper ready (legacy fallback)")
        else:
            _face_warper = None
            logger.warning("Face warper: no face detected")
    except Exception as e:
        logger.warning("Face warper init failed: %s", e)


def init_physics_face():
    """Initialize the physics-based face animation engine."""
    global _physics_face
    try:
        from phoenix.render.physics_face import PhysicsFaceEngine
        _physics_face = PhysicsFaceEngine(sample_rate=24000, fps=15)
        logger.info("PhysicsFaceEngine ready (deterministic audio-to-face)")
    except Exception as e:
        logger.warning("PhysicsFaceEngine init failed: %s", e)


def init_semantic_model():
    """Initialize the SemanticCloneModel for meaning-aware face control.

    Loads the trained model from disk. Falls back to PhysicsFaceEngine
    if the semantic model is not available.
    """
    global _semantic_model
    model_dir = Path("~/.clipcannon/models/santa/semantic_model").expanduser()
    # Try best model first, then final
    for fname in ["semantic_model_best.pt", "semantic_model_final.pt"]:
        model_path = model_dir / fname
        if model_path.exists():
            try:
                import torch
                from phoenix.clone.semantic_model import SemanticCloneModel
                checkpoint = torch.load(str(model_path), map_location="cuda", weights_only=False)
                _semantic_model = SemanticCloneModel()
                _semantic_model.load_state_dict(checkpoint["model_state"])
                _semantic_model = _semantic_model.to("cuda").eval()
                logger.info("SemanticCloneModel loaded from %s (%.1fM params)",
                            model_path, _semantic_model.param_count / 1e6)
                # Load cached identity embeddings from training data
                _load_identity_embeddings()
                return
            except Exception as e:
                logger.warning("SemanticCloneModel load failed (%s): %s", fname, e)
    logger.info("No semantic model found -- using PhysicsFaceEngine only")


def _load_identity_embeddings() -> None:
    """Load mean embeddings from training NPZ as runtime identity vectors."""
    global _semantic_vis_identity, _semantic_emo_identity, _semantic_sem_identity
    global _semantic_spk_identity, _semantic_sent_identity, _semantic_voice_identity
    import torch
    emb_path = Path("~/.clipcannon/models/santa/embeddings/all_embeddings.npz").expanduser()
    if not emb_path.exists():
        logger.error("Identity embeddings not found at %s", emb_path)
        return
    data = np.load(str(emb_path), allow_pickle=True)
    _semantic_vis_identity = torch.from_numpy(data["vis_emb"].mean(axis=0)).float().cuda()
    _semantic_emo_identity = torch.from_numpy(data["emo_emb"].mean(axis=0)).float().cuda()
    _semantic_sem_identity = torch.from_numpy(data["sem_emb"].mean(axis=0)).float().cuda()
    _semantic_spk_identity = torch.from_numpy(data["spk_emb"].mean(axis=0)).float().cuda()
    _semantic_sent_identity = torch.from_numpy(data["sent_emb"].mean(axis=0)).float().cuda()
    _semantic_voice_identity = torch.from_numpy(data["voice_emb"].mean(axis=0)).float().cuda()
    logger.info("Loaded identity embeddings: vis=%d emo=%d sem=%d spk=%d sent=%d voice=%d",
                _semantic_vis_identity.shape[0], _semantic_emo_identity.shape[0],
                _semantic_sem_identity.shape[0], _semantic_spk_identity.shape[0],
                _semantic_sent_identity.shape[0], _semantic_voice_identity.shape[0])


def _set_ref_transcripts(transcripts: dict) -> None:
    """Store pre-transcribed prosody refs where speak() reads them via globals()."""
    globals()["_ref_transcripts"] = transcripts


async def speak(page, text):
    """Synthesize speech with prosody-matched refs, laugh clips, and inject to meeting."""
    global _laugh_idx
    import base64
    import soundfile as sf

    tts = get_tts()
    try:
        logger.info("speak() starting for: '%s'", text[:60])

        # Select prosody-matched reference clip for emotional voice variation
        cached_transcripts = globals().get("_ref_transcripts", {})
        ref_path = select_prosody_ref(text)
        if ref_path and Path(ref_path).exists():
            ref_text = cached_transcripts.get(ref_path)
            tts.set_ref_audio(ref_path, ref_text=ref_text)
            logger.info("Prosody ref: %s", Path(ref_path).name)

        # Strip all tags — synthesize clean text only
        clean = re.sub(r'\[.*?\]', '', text).strip()
        if not clean:
            logger.warning("speak(): empty text after cleanup")
            return

        sr = 24000
        t0 = time.time()
        a = await tts.synthesize(clean)
        tts_ms = (time.time() - t0) * 1000
        logger.info("TTS: %.0fms for %.1fs audio", tts_ms, len(a) / sr)

        if len(a) == 0:
            logger.warning("TTS returned empty audio")
            return

        segs = [a]

        if not segs:
            return
        audio = np.concatenate(segs)
        audio_duration = len(audio) / sr
        logger.info("Audio: %.1fs (%d samples), %d segments",
                     audio_duration, len(audio), len(segs))
        del segs

        # Compute physics-based face animation and send to browser
        # Pipeline: PhysicsFaceEngine -> (optional) SemanticCloneModel -> blendshapes
        if _physics_face is not None:
            try:
                from phoenix.render.physics_face import PhysicsFaceEngine
                _physics_face.reset()
                face_states = _physics_face.process_audio_batch(audio)

                # If semantic model is available, enhance blendshapes
                if _semantic_model is not None:
                    try:
                        import torch
                        blendshape_schedule = []
                        with torch.no_grad():
                            for fs in face_states:
                                # Build all 7 modality inputs from PhysicsFaceEngine features.
                                # At runtime we construct approximations from available audio data.
                                # The model requires all 7 — no fallbacks.
                                pro = torch.zeros(1, 12, device="cuda")
                                pro[0, 0] = fs._f0       # f0_mean (raw Hz)
                                pro[0, 1] = fs._f0 * 0.2  # f0_range estimate
                                pro[0, 2] = fs._energy * 100  # energy (raw scale)
                                pro[0, 3] = 180.0         # speaking_rate WPM est
                                pro[0, 4] = fs.effort * 300  # emphasis proxy (raw scale)
                                pro[0, 5] = 0.03          # rising pitch default

                                # Emotion: 1024d Wav2Vec2 — use cached identity embedding
                                emo = _semantic_emo_identity.unsqueeze(0)
                                # Visual: 1152d SigLIP — use cached identity
                                vis = _semantic_vis_identity.unsqueeze(0)
                                # Semantic: 768d Nomic — use cached identity
                                sem = _semantic_sem_identity.unsqueeze(0)
                                # Speaker: 512d WavLM — use cached identity
                                spk = _semantic_spk_identity.unsqueeze(0)
                                # Sentence: 384d MiniLM — use cached identity
                                sent = _semantic_sent_identity.unsqueeze(0)
                                # Voice: 192d ECAPA — use cached identity
                                voi = _semantic_voice_identity.unsqueeze(0)

                                out = _semantic_model(
                                    visual=vis, emotion=emo, prosody=pro,
                                    semantic=sem, speaker=spk, sentence=sent,
                                    voice=voi,
                                )
                                bs_tensor = out["blendshapes"][0].cpu().numpy()
                                bs_dict = {}
                                # Map 52-dim tensor to ARKit names
                                arkit_names = [
                                    "jawOpen", "jawForward", "jawLeft", "jawRight",
                                    "mouthSmileLeft", "mouthSmileRight", "mouthPucker",
                                    "mouthFunnel", "mouthClose", "mouthStretchLeft",
                                    "mouthStretchRight", "mouthUpperUpLeft",
                                    "mouthUpperUpRight", "mouthLowerDownLeft",
                                    "mouthLowerDownRight", "mouthShrugUpper",
                                    "mouthShrugLower", "mouthRollUpper", "mouthRollLower",
                                    "mouthPressLeft", "mouthPressRight",
                                    "mouthDimpleLeft", "mouthDimpleRight",
                                    "browInnerUp", "browDownLeft", "browDownRight",
                                    "browOuterUpLeft", "browOuterUpRight",
                                    "eyeBlinkLeft", "eyeBlinkRight",
                                    "eyeWideLeft", "eyeWideRight",
                                    "eyeSquintLeft", "eyeSquintRight",
                                    "eyeLookUpLeft", "eyeLookUpRight",
                                    "eyeLookDownLeft", "eyeLookDownRight",
                                    "eyeLookInLeft", "eyeLookInRight",
                                    "eyeLookOutLeft", "eyeLookOutRight",
                                    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
                                    "noseSneerLeft", "noseSneerRight",
                                    "mouthFrownLeft", "mouthFrownRight",
                                    "mouthLeft", "mouthRight", "tongueOut",
                                ]
                                for j, name in enumerate(arkit_names[:len(bs_tensor)]):
                                    # Blend: 60% semantic, 40% physics for smooth result
                                    physics_val = fs.to_blendshapes().get(name, 0.0)
                                    bs_dict[name] = round(
                                        0.6 * float(bs_tensor[j]) + 0.4 * physics_val, 3,
                                    )
                                blendshape_schedule.append(bs_dict)
                        logger.info("SemanticModel: %d frames enhanced", len(blendshape_schedule))
                    except Exception as e:
                        logger.warning("Semantic model failed, using physics only: %s", e)
                        blendshape_schedule = [s.to_blendshapes() for s in face_states]
                else:
                    blendshape_schedule = [s.to_blendshapes() for s in face_states]

                mouth_schedule = [round(s.jaw_open, 2) for s in face_states]
                logger.info("PhysicsFace: %d frames, jaw range %.2f-%.2f",
                            len(face_states),
                            min(mouth_schedule), max(mouth_schedule))
                await page.evaluate(
                    "schedule => { window.__santaMouthSchedule = schedule; }",
                    mouth_schedule,
                )
                await page.evaluate(
                    "schedule => { window.__santaBlendSchedule = schedule; }",
                    blendshape_schedule,
                )
            except Exception as e:
                logger.warning("PhysicsFace prep failed: %s", e)
        elif _face_warper is not None and _face_warper.ready:
            # Legacy fallback: energy-only lip sync
            try:
                from phoenix.render.lip_sync import LipSync
                lip = LipSync(fps=25, sample_rate=sr)
                lip_frames = lip.from_audio(audio)
                mouth_schedule = [round(f.mouth_open, 2) for f in lip_frames]
                logger.info("Lip sync (legacy): %d frames", len(lip_frames))
                await page.evaluate(
                    "schedule => { window.__santaMouthSchedule = schedule; }",
                    mouth_schedule,
                )
            except Exception as e:
                logger.warning("Lip sync prep failed: %s", e)

        # Inject audio into WebRTC via JavaScript WebAudio API
        audio_bytes = audio.astype(np.float32).tobytes()
        b64 = base64.b64encode(audio_bytes).decode('ascii')
        b64_len = len(b64)
        del audio, audio_bytes

        logger.info("Sending %dKB audio (%.1fs) to browser...", b64_len // 1024, audio_duration)
        try:
            # Resume AudioContext and play audio
            await page.evaluate("() => window.__santaAudioCtx && window.__santaAudioCtx.resume()")
            result = await page.evaluate(
                "([b64, sr]) => window.__santaPlayAudio(b64, sr)",
                [b64, sr],
            )
            logger.info("Audio delivered: %s", result)
        except Exception as e:
            logger.error("Audio injection failed: %s", e)
        # Wait for playback
        await asyncio.sleep(audio_duration + 0.5)
        del b64

        logger.info("Spoke: %.1fs", audio_duration)

        # Return avatar to listening state
        if _y4m_writer is not None:
            try:
                from phoenix.render.y4m_writer import AvatarState
                _y4m_writer.set_state(AvatarState.LISTENING)
            except Exception:
                pass
    except Exception as e:
        logger.error("Speak failed: %s", e)
        # Ensure avatar returns to listening even on error
        if _y4m_writer is not None:
            try:
                from phoenix.render.y4m_writer import AvatarState
                _y4m_writer.set_state(AvatarState.LISTENING)
            except Exception:
                pass
