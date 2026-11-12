"""Who is speaking, where they are on screen, and what they are talking about.

Binds three senses per transcript segment:
  * face  - which visible face track is speaking (Light-ASD logits),
  * voice - which voice cluster the segment's audio belongs to,
  * words - the transcript text and its salient terms.

Voice clusters are tied to people using the segments where the face evidence
is confident; that binding then names the speaker when the face evidence is
weak (wide shots, profile views) or absent (cutaways, off-camera speakers).
Pure numpy/sklearn; no GPU.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from clipcannon.pipeline.face_tracking import FaceAnalysis

MIN_COVER = 0.25           # a track must be visible for >= 25% of a segment
FACE_SPEAKING_FRAC = 0.40  # ...and score > 0 on >= 40% of its frames there
VOICE_MIN_MS = 1200        # segments shorter than this get no voice embedding vote
VOICE_DISTANCE = 0.75      # ECAPA cosine distance (average linkage); calibrated on
                           # this project: 0.75 separates crew/moderator/reporter exactly
BIND_MIN_SEGMENTS = 2      # confident face segments needed to bind a voice
BIND_MIN_AGREEMENT = 0.6   # share of those segments that must agree


@dataclass
class SegmentSpeaker:
    segment_id: int
    start_ms: int
    end_ms: int
    text: str
    person_id: int | None          # None = unknown / off-screen voice
    voice_cluster: int | None
    on_screen: bool                # speaker's face visible during the segment
    source: str                    # "face", "voice", "face+voice" or "none"
    face_score: float              # mean ASD logit of the chosen track
    track_ids: list[int] = field(default_factory=list)


@dataclass
class Turn:
    turn_id: int
    start_ms: int
    end_ms: int
    person_id: int | None
    voice_cluster: int | None
    speaker_key: str               # "P3", "V2" (unbound voice) or "unknown"
    on_screen_ms: int
    text: str
    keywords: list[str]
    segment_ids: list[int]
    is_question: bool


def _face_evidence(fa: FaceAnalysis, det_frame: np.ndarray, det_asd: np.ndarray,
                   s_ms: int, e_ms: int) -> tuple[int | None, float, float, list[int], set[int]]:
    """Best speaking track in [s_ms, e_ms]: (track, mean logit, speaking frac, tracks, persons)."""
    t = fa.frame_t_ms
    f0, f1 = int(np.searchsorted(t, s_ms)), int(np.searchsorted(t, e_ms))
    n = max(1, f1 - f0)
    in_win = (det_frame >= f0) & (det_frame < f1) & (fa.track_of_det >= 0)
    idx = np.nonzero(in_win)[0]
    if len(idx) == 0:
        return None, 0.0, 0.0, [], set()
    best, best_mean, best_frac = None, -1e9, 0.0
    tracks = sorted(set(int(fa.track_of_det[d]) for d in idx))
    visible_persons = set()
    for tr in tracks:
        d = idx[fa.track_of_det[idx] == tr]
        visible_persons.add(fa.tracks[tr].person_id)
        if len(d) / n < MIN_COVER:
            continue
        sc = det_asd[d]
        sc = sc[np.isfinite(sc)]
        if len(sc) == 0:
            continue
        m = float(sc.mean())
        if m > best_mean:
            best, best_mean, best_frac = tr, m, float(np.mean(sc > 0))
    return best, (best_mean if best is not None else 0.0), best_frac, tracks, visible_persons


def cluster_voices(emb: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Agglomerative (average, cosine) clustering; -1 for segments without a vote."""
    from sklearn.cluster import AgglomerativeClustering

    labels = np.full(len(emb), -1, np.int32)
    idx = np.nonzero(valid)[0]
    if len(idx) == 1:
        labels[idx] = 0
    elif len(idx) > 1:
        x = emb[idx] / np.maximum(np.linalg.norm(emb[idx], axis=1, keepdims=True), 1e-9)
        cl = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                     distance_threshold=VOICE_DISTANCE).fit(x)
        labels[idx] = cl.labels_
    return labels


def assign_speakers(
    fa: FaceAnalysis,
    det_frame: np.ndarray,
    det_asd: np.ndarray,
    segments: list[tuple[int, int, int, str]],
    voice_emb: np.ndarray | None = None,
) -> tuple[list[SegmentSpeaker], dict[int, int]]:
    """Speaker per transcript segment, plus the voice-cluster -> person binding."""
    n = len(segments)
    dur = np.array([e - s for _, s, e, _ in segments])
    if voice_emb is not None and len(voice_emb) == n:
        labels = cluster_voices(voice_emb, dur >= VOICE_MIN_MS)
    else:
        labels = np.full(n, -1, np.int32)

    face = []
    for _sid, s, e, _txt in segments:
        tr, mean, frac, tracks, persons = _face_evidence(fa, det_frame, det_asd, s, e)
        confident = tr is not None and mean > 0 and frac >= FACE_SPEAKING_FRAC
        pid = fa.tracks[tr].person_id if confident and tr is not None else None
        face.append((pid, mean, tracks, persons))

    # Bind voice clusters to people using confident face segments.
    votes: dict[int, dict[int, int]] = {}
    for (pid, _m, _t, _p), lab in zip(face, labels, strict=True):
        if pid is not None and lab >= 0:
            votes.setdefault(int(lab), {}).setdefault(pid, 0)
            votes[int(lab)][pid] += 1
    binding: dict[int, int] = {}
    for lab, v in votes.items():
        pid, cnt = max(v.items(), key=lambda kv: kv[1])
        if cnt >= BIND_MIN_SEGMENTS and cnt / sum(v.values()) >= BIND_MIN_AGREEMENT:
            binding[lab] = pid

    out: list[SegmentSpeaker] = []
    for (sid, s, e, txt), (pid, mean, tracks, persons), lab in zip(
            segments, face, labels, strict=True):
        lab_i = int(lab) if lab >= 0 else None
        voice_pid = binding.get(lab_i) if lab_i is not None else None
        if pid is not None:
            source = "face+voice" if voice_pid == pid else "face"
            person = pid
        elif voice_pid is not None:
            source, person = "voice", voice_pid
        else:
            source, person = ("voice" if lab_i is not None else "none"), None
        out.append(SegmentSpeaker(
            segment_id=sid, start_ms=s, end_ms=e, text=txt, person_id=person,
            voice_cluster=lab_i, on_screen=person is not None and person in persons,
            source=source, face_score=round(mean, 3), track_ids=tracks,
        ))
    return out, binding


_STOP_WORDS = """a an the and or but if so of to in on at for with from by as is are was
were be been being it its this that these those i you he she we they me him her us them
my your our their just like really very know think going get got go one thing things yeah
um uh well okay ok right there here what which who whom how when where why all can could
would should will do does did have has had not no yes also about into out up down then than
more most some any much many lot lots kind sort way actually say said says see"""
_STOP = set(_STOP_WORDS.split())


def _keywords(texts: list[str], k: int = 4) -> list[list[str]]:
    """Top TF-IDF terms per text, relative to the whole video."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    if not texts:
        return []
    vec = TfidfVectorizer(stop_words=sorted(_STOP), ngram_range=(1, 2), min_df=1,
                          token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z'-]{2,}\b", sublinear_tf=True)
    try:
        m = vec.fit_transform(texts)
    except ValueError:
        return [[] for _ in texts]
    terms = np.array(vec.get_feature_names_out())
    out = []
    for row in m:
        r = row.toarray().ravel()
        top = [terms[i] for i in np.argsort(-r)[: k * 3] if r[i] > 0]
        picked: list[str] = []
        for term in top:  # drop unigrams already inside a chosen bigram
            if not any(term in p.split() or p in term.split() for p in picked):
                picked.append(term)
            if len(picked) == k:
                break
        out.append(picked)
    return out


def build_turns(speakers: list[SegmentSpeaker], max_gap_ms: int = 1500) -> list[Turn]:
    """Merge consecutive segments by the same speaker into turns."""
    groups: list[list[SegmentSpeaker]] = []
    for sp in speakers:
        key = _speaker_key(sp)
        if (groups and _speaker_key(groups[-1][-1]) == key and key != "unknown"
                and sp.start_ms - groups[-1][-1].end_ms <= max_gap_ms):
            groups[-1].append(sp)
        else:
            groups.append([sp])
    texts = [" ".join(s.text.strip() for s in g) for g in groups]
    kws = _keywords(texts)
    turns = []
    for i, (g, text) in enumerate(zip(groups, texts, strict=True)):
        turns.append(Turn(
            turn_id=i + 1, start_ms=g[0].start_ms, end_ms=g[-1].end_ms,
            person_id=g[0].person_id, voice_cluster=g[0].voice_cluster,
            speaker_key=_speaker_key(g[0]),
            on_screen_ms=sum(s.end_ms - s.start_ms for s in g if s.on_screen),
            text=text, keywords=kws[i], segment_ids=[s.segment_id for s in g],
            is_question=bool(re.search(r"\?\s*$", text)) or bool(
                re.match(r"(?i)\s*(hi|hello|good (morning|afternoon)|this is|my question)", text)),
        ))
    return turns


def _speaker_key(sp: SegmentSpeaker) -> str:
    if sp.person_id is not None:
        return f"P{sp.person_id}"
    if sp.voice_cluster is not None:
        return f"V{sp.voice_cluster}"
    return "unknown"
