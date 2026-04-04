"""Y4M named pipe writer — feeds frames to Chromium's fake video capture.

Runs as a separate process. Reads state from a control file:
- state=idle → writes idle frames in a loop
- state=speaking → writes frames from a rendered video file
- state=stop → exits

Usage:
    python y4m_pipe_writer.py /path/to/pipe.y4m /path/to/idle_video.mp4

Chromium uses: --use-file-for-fake-video-capture=/path/to/pipe.y4m
"""
import os
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np

PIPE_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/santa_video.y4m"
IDLE_VIDEO = sys.argv[2] if len(sys.argv) > 2 else str(Path("~/.voiceagent/drivers/santa_idle_web.mp4").expanduser())
CONTROL_FILE = "/tmp/santa_video_state.json"
FPS = 15
WIDTH = 640
HEIGHT = 480


def load_idle_frames(video_path: str) -> list[bytes]:
    """Load idle video frames as Y4M frame data."""
    cap = cv2.VideoCapture(video_path)
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        # Convert BGR → YUV I420
        yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
        frames.append(yuv.tobytes())
    cap.release()

    # Ping-pong
    if len(frames) > 2:
        frames = frames + frames[-2:0:-1]

    return frames


def load_speaking_frames(video_path: str) -> list[bytes]:
    """Load rendered speaking video frames."""
    if not Path(video_path).exists():
        return []
    cap = cv2.VideoCapture(video_path)
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
        frames.append(yuv.tobytes())
    cap.release()
    return frames


def read_state() -> dict:
    """Read control state from file."""
    import json
    try:
        with open(CONTROL_FILE) as f:
            return json.load(f)
    except Exception:
        return {"state": "idle"}


def main():
    print(f"Loading idle frames from {IDLE_VIDEO}...")
    idle_frames = load_idle_frames(IDLE_VIDEO)
    if not idle_frames:
        print(f"ERROR: No frames from {IDLE_VIDEO}")
        sys.exit(1)
    print(f"Loaded {len(idle_frames)} idle frames (ping-pong)")

    # Create named pipe
    if os.path.exists(PIPE_PATH):
        os.unlink(PIPE_PATH)
    os.mkfifo(PIPE_PATH)
    print(f"Created FIFO: {PIPE_PATH}")
    print(f"Waiting for reader (Chromium)...")

    # Open pipe for writing (blocks until a reader connects)
    pipe = open(PIPE_PATH, "wb")
    print("Reader connected!")

    # Write Y4M header
    header = f"YUV4MPEG2 W{WIDTH} H{HEIGHT} F{FPS}:1 Ip A1:1 C420\n".encode()
    pipe.write(header)
    pipe.flush()

    frame_interval = 1.0 / FPS
    idx = 0
    current_state = "idle"
    speaking_frames = []
    speaking_idx = 0

    while True:
        t0 = time.monotonic()

        # Check state
        state = read_state()
        new_state = state.get("state", "idle")

        if new_state == "stop":
            break

        if new_state != current_state:
            if new_state == "speaking":
                video_file = state.get("video", "")
                speaking_frames = load_speaking_frames(video_file)
                speaking_idx = 0
                print(f"Switching to SPEAKING ({len(speaking_frames)} frames)")
            elif new_state == "idle":
                print("Switching to IDLE")
            current_state = new_state

        # Get frame data
        if current_state == "speaking" and speaking_frames:
            if speaking_idx < len(speaking_frames):
                frame_data = speaking_frames[speaking_idx]
                speaking_idx += 1
            else:
                # Speaking video ended → back to idle
                current_state = "idle"
                frame_data = idle_frames[idx % len(idle_frames)]
                idx += 1
        else:
            frame_data = idle_frames[idx % len(idle_frames)]
            idx += 1

        # Write frame
        try:
            pipe.write(b"FRAME\n")
            pipe.write(frame_data)
            pipe.flush()
        except BrokenPipeError:
            print("Pipe broken (reader disconnected)")
            break

        # Maintain FPS
        elapsed = time.monotonic() - t0
        sleep = max(0, frame_interval - elapsed)
        if sleep > 0:
            time.sleep(sleep)

    pipe.close()
    os.unlink(PIPE_PATH)
    print("Done.")


if __name__ == "__main__":
    main()
