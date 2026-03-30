#!/usr/bin/env bash
# Jarvis Voice Agent - background service launcher
# Auto-configures PulseAudio TCP bridge for WSL2 mic/speaker access,
# then starts the voice agent in wake-word-listening mode.

set -euo pipefail

# --- Ensure Windows PulseAudio is running ---
if [ -f /proc/sys/fs/binfmt_misc/WSLInterop ]; then
    if ! tasklist.exe 2>/dev/null | grep -qi "pulseaudio.exe"; then
        echo "[jarvis] Starting Windows PulseAudio..."
        powershell.exe -Command "Start-Process -FilePath 'C:\Program Files (x86)\PulseAudio\bin\pulseaudio.exe' -ArgumentList '--exit-idle-time=-1','--daemonize=no' -WindowStyle Hidden" >/dev/null 2>&1
        sleep 3  # Give it time to initialize audio devices
    else
        echo "[jarvis] Windows PulseAudio already running"
    fi
fi

# --- PulseAudio TCP bridge for WSL2 ---
if [ -f /proc/sys/fs/binfmt_misc/WSLInterop ]; then
    WIN_HOST=$(ip route show default | awk '{print $3}')
    if pactl info >/dev/null 2>&1; then
        : # PulseAudio already working
    else
        export PULSE_SERVER="tcp:${WIN_HOST}"
    fi

    # Always prefer TCP for real mic input (WSLg RDP returns near-silence)
    if ! echo "$PULSE_SERVER" | grep -q "^tcp:"; then
        export PULSE_SERVER="tcp:${WIN_HOST}"
    fi

    # Verify TCP connection
    if ! pactl info >/dev/null 2>&1; then
        echo "[jarvis] ERROR: PulseAudio TCP bridge not available at $PULSE_SERVER" >&2
        echo "[jarvis] Ensure Windows PulseAudio is running with module-native-protocol-tcp" >&2
        exit 1
    fi
    echo "[jarvis] PulseAudio: $PULSE_SERVER"
fi

# --- Conda environment ---
CONDA_BASE="${HOME}/miniconda3"
if [ -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]; then
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
    conda activate base 2>/dev/null || true
fi

# --- Start voice agent ---
cd /home/cabdru/clipcannon
exec python -m voiceagent talk --voice boris
