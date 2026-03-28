# AI Voice Agent Benchmarks: Comprehensive Report

**Date**: 2026-03-28
**Scope**: All major benchmarks, metrics, leaderboards, and evaluation frameworks for AI voice agents (customer service, sales, phone agents, conversational AI)

---

## Table of Contents

1. [End-to-End Voice Agent Benchmarks](#1-end-to-end-voice-agent-benchmarks)
2. [Speech Quality Metrics](#2-speech-quality-metrics)
3. [ASR / Speech-to-Text Benchmarks](#3-asr--speech-to-text-benchmarks)
4. [TTS / Text-to-Speech Benchmarks](#4-tts--text-to-speech-benchmarks)
5. [Speaker Similarity & Voice Cloning Benchmarks](#5-speaker-similarity--voice-cloning-benchmarks)
6. [Dialogue & Conversation Benchmarks](#6-dialogue--conversation-benchmarks)
7. [Latency Benchmarks](#7-latency-benchmarks)
8. [Industry KPIs for Voice AI](#8-industry-kpis-for-voice-ai)
9. [Voice Agent Testing Platforms](#9-voice-agent-testing-platforms)
10. [Provider Comparisons](#10-provider-comparisons)
11. [What to Benchmark (Summary)](#11-what-to-benchmark-summary)

---

## 1. End-to-End Voice Agent Benchmarks

### 1.1 tau-Voice (Sierra AI)

The definitive full-duplex voice agent benchmark.

| Detail | Value |
|--------|-------|
| **Full Name** | tau-Voice: Benchmarking Full-Duplex Voice Agents on Real-World Domains |
| **Creator** | Sierra AI (Bret Taylor's customer service AI company) |
| **Published** | March 2026 (arxiv 2603.13686) |
| **Leaderboard** | taubench.com |

**What It Tests**: Full-duplex voice agent performance on grounded, real-world tasks combining task completion + conversation management (turn-taking, interruptions, backchanneling).

**Methodology**: 278 complex multi-turn tasks across real-world domains. Uses a controllable voice user simulator with diverse accents, realistic audio environments, and rich turn-taking dynamics. Simulation is decoupled from wall-clock time. Agents must navigate conversations, adhere to domain policies, and interact with tools/databases.

**Key Metrics**: Pass@1 (task completion rate), capability retention vs text.

**Current Results**:

| System | Task Completion (Clean) | Task Completion (Noise + Accents) |
|--------|------------------------|----------------------------------|
| GPT-5 (text reasoning) | 85% | -- |
| Best voice agent | 51% | 38% |
| Worst voice agent | 31% | 26% |

**Key Findings**:
- Voice agents retain only 30-45% of their text capability
- 79-90% of failures stem from agent behavior, not evaluation setup
- Authentication is the bottleneck -- mishearing names/emails causes cascading failures
- Leaderboard includes OpenAI Realtime, Gemini, xAI full-duplex providers

---

### 1.2 VoiceAgentBench

| Detail | Value |
|--------|-------|
| **Full Name** | VoiceAgentBench: Are Voice Assistants Ready for Agentic Tasks? |
| **Creator** | Academic consortium |
| **Published** | October 2025 (arxiv 2510.07978) |

**What It Tests**: Voice assistants on realistic, tool-driven agentic tasks.

**Methodology**: 6,000+ synthetic spoken queries across English and 6 Indic languages. Spans single-tool invocations, multi-tool workflows, multi-turn dialogue, and safety evaluations.

**Key Metrics**: Tool selection accuracy, API call structure correctness, parameter filling accuracy, refusal rate (adversarial safety).

**Results**: ASR-LLM pipelines outperform end-to-end SpeechLMs, achieving up to 60.6% average parameter-filling accuracy on English. SpeechLMs exhibit sharper degradation on Indic languages.

**Key Finding**: Persistent challenges in sequential/multi-tool reasoning, multi-turn dialogue, safety robustness, and cross-lingual generalization.

---

### 1.3 VoiceBench

| Detail | Value |
|--------|-------|
| **Full Name** | VoiceBench: Benchmarking LLM-Based Voice Assistants |
| **Creator** | Chen et al. (NUS + collaborators) |
| **Published** | 2024, actively updated through 2025 |
| **GitHub** | github.com/MatthewCYM/VoiceBench |

**What It Tests**: LLM-based voice assistants across general knowledge, instruction following, safety alignment, and robustness.

**Methodology**: 10 dataset subsets with ~7,800+ samples including both TTS-generated and human-recorded speech. Uses GPT-4o-mini as evaluator. Covers open-ended QA, multiple-choice QA, instruction following, reasoning, safety, and multi-turn QA.

**Datasets**: alpacaeval, wildvoice (human-recorded, diverse accents), mmsu (12 domains from MMLU-Pro), sd-qa, ifeval, bbh (reasoning), advbench (safety), openbookqa, mtbench, commoneval.

**Leaderboard**: Active, includes GPT-4o-Audio, Whisper+GPT-4o, Mini-Omni2, and others.

---

### 1.4 VocalBench

| Detail | Value |
|--------|-------|
| **Full Name** | VocalBench: Benchmarking the Vocal Conversational Abilities for Speech Interaction Models |
| **Creator** | SJTU OmniAgent (Shanghai Jiao Tong University) |
| **Published** | May 2025 |
| **GitHub** | github.com/SJTU-OmniAgent/VocalBench |

**What It Tests**: Speech conversational abilities across 4 dimensions.

**Methodology**: ~24,000 curated instances in English and Mandarin across: semantic quality, acoustic performance, conversational abilities, and robustness (14 user-oriented characteristics).

**Robustness Testing**: White noise, background noise, reverberation, far-field, packet loss, clipping distortion.

**Key Metrics**: Real-time factor (computing latency), single/multi-round chat, instruction following, emotion-aware responses, safety alignment.

---

### 1.5 VoiceAssistant-Eval

| Detail | Value |
|--------|-------|
| **Full Name** | VoiceAssistant-Eval: Benchmarking AI Assistants across Listening, Speaking, and Viewing |
| **Published** | September 2025 (arxiv 2509.22651) |

**What It Tests**: AI assistants across 3 modalities: listening (natural sounds, music, spoken dialogue), speaking (multi-turn dialogue, role-play), and viewing (images).

**Scale**: 10,497 curated examples spanning 13 task categories.

---

### 1.6 Salesforce Enterprise Agent Benchmark

| Detail | Value |
|--------|-------|
| **Full Name** | Benchmarking Voice and Text Agents for Enterprise Workflows |
| **Creator** | Salesforce AI Research & Engineering |
| **Published** | 2025 |

**What It Tests**: AI agent performance across complex enterprise workflows in both text and voice.

**Domains**: Healthcare appointment management, financial transactions, inbound sales, e-commerce order processing.

**Key Metrics**: Accuracy (correct task completion) and efficiency (conversational length, token usage).

**Results**:
- Financial tasks are the most error-prone
- Voice tasks show 5-8% performance drop vs text
- Agents often skip mandatory verification steps
- Open-source release planned

---

## 2. Speech Quality Metrics

### 2.1 MOS (Mean Opinion Score)

| Detail | Value |
|--------|-------|
| **Standard** | ITU-T P.800 |
| **Scale** | 1 (bad) to 5 (excellent) |
| **Industry Adoption** | Universal |

**What It Measures**: Subjective speech quality rated by human listeners.

**Score Guide**:
| Score | Quality |
|-------|---------|
| 4.3-4.5 | Rivals human speech |
| 3.8-4.2 | Production quality |
| 3.0-3.7 | Acceptable |
| <3.0 | Poor |

**Variants**: CMOS (Comparative MOS), SMOS (Speaker MOS for similarity).

**Limitation**: Expensive, slow, requires human panels.

---

### 2.2 DNSMOS (Deep Noise Suppression MOS)

| Detail | Value |
|--------|-------|
| **Creator** | Microsoft |
| **Type** | Non-intrusive (no reference needed) |
| **Standard** | Based on ITU-T P.835 |

**What It Measures**: Predicted MOS without human listeners. Evaluates noise suppressors and general speech quality.

**How It Works**: Deep neural network trained on human MOS ratings; predicts overall quality, speech quality (SIG), background quality (BAK), and overall quality (OVRL) on a 1-5 scale.

**Score Guide**: 3.5+ good; 4.0+ excellent.

**Update**: DNSMOS Pro (2024) -- reduced-size DNN with probabilistic MOS prediction.

---

### 2.3 UTMOS

| Detail | Value |
|--------|-------|
| **Full Name** | UTokyo-SaruLab MOS Prediction System |
| **Creator** | University of Tokyo (Saeki et al., 2022) |

**What It Measures**: Automatic MOS prediction for synthetic speech naturalness.

**How It Works**: Ensemble learning over self-supervised speech representations (wav2vec 2.0, HuBERT). UTMOSv2 (2024) improves robustness to out-of-domain conditions.

**Performance**: Pearson correlation ~0.82 with human MOS ratings. Same 1-5 scale as MOS; 4.0+ is production-quality TTS.

---

### 2.4 PESQ (Perceptual Evaluation of Speech Quality)

| Detail | Value |
|--------|-------|
| **Standard** | ITU-T P.862 (2001) |
| **Type** | Intrusive (requires clean reference) |
| **Scale** | -0.5 to 4.5 (MOS-LQO) |

**Score Guide**: 3.5+ good quality; 4.0+ excellent.

**Limitation**: Requires clean reference signal; does not handle time-varying delay well.

**Industry Adoption**: Telecom standard, VoIP quality testing.

---

### 2.5 POLQA

| Detail | Value |
|--------|-------|
| **Standard** | ITU-T P.863 (successor to PESQ) |
| **Scale** | 1-5 (MOS-LQO) |

**What It Measures**: Same as PESQ but handles super-wideband audio (up to 14 kHz), HD voice, and better models modern codecs.

**Industry Adoption**: Telecom, 5G voice quality testing, VoLTE.

---

### 2.6 NISQA

| Detail | Value |
|--------|-------|
| **Creator** | Gabriel Mittag (TU Berlin) |
| **Type** | Non-intrusive |
| **GitHub** | github.com/gabrielmittag/NISQA |

**What It Measures**: Non-intrusive speech quality using Mel-spectrograms + CNN-Self-Attention.

**Dimensions**: Overall MOS plus 4 sub-dimensions: Noisiness, Coloration, Discontinuity, Loudness.

**Industry Adoption**: VoIP monitoring, TTS evaluation, conferencing quality.

---

### 2.7 TTSDS2

| Detail | Value |
|--------|-------|
| **Full Name** | TTSDS2: Robust Objective Evaluation for Human-Quality Synthetic Speech |
| **Published** | SSW 2025 |

**What It Measures**: Distributional similarity between synthetic and natural speech (rather than sample-level MOS).

**Key Advantage**: Only evaluation metric that formally qualifies as "robust" with lowest correlation 0.49+ with human judgments across all domains.

---

## 3. ASR / Speech-to-Text Benchmarks

### 3.1 Word Error Rate (WER)

The universal ASR metric.

**Formula**: (Substitutions + Deletions + Insertions) / Total Words x 100

| Score | Quality |
|-------|---------|
| <5% | Enterprise-grade |
| 5-10% | Good |
| 10-15% | Fair |
| >15% | Poor |

**Character Error Rate (CER)**: Same formula at character level. Best for non-whitespace languages (Mandarin, Japanese, Thai).

---

### 3.2 LibriSpeech Benchmark

| Detail | Value |
|--------|-------|
| **Scale** | ~1,000 hours of 16kHz read English speech |
| **Source** | LibriVox audiobooks |
| **Subsets** | test-clean (easy), test-other (hard with accents/noise) |
| **Current Leader** | NVIDIA Canary-Qwen-2.5B at 1.3% WER (test-clean) |

---

### 3.3 Open ASR Leaderboard (Hugging Face)

| Detail | Value |
|--------|-------|
| **Creator** | Hugging Face (hf-audio) |
| **URL** | huggingface.co/spaces/hf-audio/open_asr_leaderboard |
| **Models Ranked** | 60+ |

**Current Leaders (late 2025)**:

| Model | Avg WER | Speed (RTFx) |
|-------|---------|-------------|
| NVIDIA Canary-Qwen-2.5B | 5.63% | -- |
| IBM Granite-Speech-3.3-8B | ~5.7% | -- |
| NVIDIA Parakeet CTC 1.1B | -- | 2793.75x |
| Whisper Large v3 | ~10.6% | 68.56x |

---

### 3.4 Artificial Analysis STT Leaderboard

| Detail | Value |
|--------|-------|
| **Creator** | Artificial Analysis |
| **Metric** | AA-WER (weighted: 50% AA-AgentTalk, 25% VoxPopuli, 25% Earnings22) |
| **Models Ranked** | 47 |

**Current Leaders**:

| Rank | Model | AA-WER |
|------|-------|--------|
| 1 | ElevenLabs Scribe v2 | 2.3% |
| 2 | Google Gemini 3 Pro (High) | 2.9% |
| 3 | Mistral Voxtral Small | 2.9% |
| 4 | Google Gemini 3.1 Pro Preview | 2.9% |
| 5 | Google Gemini 2.5 Pro | 3.0% |

**Speed Leaders**: Deepgram Base (590.2x real-time), Deepgram Nova-2 (513.5x).

**Cost Leaders**: Google Gemini 2.0 Flash Lite ($0.19/1000 min).

---

### 3.5 AssemblyAI Voice Agent STT Benchmark

| Detail | Value |
|--------|-------|
| **Creator** | AssemblyAI |
| **Focus** | Streaming STT specifically for voice agent use cases |

**Results**:

| Provider | WER (Streaming) | Latency |
|----------|-----------------|---------|
| AssemblyAI Universal-2 | 14.5% | 300-600ms |
| Deepgram Nova-3 | 18.3% | <300ms |
| AssemblyAI Universal-3 Pro | Improved | Telephony-optimized |

**Key Insight**: Standard WER benchmarks don't predict voice agent performance -- entities, punctuation, and domain accuracy matter more than overall WER.

---

### 3.6 SUPERB

| Detail | Value |
|--------|-------|
| **Full Name** | Speech processing Universal PERformance Benchmark |
| **Creator** | CMU, MIT, Johns Hopkins, et al. |
| **URL** | superbbenchmark.org |

**What It Tests**: Self-supervised speech model performance across 10+ tasks: ASR, speaker identification, speaker verification, speaker diarization, emotion recognition, intent classification, slot filling, phoneme recognition, keyword spotting, query-by-example.

**Extension**: ML-SUPERB covers 143 languages including endangered ones.

---

### 3.7 MLPerf Inference ASR Benchmark

| Detail | Value |
|--------|-------|
| **Creator** | MLCommons |
| **Selected Model** | Whisper-Large-V3 on LibriSpeech |

**Purpose**: Hardware/infrastructure benchmarking for ASR deployment (measures inference speed at scale, not model quality).

---

## 4. TTS / Text-to-Speech Benchmarks

### 4.1 Artificial Analysis Speech Arena (TTS Leaderboard)

| Detail | Value |
|--------|-------|
| **Creator** | Artificial Analysis |
| **Methodology** | Blind pairwise human preference voting (Elo rating system) |
| **URL** | artificialanalysis.ai/text-to-speech/arena |
| **Models Ranked** | 68 |

**Current Leaders**:

| Rank | Model | Elo Score |
|------|-------|-----------|
| 1 | Inworld TTS 1.5 Max | 1,236 |
| 2 | ElevenLabs Eleven v3 | 1,196 |
| 3 | Inworld TTS 1 Max | 1,184 |
| 4 | Inworld TTS 1.5 Mini | 1,182 |
| 5 | MiniMax Speech 2.8 HD | 1,175 |
| 6 | MiniMax Speech 2.8 Turbo | 1,160 |
| 7 | StepFun ST260212 | 1,149 |
| 8 | MiniMax Speech 2.6 Turbo | 1,147 |
| 9 | Inworld TTS 1 | 1,145 |
| 10 | ElevenLabs Multilingual v2 | 1,129 |

**Best Open Source**: Kokoro 82M v1.0 (Elo 1,072, $0.65/M chars).

---

### 4.2 Picovoice TTS Latency Benchmark

| Detail | Value |
|--------|-------|
| **Creator** | Picovoice |
| **Metric** | First Token to Speech (FTTS) latency |
| **GitHub** | github.com/Picovoice/tts-latency-benchmark |

**What It Measures**: Time from LLM first text token to TTS first audio byte.

**Results**: Picovoice Orca achieves 130ms FTTS (6.5x faster than ElevenLabs, 16x faster than some cloud solutions).

**Key Insight**: On-device processing eliminates cloud latency.

---

### 4.3 Seed-TTS Eval

| Detail | Value |
|--------|-------|
| **Creator** | ByteDance Speech |
| **GitHub** | github.com/BytedanceSpeech/seed-tts-eval |

**What It Measures**: TTS quality via WER (intelligibility) + SIM (speaker similarity).

**Methodology**: Uses WavLM-large fine-tuned on speaker verification to extract speaker embeddings; cosine similarity between reference and generated speech. 1,000 samples from Common Voice + 2,000 from DiDiSpeech-2.

**Score Guide**: SIM > 0.85 is strong; SIM > 0.90 is state-of-the-art.

**Industry Adoption**: THE standard for evaluating voice cloning and zero-shot TTS models.

---

### 4.4 VoiceMOS Challenge / AudioMOS Challenge

| Detail | Value |
|--------|-------|
| **Creator** | Academic consortium |
| **URL** | sites.google.com/view/voicemos-challenge |

**What It Tests**: How well neural systems can predict human MOS ratings for speech.

**VoiceMOS 2024 Tracks**: (1) High-quality TTS, (2) Singing voice synthesis + voice conversion, (3) Semi-supervised quality prediction.

**Evolved Into**: AudioMOS Challenge 2025.

---

### 4.5 Balacoon TTS Leaderboard

| Detail | Value |
|--------|-------|
| **Creator** | Balacoon |
| **Tools** | speech_gen_eval (open-source), speech_gen_eval_testsets, speech_gen_baselines |
| **Hosted** | Hugging Face Spaces |

**Metrics**: Intelligibility (WER on synthetic speech), Naturalness (predicted MOS), Similarity (cosine similarity of speaker embeddings).

---

## 5. Speaker Similarity & Voice Cloning Benchmarks

### 5.1 SECS (Speaker Encoder Cosine Similarity)

**What It Measures**: Cosine similarity between speaker embeddings of reference and generated speech.

**Common Encoders**:

| Encoder | Dimensions | Training |
|---------|-----------|----------|
| WavLM-large (microsoft/wavlm-base-plus-sv) | 512 | VoxCeleb -- ClonEval standard |
| SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb) | 192 | VoxCeleb -- academic standard |
| Qwen3-TTS ECAPA-TDNN | 2048 | Internal |

**Score Guide (WavLM)**:

| Score Range | Interpretation |
|-------------|---------------|
| 0.95-0.99 | Same person, same session (natural ceiling) |
| 0.85-0.95 | Same person, different session |
| 0.70-0.85 | Same person, very different conditions |
| <0.70 | Likely different speakers |

**Academic SOTA**: NaturalSpeech 3 at 0.891; VALL-E 2 "human parity" at 0.881.

---

### 5.2 ClonEval

| Detail | Value |
|--------|-------|
| **Full Name** | ClonEval: An Open Voice Cloning Benchmark |
| **Creator** | AMU-CAI (Adam Mickiewicz University) |
| **Published** | April 2025 |
| **GitHub** | github.com/amu-cai/cloneval |

**What It Tests**: Voice cloning quality using WavLM speaker embeddings + audio feature analysis.

**Methodology**: Standardized one-shot/few-shot protocols, data splits, scoring library, and leaderboard submissions. Supports neutral/emotional/expressive/accented datasets (CREMA-D, LibriSpeech, RAVDESS, SAVEE, TESS).

**Tested Models**: OuteTTS, SpeechT5, VALL-E X, WhisperSpeech, XTTS-v2 (XTTS-v2 scored highest).

**Key Feature**: Architecture-agnostic, reproducible, leaderboard-based.

---

### 5.3 RVCBench

| Detail | Value |
|--------|-------|
| **Full Name** | RVCBench: Benchmarking the Robustness of Voice Cloning Across Modern Audio Generation Models |
| **Published** | February 2026 |

**Focus**: Robustness of voice cloning under adversarial conditions.

---

### 5.4 Speaker Verification EER

| Detail | Value |
|--------|-------|
| **Metric** | Equal Error Rate |
| **Good Scores** | <5% strong; <1% state-of-the-art |
| **Used By** | VoxCeleb Speaker Recognition Challenge, NIST SRE |

**What It Measures**: The point where false acceptance rate equals false rejection rate.

---

## 6. Dialogue & Conversation Benchmarks

### 6.1 VAQI (Voice Agent Quality Index)

| Detail | Value |
|--------|-------|
| **Creator** | Deepgram |
| **Scale** | 0-100 |

**What It Measures**: Conversational quality across timing, interruptions, and response coverage.

**Formula**: Single score combining:
- Interruptions (I): 40% weight -- normalized interruption count per conversation
- Missed Response Windows (M): 40% weight -- normalized missed response count
- Latency (L): 20% weight -- log-transformed, normalized latency

**Methodology**: 121 conversations per provider, 16kHz PCM over websockets, 50ms chunk intervals, microsecond-precision timing, each provider runs 10+ times per conversation. Test scenario: food ordering with natural pauses, fillers, contradictions, background noise.

**Results**:

| Provider | VAQI Score |
|----------|-----------|
| Deepgram | 71.5 (highest) |
| OpenAI | ~67 (6.4% lower) |
| ElevenLabs | ~55 (29.3% lower) |

**Key Finding**: Some providers have near-perfect interruption handling but multi-second delays; others have great latency but inconsistent performance.

---

### 6.2 AudioBench

| Detail | Value |
|--------|-------|
| **Full Name** | AudioBench: A Universal Benchmark for Audio Large Language Models |
| **Published** | June 2024, accepted NAACL 2025 |
| **GitHub** | github.com/AudioLLMs/AudioBench |

**What It Tests**: Audio LLM capabilities across 8 tasks and 26 datasets (7 newly proposed).

**Three Aspects**: Speech understanding, audio scene understanding, voice/paralinguistic understanding.

---

### 6.3 S2SBench

| Detail | Value |
|--------|-------|
| **Full Name** | S2SBench: A Benchmark for Quantifying Intelligence Degradation in Speech-to-Speech LLMs |

**What It Measures**: Performance degradation when LLMs operate in speech-to-speech mode vs text. Focuses on sentence continuation, commonsense reasoning under audio input.

---

### 6.4 WildSpeech-Bench

| Detail | Value |
|--------|-------|
| **Full Name** | WILDSPEECH-BENCH: Benchmarking End-to-End Speech LLMs in the Wild |

**Focus**: Full speech-to-speech interaction and expressive, generative capabilities of speech LLMs under real-world conditions.

---

### 6.5 SOVA-Bench

| Detail | Value |
|--------|-------|
| **Full Name** | SOVA-Bench: Benchmarking the Speech Conversation Ability for LLM-based Systems |
| **Published** | Interspeech 2025 |

**Focus**: Speech conversation ability specifically for LLM-based systems.

---

### 6.6 VCB Bench

| Detail | Value |
|--------|-------|
| **Full Name** | VCB Bench: An Evaluation Benchmark for Audio-Grounded LLM Conversational Agents |
| **Published** | October 2025 |

**Focus**: Audio-grounded conversational agent capabilities.

---

### 6.7 Hallucination Benchmarks for Voice

| Benchmark | Focus |
|-----------|-------|
| TruthfulQA | LLM veracity (applicable to voice agent responses) |
| FaithDial | Dialogue faithfulness throughout conversation |
| Wizard of Wikipedia (WoW) | Knowledge-grounded dialogue |
| CMU-DoG | Document-grounded dialogue |
| TopicalChat | Open-domain knowledge dialogue |
| HUN Rate (Hallucination-Under-Noise) | Voice-specific: hallucination rate when audio quality degrades. Target: <1% for production |

---

## 7. Latency Benchmarks

### 7.1 Industry Latency Targets

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Time to First Word (TTFW) | <400ms | <600ms | >800ms |
| Voice Assistant Response Time (VART) P95 | <800ms | -- | -- |
| End-to-End Latency (mouth-to-ear) | <800ms | -- | >1200ms |
| Real-Time Factor (RTF) | <1.0 required | -- | -- |
| Human Expectation (natural conversation) | 300-500ms | -- | -- |

---

### 7.2 Voice Agent Provider Latency

| Provider | Avg Latency | Notes |
|----------|-------------|-------|
| Telnyx | sub-200ms | Co-located GPU + telecom infra |
| Synthflow | ~400ms (claimed) | |
| Retell AI | ~600ms | Consistently fastest middleware |
| Vapi | ~465ms optimal, 1.5s+ default | Requires extensive optimization |
| Bland AI | ~800ms | Infrastructure-level approach |
| Twilio | ~950ms | Focus on reliability over speed |
| Vonage | 800-1200ms | |

---

### 7.3 TTS TTFB (Time to First Byte)

| Provider | Avg TTFB | Notes |
|----------|----------|-------|
| Picovoice Orca | 130ms | On-device, 6.5x faster than ElevenLabs |
| Smallest.ai Lightning V2 | 212.88ms | Cloud-based |
| Cartesia | 219.76ms | Similar real-time, 3x slower full audio |
| ElevenLabs | 512.48ms | Highest quality but slower |

---

### 7.4 STT Latency

| Provider | Latency | WER (Streaming) |
|----------|---------|-----------------|
| Deepgram Nova-3 | <300ms | 18.3% |
| AssemblyAI Universal-2 | 300-600ms | 14.5% |
| Gladia | <300ms partial, ~700ms final | Varies |

---

### 7.5 Production Monitoring Thresholds

From Hamming/LiveKit production analysis:

| Metric | Threshold |
|--------|-----------|
| P90 end-to-end latency | <3.5 seconds |
| P99 end-to-end latency | <5 seconds |
| STT TTFT | <200ms excellent, <500ms good |
| WER | <5% enterprise, <8% acceptable |
| Task completion | >90% |
| Connection drop rate | <15% |

---

## 8. Industry KPIs for Voice AI

### 8.1 Core Metrics

| KPI | Formula | Good Score | Excellent |
|-----|---------|-----------|-----------|
| **Containment Rate** | (AI-Handled / Total) x 100 | 60-80% | 85%+ |
| **CSAT** | (Satisfied / Total Survey) x 100 | 80-90% | >90% |
| **First Call Resolution (FCR)** | (Resolved First Contact / Total) x 100 | 70-80% | 80%+ |
| **Average Handle Time (AHT)** | Includes hold, transfers, after-call | 5-8 min | <5 min |
| **Intent Recognition Accuracy** | (Correct / Total Utterances) x 100 | >90% | >95% |
| **Task Success Rate (TSR)** | (Successful / Total Interactions) x 100 | >75% | >85% |
| **Safety Refusal Rate** | Correct refusal on adversarial prompts | >95% | >99% |
| **Compliance Score** | Regulatory adherence | -- | 100% |

---

### 8.2 Use-Case Specific Benchmarks

From Hamming's analysis of 1M+ production calls:

| Use Case | WER Target | TSR Target | FCR Target | Latency P95 |
|----------|-----------|-----------|-----------|-------------|
| Contact Center Support | <8% | >75% | >70% | <1000ms |
| Appointment Scheduling | <5% | >90% | >85% | <800ms |
| Healthcare | <5% | >85% | N/A | <1200ms |
| E-commerce | <6% | >85% | N/A | <700ms |

---

## 9. Voice Agent Testing Platforms

### 9.1 Hamming AI

| Detail | Value |
|--------|-------|
| **Focus** | Enterprise voice agent testing and production monitoring |
| **Scale** | Analyzed 4M+ production calls across 10K+ voice agents (2025-2026) |
| **Metrics** | 50+ built-in + unlimited custom scorers |

**Key Features**:
- Automatic test scenario generation from system prompts
- 95-96% agreement with human evaluators
- 4-layer evaluation framework: Infrastructure -> Agent Execution -> User Reaction -> Business Outcome
- Voice-specific: turn-taking latency, interruptions, time to first word, talk-to-listen ratio, barge-in detection

---

### 9.2 Braintrust

| Detail | Value |
|--------|-------|
| **Focus** | AI observability and voice agent evaluation |
| **Methodology Weights** | Simulation 25%, Evaluation 25%, Monitoring 20%, Integration 15%, Scale 10% |

**Metrics**: Response latency (p50/p95/p99), goal completion, CSAT, STT confidence, intent classification confidence, escalation frequency.

---

### 9.3 Maxim AI

| Detail | Value |
|--------|-------|
| **Focus** | End-to-end GenAI evaluation and observability for multimodal agents |
| **Evaluators** | SNR, WER, custom dashboards |

**Features**: No-code evaluation configuration, conversation-level assessment (goal accomplishment, clarifying questions, unexpected input handling, context maintenance).

---

### 9.4 Cekura

| Detail | Value |
|--------|-------|
| **Focus** | Automated QA for voice AI and chat AI agents |
| **Backed By** | Y Combinator |

**Key Features**:
- Automatic scenario generation with persona/accent/noise variations
- Hierarchical metrics framework
- Voice-specific signals: gibberish detection, interruption tracking, latency, sentiment, pitch
- Multi-turn conversations with branching logic, interruptions, persona variations
- CI/CD regression testing on every prompt/model change

---

### 9.5 Deepgram (VAQI)

See [Section 6.1](#61-vaqi-voice-agent-quality-index) for details. The only standardized single-score benchmark (0-100) for voice agent conversational quality.

---

## 10. Provider Comparisons

### 10.1 Voice Agent Platforms

| Feature | Bland AI | Vapi | Retell AI | Air AI |
|---------|----------|------|-----------|--------|
| Latency | ~800ms | ~700ms | ~600ms | Varies |
| Approach | Infrastructure (end-to-end) | Middleware (BYO models) | Middleware | Full-stack |
| Call Capacity | 20,000+/hr | Moderate | Moderate | Limited |
| HIPAA | Included | $1,000/mo add-on | Included | N/A |
| Pricing | $0.09/min connected | $0.05/min + extras ($0.13-0.31 total) | Per-minute | Varies |

---

### 10.2 STT Providers (by AA-WER)

| Rank | Provider | WER |
|------|----------|-----|
| 1 | ElevenLabs Scribe v2 | 2.3% |
| 2 | Google Gemini 3 Pro | 2.9% |
| 3 | Mistral Voxtral Small | 2.9% |
| 4 | Google Gemini 2.5 Pro | 3.0% |
| 5 | Deepgram Nova-3 | 5.26-6.84% |
| 6 | Whisper Large v3 | ~10.6% |

---

### 10.3 TTS Providers (by Speech Arena Elo)

| Rank | Provider | Elo |
|------|----------|-----|
| 1 | Inworld TTS 1.5 Max | 1,236 |
| 2 | ElevenLabs Eleven v3 | 1,196 |
| 3 | Inworld TTS 1 Max | 1,184 |
| 4 | MiniMax Speech 2.8 HD | 1,175 |
| 5 | Kokoro 82M (best OSS) | 1,072 |

---

## 11. What to Benchmark (Summary)

A complete voice agent evaluation should cover these layers:

| Layer | Key Metrics | Targets |
|-------|------------|---------|
| **ASR** | WER, CER, entity accuracy, streaming latency | WER <5%, latency <300ms |
| **Understanding** | Intent accuracy, slot filling, context retention | Intent >95% |
| **LLM/Reasoning** | Task completion, hallucination rate, safety refusal | TSR >85%, hallucination <1%, safety >99% |
| **TTS** | MOS, speaker similarity (SECS), TTFB | MOS >4.0, SECS >0.85, TTFB <300ms |
| **Conversation** | VAQI, turn-taking, interruption handling, barge-in | VAQI >70, barge-in recovery >90% |
| **End-to-End** | Mouth-to-ear latency, task success rate, FCR | Latency <800ms, TSR >85%, FCR >75% |
| **Business** | Containment rate, CSAT, AHT reduction | Containment >70%, CSAT >80% |

---

## Sources

### End-to-End Benchmarks
- [tau-Voice Paper](https://arxiv.org/abs/2603.13686) | [Leaderboard](https://taubench.com/)
- [Sierra AI Blog: tau3-Bench](https://sierra.ai/blog/bench-advancing-agent-benchmarking-to-knowledge-and-voice)
- [VoiceAgentBench](https://arxiv.org/abs/2510.07978)
- [VoiceBench GitHub](https://github.com/MatthewCYM/VoiceBench)
- [VocalBench GitHub](https://github.com/SJTU-OmniAgent/VocalBench)
- [VoiceAssistant-Eval](https://arxiv.org/abs/2509.22651)
- [Salesforce Enterprise Agent Benchmark](https://www.salesforce.com/blog/enterprise-agent-benchmark/)

### Speech Quality
- [DNSMOS Pro Paper](https://www.isca-archive.org/interspeech_2024/cumlin24_interspeech.pdf)
- [NISQA GitHub](https://github.com/gabrielmittag/NISQA)
- [TTSDS2 Paper](https://www.isca-archive.org/ssw_2025/minixhofer25_ssw.pdf)
- [UTMOS Topic](https://www.emergentmind.com/topics/utmos)

### ASR
- [Open ASR Leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard)
- [Artificial Analysis STT](https://artificialanalysis.ai/speech-to-text)
- [AssemblyAI Benchmarks](https://www.assemblyai.com/benchmarks)
- [Deepgram STT Benchmarks](https://deepgram.com/learn/speech-to-text-benchmarks)
- [Soniox Benchmarks](https://soniox.com/benchmarks)
- [SUPERB Benchmark](https://superbbenchmark.github.io/)

### TTS
- [Artificial Analysis Speech Arena](https://artificialanalysis.ai/text-to-speech/arena)
- [Picovoice TTS Latency Benchmark](https://github.com/Picovoice/tts-latency-benchmark)
- [Seed-TTS Eval](https://github.com/BytedanceSpeech/seed-tts-eval)
- [VoiceMOS Challenge](https://sites.google.com/view/voicemos-challenge)
- [Balacoon TTS Leaderboard](https://balacoon.com/blog/tts_leaderboard/)

### Voice Cloning
- [ClonEval GitHub](https://github.com/amu-cai/cloneval)
- [RVCBench](https://arxiv.org/html/2602.00443)

### Dialogue
- [Deepgram VAQI](https://deepgram.com/learn/voice-agent-quality-index)
- [AudioBench GitHub](https://github.com/AudioLLMs/AudioBench)
- [S2SBench](https://arxiv.org/html/2505.14438v1)
- [WildSpeech-Bench](https://arxiv.org/pdf/2506.21875)

### Latency & Industry
- [Telnyx Voice AI Latency Comparison](https://telnyx.com/resources/voice-ai-agents-compared-latency)
- [Hamming AI Metrics Guide](https://hamming.ai/resources/voice-agent-evaluation-metrics-guide)
- [Hamming AI QA Framework](https://hamming.ai/resources/guide-to-ai-voice-agents-quality-assurance)
- [Braintrust: How to Evaluate Voice Agents](https://www.braintrust.dev/articles/how-to-evaluate-voice-agents)

### Provider Comparisons
- [Bland AI Comparison](https://www.bland.ai/blogs/bland-ai-vs-retell-vs-vapi-vs-air)
- [Retell AI Comparisons](https://www.retellai.com/comparisons/retell-vs-vapi)
- [Inworld TTS Benchmark](https://inworld.ai/resources/best-voice-ai-tts-apis-for-real-time-voice-agents-2026-benchmarks)
