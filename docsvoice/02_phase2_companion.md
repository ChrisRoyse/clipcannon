# Phase 2: Windows Companion + Capture System

**Timeline**: Weeks 4-5
**Exit Criteria**: Companion captures screenshots, audio, clipboard on Windows. Files appear in shared volume. Docker container can read them.
**Predecessor**: Phase 1 (core voice pipeline working)

---

## What Gets Built

A lightweight Windows-native Python application (`voiceagent-capture.exe`) that runs in the system tray and continuously captures: screenshots (per-monitor, change-detected), active window metadata, microphone audio, and system audio loopback. Clipboard is voice-controlled (read/write on command, no polling). All output goes to `C:\voiceagent_data\` which is mounted into the Docker container.

This phase does NOT connect to OCR Provenance yet. That's Phase 3.

---

## 1. Project Structure

```
src/companion/
    __init__.py
    main.py                    # Entry point, tray icon, main loop
    config.py                  # CompanionConfig from %APPDATA%\voiceagent\companion_config.json
    http_api.py                # FastAPI on :8770 (status, pause/resume, capture-now)

    capture/
        __init__.py
        screen.py              # PIL.ImageGrab per-monitor capture + pHash dedup
        window.py              # win32gui active window title + process name
        browser_url.py         # Win32 COM Shell.Application for Chrome/Edge URL
        clipboard.py           # Voice-controlled clipboard read/write via HTTP endpoints
        audio.py               # sounddevice mic + system audio 15-min segments

    health/
        __init__.py
        heartbeat.py           # Write companion_status.json every 30s
        docker_check.py        # Poll Docker container :8080/health every 30s

    tray/
        __init__.py
        icon.py                # pystray system tray icon (green/yellow/red)

    voiceagent-capture.spec    # PyInstaller spec file
```

---

## 2. Screenshot Capture (`capture/screen.py`)

### 2.1 Screen Change Detection

Check every 5 seconds if screen content changed. Only capture on change.

```python
from PIL import ImageGrab
import imagehash
import ctypes
import ctypes.wintypes

class ScreenCapture:
    DIFF_INTERVAL_S = 5
    PHASH_THRESHOLD = 5
    MAX_PER_DAY = 190

    def __init__(self, config, output_dir: Path):
        self.output_dir = output_dir
        self.config = config
        self.monitor_hashes: dict[int, imagehash.ImageHash] = {}
        self.today_count = 0

    def get_monitors(self) -> list[dict]:
        """Win32 EnumDisplayMonitors → list of monitor bounds."""
        monitors = []
        def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
            rect = lprcMonitor.contents
            monitors.append({
                "index": len(monitors),
                "x": rect.left, "y": rect.top,
                "w": rect.right - rect.left, "h": rect.bottom - rect.top
            })
            return True
        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double
        )
        ctypes.windll.user32.EnumDisplayMonitors(
            None, None, MonitorEnumProc(callback), 0
        )
        return monitors

    def capture_changed(self) -> list[tuple[Path, dict]]:
        """Capture only monitors that changed. Returns [(path, metadata), ...]."""
        if self.today_count >= self.MAX_PER_DAY:
            return []

        changed = []
        monitors = self.get_monitors()
        window_meta = get_active_window()  # from window.py

        # Check privacy blocklist against window title
        if self._is_blocked(window_meta.get("title", "")):
            return []

        for mon in monitors:
            bbox = (mon["x"], mon["y"], mon["x"]+mon["w"], mon["y"]+mon["h"])
            img = ImageGrab.grab(bbox=bbox)
            phash = imagehash.phash(img)

            prev = self.monitor_hashes.get(mon["index"])
            if prev is not None and (phash - prev) < self.PHASH_THRESHOLD:
                continue  # unchanged

            self.monitor_hashes[mon["index"]] = phash
            timestamp = datetime.now().strftime("%H%M%S")
            date_dir = self.output_dir / datetime.now().strftime("%Y-%m-%d")
            date_dir.mkdir(parents=True, exist_ok=True)

            png_path = date_dir / f"screenshot_{timestamp}_mon{mon['index']}.png"
            img.save(png_path, "PNG")

            metadata = {
                "timestamp": datetime.now().isoformat(),
                "monitor": mon["index"],
                "phash": str(phash),
                "processed": False,
                **window_meta
            }
            json_path = png_path.with_suffix(".json")
            json_path.write_text(json.dumps(metadata, indent=2))

            changed.append((png_path, metadata))
            self.today_count += 1

        return changed

    def _is_blocked(self, title: str) -> bool:
        title_lower = title.lower()
        return any(b.lower() in title_lower for b in self.config.privacy_blocklist)
```

---

## 3. Active Window Metadata (`capture/window.py`)

```python
import win32gui
import win32process
import psutil

def get_active_window() -> dict:
    """Native Win32. Instant. No subprocess."""
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        proc = psutil.Process(pid)
        process_name = proc.name().replace(".exe", "")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        process_name = "unknown"

    # Classify application category
    category = _classify_app(process_name, title)

    return {
        "app": process_name,
        "title": title,
        "pid": pid,
        "category": category  # code, browser, terminal, email, chat, other
    }

def _classify_app(process: str, title: str) -> str:
    p = process.lower()
    t = title.lower()
    if p in ("code", "devenv", "idea64", "pycharm64", "webstorm64"):
        return "code"
    if p in ("chrome", "msedge", "firefox", "brave"):
        return "browser"
    if p in ("windowsterminal", "cmd", "powershell", "wsl"):
        return "terminal"
    if p in ("outlook", "thunderbird") or "mail" in t:
        return "email"
    if p in ("slack", "discord", "teams") or "slack" in t or "discord" in t:
        return "chat"
    return "other"
```

---

## 4. Browser URL Extraction (`capture/browser_url.py`)

```python
def get_browser_url() -> str | None:
    """Get URL from Chrome/Edge via COM Shell.Application."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        for window in shell.Windows():
            name = str(getattr(window, "FullName", "")).lower()
            if "chrome" in name or "msedge" in name:
                return window.LocationURL
    except Exception:
        pass
    return None
```

---

## 5. Clipboard (Voice-Controlled, No Polling)

**No background clipboard polling.** Clipboard is only accessed on explicit voice command:

- **"Clip"** → Docker container sends agent's last response text to companion via `POST /clipboard/write`. Companion writes it to Windows clipboard. User can Ctrl+V immediately.
- **"Save clipboard"** → Docker container calls companion `GET /clipboard/read`. Companion reads clipboard once, returns text. Docker ingests into `va_clipboard` database.

```python
# capture/clipboard.py — HTTP endpoints only, no background thread

import win32clipboard

def read_clipboard() -> str:
    """One-time read. Called only when user says 'save clipboard'."""
    win32clipboard.OpenClipboard()
    try:
        text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    except TypeError:
        text = ""  # non-text content (image, etc.)
    finally:
        win32clipboard.CloseClipboard()
    return text

def write_clipboard(text: str):
    """Write agent response to clipboard. Called when user says 'clip'."""
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()
```

---

## 6. Audio Recording (`capture/audio.py`)

Two independent recorders: microphone and system audio loopback.

```python
import sounddevice as sd
import numpy as np
from scipy.io import wavfile

class AudioRecorder:
    SAMPLE_RATE = 16000
    SEGMENT_S = 900  # 15 minutes

    def __init__(self, device_name: str, output_subdir: str, output_dir: Path):
        self.device = self._find_device(device_name)
        self.out_dir = output_dir / "audio" / output_subdir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def record_segment(self) -> Path:
        """Record one 15-minute WAV segment. Blocking."""
        frames = int(self.SAMPLE_RATE * self.SEGMENT_S)
        audio = sd.rec(frames, samplerate=self.SAMPLE_RATE,
                       channels=1, dtype="int16", device=self.device)
        sd.wait()
        timestamp = datetime.now().strftime("%H%M%S")
        path = self.out_dir / f"segment_{timestamp}.wav"
        wavfile.write(str(path), self.SAMPLE_RATE, audio)
        return path

    def _find_device(self, name: str) -> int:
        for i, dev in enumerate(sd.query_devices()):
            if name.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
                return i
        raise ValueError(f"Audio device '{name}' not found")

# Usage:
# mic = AudioRecorder("default", "mic", output_dir)
# loopback = AudioRecorder("Stereo Mix", "system", output_dir)
```

---

## 7. Heartbeat (`health/heartbeat.py`)

```python
class Heartbeat:
    INTERVAL_S = 30

    def __init__(self, status_path: Path):
        self.status_path = status_path
        self.started_at = datetime.now()
        self.captures_today = 0
        self.errors_last_hour = 0

    def write(self):
        status = {
            "status": "running",
            "last_heartbeat": datetime.now().isoformat(),
            "captures_today": self.captures_today,
            "disk_usage_mb": self._disk_usage(),
            "mic_recording": True,
            "system_audio_recording": True,
            "clipboard_available": true,
            "errors_last_hour": self.errors_last_hour,
            "uptime_s": (datetime.now() - self.started_at).total_seconds()
        }
        self.status_path.write_text(json.dumps(status, indent=2))

    def run_loop(self):
        while True:
            self.write()
            time.sleep(self.INTERVAL_S)
```

---

## 8. System Tray Icon (`tray/icon.py`)

```python
import pystray
from PIL import Image

class TrayIcon:
    def __init__(self, on_pause, on_resume, on_quit):
        self.icon = pystray.Icon(
            "voiceagent",
            icon=self._make_icon("green"),
            title="Voice Agent Capture",
            menu=pystray.Menu(
                pystray.MenuItem("Pause", on_pause),
                pystray.MenuItem("Resume", on_resume),
                pystray.MenuItem("Quit", on_quit),
            )
        )

    def set_status(self, status: str):
        """green=capturing, yellow=paused, red=error"""
        self.icon.icon = self._make_icon(status)

    def _make_icon(self, color: str) -> Image:
        img = Image.new("RGB", (64, 64), color)
        return img

    def run(self):
        self.icon.run()
```

---

## 9. HTTP API (`http_api.py`)

```python
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok", "uptime_s": get_uptime()}

@app.get("/status")
def status():
    return read_heartbeat_json()

@app.get("/window")
def window():
    return get_active_window()

@app.post("/pause")
def pause():
    capture_daemon.pause()
    return {"paused": True}

@app.post("/resume")
def resume():
    capture_daemon.resume()
    return {"paused": False}

@app.post("/capture-now")
def capture_now():
    results = capture_daemon.capture_now()
    return {"captured": len(results)}

@app.get("/clipboard/read")
def clipboard_read():
    from capture.clipboard import read_clipboard
    return {"text": read_clipboard()}

@app.post("/clipboard/write")
def clipboard_write(body: dict):
    from capture.clipboard import write_clipboard
    write_clipboard(body["text"])
    return {"written": True}
```

---

## 10. Main Entry Point (`main.py`)

```python
import threading

def main():
    config = load_config()
    output_dir = Path(config.output_dir)

    # Start capture modules in threads
    screen = ScreenCapture(config.capture, output_dir / "captures")
    mic = AudioRecorder(config.audio.mic_device, "mic", output_dir)
    loopback = AudioRecorder(config.audio.system_audio_device, "system", output_dir)
    heartbeat = Heartbeat(output_dir / "companion_status.json")
    tray = TrayIcon(on_pause=pause_all, on_resume=resume_all, on_quit=quit_all)

    threads = [
        threading.Thread(target=screen_loop, args=(screen,), daemon=True),
        threading.Thread(target=mic_record_loop, args=(mic,), daemon=True),
        threading.Thread(target=loopback_record_loop, args=(loopback,), daemon=True),
        threading.Thread(target=heartbeat.run_loop, daemon=True),
        threading.Thread(target=run_http_api, daemon=True),
    ]
    for t in threads:
        t.start()

    # Tray icon runs on main thread (required by Windows)
    tray.run()

def screen_loop(screen):
    while True:
        screen.capture_changed()
        time.sleep(screen.DIFF_INTERVAL_S)

def mic_record_loop(recorder):
    while True:
        recorder.record_segment()  # blocks for 15 min

if __name__ == "__main__":
    main()
```

---

## 11. Packaging

```bash
# Build on Windows (CMD or PowerShell, NOT WSL2)
cd src\companion
pip install pyinstaller pillow pywin32 sounddevice imagehash pystray requests psutil numpy scipy fastapi uvicorn
pyinstaller --onefile --windowed --name voiceagent-capture main.py
# Output: dist\voiceagent-capture.exe
```

---

## 12. Verification Checklist

All tests run on Windows 11, NOT WSL2.

| # | Test | Source of Truth | Expected |
|---|------|----------------|----------|
| 1 | Screenshot capture | PNG file on disk | >10KB, correct resolution |
| 2 | Per-monitor capture | Separate PNGs per monitor | One per monitor, tagged `mon0`, `mon1` |
| 3 | pHash dedup | File count after 10 unchanged captures | Only 1 file saved, 9 skipped |
| 4 | Privacy blocklist | Capture while 1Password focused | No PNG saved |
| 5 | Active window | JSON sidecar content | Contains app name, title, category |
| 6 | Browser URL | URL field in metadata | Contains actual URL from Chrome/Edge |
| 7 | Clipboard read (on demand) | GET /clipboard/read | Returns current clipboard text |
| 8 | Clipboard write | POST /clipboard/write with test text | Text appears in Windows clipboard (Ctrl+V works) |
| 9 | Mic recording | WAV file in audio/mic/ | 16kHz, mono, ~15MB for 15 min |
| 10 | System audio recording | WAV file in audio/system/ | 16kHz, mono, device accessible |
| 11 | Heartbeat file | companion_status.json | Updated within last 30s |
| 12 | HTTP /health | curl localhost:8770/health | `{"status":"ok"}` |
| 13 | HTTP /pause + /resume | Capture stops/starts | No new PNGs during pause |
| 14 | Tray icon visible | Windows system tray | Green icon present |
| 15 | Disk limit respected | Fill to 500MB then capture | Next capture skipped, warning logged |
| 16 | Daily cap respected | Set max_per_day=5, capture 6 | 6th capture skipped |

**Edge cases:**
- No Stereo Mix device enabled → error on startup, clear message to enable it
- All monitors identical content → only first changed monitor captured
- Clipboard contains image (not text) → skip gracefully, no crash
- 190 captures/day reached → stop capturing, log warning, resume next day
