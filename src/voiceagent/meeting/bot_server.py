"""HTTP server managing the Santa meeting bot lifecycle.

POST /join  {"url": "https://meet.google.com/xxx-yyyy-zzz"}
POST /leave
GET  /status -> {"state": "idle|joining|in-meeting", ...}
"""
from __future__ import annotations

import json, logging, os, signal, subprocess, sys, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock, Thread

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [BotServer] %(levelname)s %(message)s")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_BOT_SCRIPT = _PROJECT_ROOT / "scripts" / "santa_meet_bot.py"
HOST, PORT, XVFB_DISPLAY = "127.0.0.1", 9877, ":99"


class BotManager:
    """Manages a single bot process with Xvfb."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.state = "idle"
        self.meeting_url: str | None = None
        self.xvfb_proc: subprocess.Popen | None = None
        self.bot_proc: subprocess.Popen | None = None
        self.started_at: float | None = None

    def join(self, url: str) -> dict:
        with self._lock:
            if self.state != "idle":
                return {"error": f"Bot already {self.state}", "state": self.state}
            self.state = "joining"
            self.meeting_url = url
        Thread(target=self._launch, args=(url,), daemon=True).start()
        return {"ok": True, "state": "joining", "meeting_url": url}

    def _launch(self, url: str) -> None:
        try:
            self._start_xvfb()
            self._start_bot(url)
            with self._lock:
                self.state = "in-meeting"
                self.started_at = time.time()
            logger.info("Bot joined: %s", url)
        except Exception as exc:
            logger.error("Launch failed: %s", exc)
            self._cleanup()
            with self._lock:
                self.state, self.meeting_url = "idle", None

    def _start_xvfb(self) -> None:
        try:
            r = subprocess.run(["xdpyinfo", "-display", XVFB_DISPLAY], capture_output=True, timeout=2)
            if r.returncode == 0:
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        self.xvfb_proc = subprocess.Popen(
            ["Xvfb", XVFB_DISPLAY, "-screen", "0", "1920x1080x24"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        logger.info("Xvfb started on %s (pid=%d)", XVFB_DISPLAY, self.xvfb_proc.pid)

    def _start_bot(self, url: str) -> None:
        if not _BOT_SCRIPT.exists():
            raise FileNotFoundError(f"Bot script not found: {_BOT_SCRIPT}")
        env = {**os.environ, "DISPLAY": XVFB_DISPLAY}
        bot_log = open("/tmp/santa_bot.log", "w")
        self.bot_proc = subprocess.Popen(
            [sys.executable, str(_BOT_SCRIPT), url],
            env=env, stdout=bot_log, stderr=subprocess.STDOUT,
        )
        logger.info("Bot started (pid=%d) for %s", self.bot_proc.pid, url)
        Thread(target=self._monitor_bot, daemon=True).start()

    def _monitor_bot(self) -> None:
        if not self.bot_proc:
            return
        self.bot_proc.wait()
        logger.info("Bot exited with code %d", self.bot_proc.returncode)
        with self._lock:
            if self.state != "idle":
                self.state, self.meeting_url, self.started_at = "idle", None, None

    def leave(self) -> dict:
        with self._lock:
            if self.state == "idle":
                return {"ok": True, "state": "idle"}
            prev, self.state = self.state, "idle"
            url, self.meeting_url, self.started_at = self.meeting_url, None, None
        self._cleanup()
        logger.info("Bot left: %s (was %s)", url, prev)
        return {"ok": True, "state": "idle", "previous": prev}

    def _cleanup(self) -> None:
        for attr in ("bot_proc", "xvfb_proc"):
            proc = getattr(self, attr, None)
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGTERM)
                    proc.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
            setattr(self, attr, None)

    def status(self) -> dict:
        with self._lock:
            info: dict = {"state": self.state, "meeting_url": self.meeting_url}
            if self.started_at:
                info["uptime_seconds"] = int(time.time() - self.started_at)
            if self.bot_proc and self.bot_proc.poll() is None:
                info["bot_pid"] = self.bot_proc.pid
            return info


_manager = BotManager()


class BotRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for bot control API."""

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        for k, v in [("Content-Type", "application/json"),
                      ("Content-Length", str(len(body))),
                      ("Access-Control-Allow-Origin", "*")]:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        for k, v in [("Access-Control-Allow-Origin", "*"),
                      ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                      ("Access-Control-Allow-Headers", "Content-Type")]:
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/status":
            self._send_json(_manager.status())
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        if self.path == "/join":
            url = self._read_body().get("url", "")
            if not url:
                self._send_json({"error": "Missing 'url' field"}, 400)
                return
            result = _manager.join(url)
            self._send_json(result, 200 if "ok" in result else 409)
        elif self.path == "/leave":
            self._send_json(_manager.leave())
        else:
            self._send_json({"error": "Not found"}, 404)

    def log_message(self, fmt, *args) -> None:
        logger.info(fmt, *args)


def main() -> None:
    server = HTTPServer((HOST, PORT), BotRequestHandler)
    logger.info("Bot server on http://%s:%d", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _manager.leave()
        server.server_close()


if __name__ == "__main__":
    main()
