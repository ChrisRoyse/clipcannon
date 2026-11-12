"""Paths, clip parameters, the TeleologicalLabel record and the viseme tables."""
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ID = "proj_2ea7221d"
DB_PATH = Path.home() / ".clipcannon" / "projects" / PROJECT_ID / "analysis.db"
SOURCE_VIDEO = Path.home() / ".clipcannon" / "projects" / PROJECT_ID / "source" / "2026-04-03 04-23-11.mp4"
VOCALS_WAV = Path.home() / ".clipcannon" / "projects" / PROJECT_ID / "stems" / "vocals.wav"
LANDMARKS_FILE = Path.home() / ".clipcannon" / "models" / "santa" / "face_landmarks_25fps.npz"
OUTPUT_DIR = Path.home() / "echomimic_v3" / "datasets" / "santa_teleological"
OUTPUT_LABELS = OUTPUT_DIR / "labels.json"

# Clip parameters
# 49 frames at 25fps: (49-1)/4 + 1 = 13 latent temporal frames (required by VAE)
CLIP_FRAMES = 49
TARGET_FPS = 25
CLIP_DURATION_MS = int(CLIP_FRAMES * 1000 / TARGET_FPS)  # 1960 ms (not 2000)
SRC_WIDTH = 2560
SRC_HEIGHT = 1440


@dataclass
class TeleologicalLabel:
    """Complete teleological label for a training clip."""
    clip_id: str
    # Temporal anchor
    start_ms: int
    end_ms: int
    center_word: str
    center_word_ms: int

    # Linguistic units
    words: list = field(default_factory=list)
    phonemes: list = field(default_factory=list)
    visemes: list = field(default_factory=list)
    viseme_sequence: list = field(default_factory=list)  # per-frame viseme (49 entries)

    # Face geometry per frame (from precomputed landmarks)
    face_bbox_per_frame: list = field(default_factory=list)   # [x1,y1,x2,y2] per frame
    mouth_bbox_per_frame: list = field(default_factory=list)  # [x1,y1,x2,y2] per frame
    mouth_center_per_frame: list = field(default_factory=list)  # [x,y] per frame

    # Detection quality (flags for filtering bad clips)
    frames_detected: int = 0       # How many of 49 frames had real detection
    mean_face_score: float = 0.0

    # Prosody
    prosody_f0_mean: float = 0.0
    prosody_f0_std: float = 0.0
    prosody_energy_mean: float = 0.0
    prosody_energy_peak: float = 0.0
    prosody_speaking_rate: float = 0.0
    prosody_energy_level: str = "medium"
    prosody_contour_type: str = "flat"
    prosody_has_emphasis: bool = False
    prosody_has_breath: bool = False

    # Emotion
    emotion_arousal: float = 0.19
    emotion_valence: float = 0.51
    emotion_energy: float = 0.0

    # Context flags
    has_speech: bool = True
    clip_category: str = "speaking"


# Viseme mapping based on CMU ARPAbet phonemes
PHONEME_TO_VISEME = {
    "SIL": "SIL", "": "SIL",
    # Bilabials (lip closure)
    "P": "P", "B": "P", "M": "P",
    # Labiodentals
    "F": "F", "V": "F",
    # Dentals
    "TH": "TH", "DH": "TH",
    # Alveolars
    "T": "T", "D": "T", "N": "T", "L": "T", "S": "T", "Z": "T",
    # Post-alveolars
    "SH": "SH", "ZH": "SH", "CH": "SH", "JH": "SH",
    # Velars
    "K": "K", "G": "K", "NG": "K",
    "HH": "SIL",
    # Approximants
    "R": "R", "W": "W", "Y": "Y",
    # Front vowels
    "IY": "IY", "IY0": "IY", "IY1": "IY", "IY2": "IY",
    "IH": "IH", "IH0": "IH", "IH1": "IH", "IH2": "IH",
    "EH": "EH", "EH0": "EH", "EH1": "EH", "EH2": "EH",
    "AE": "AH", "AE0": "AH", "AE1": "AH", "AE2": "AH",
    "AH": "AH", "AH0": "AH", "AH1": "AH", "AH2": "AH",
    "ER": "ER", "ER0": "ER", "ER1": "ER", "ER2": "ER",
    "AA": "AA", "AA0": "AA", "AA1": "AA", "AA2": "AA",
    "AO": "AO", "AO0": "AO", "AO1": "AO", "AO2": "AO",
    "UH": "UH", "UH0": "UH", "UH1": "UH", "UH2": "UH",
    "UW": "UW", "UW0": "UW", "UW1": "UW", "UW2": "UW",
    "EY": "EY", "EY0": "EY", "EY1": "EY", "EY2": "EY",
    "AY": "AY", "AY0": "AY", "AY1": "AY", "AY2": "AY",
    "OY": "OY", "OY0": "OY", "OY1": "OY", "OY2": "OY",
    "AW": "AW", "AW0": "AW", "AW1": "AW", "AW2": "AW",
    "OW": "OW", "OW0": "OW", "OW1": "OW", "OW2": "OW",
}

ALL_VISEMES = [
    "SIL", "P", "F", "TH", "T", "SH", "K", "R", "W", "Y",
    "IY", "IH", "EH", "AH", "ER", "AA", "AO", "UH", "UW",
    "EY", "AY", "OY", "AW", "OW",
]
