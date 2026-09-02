"""Start/stop the rival crawl from the web UI, without locking the request."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings

STATUS_FILE = Path(settings.BASE_DIR) / "data" / "crawl-job.json"
LOG_FILE = Path(settings.BASE_DIR) / "data" / "crawl-job.log"


def _read() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write(payload: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def status() -> dict:
    data = _read()
    pid = int(data.get("pid") or 0)
    running = _alive(pid)
    if data.get("running") and not running:
        data["running"] = False
        data["ended_at"] = data.get("ended_at") or time.strftime("%Y-%m-%d %H:%M:%S")
        data["last_line"] = _tail()
        _write(data)
    elif running:
        data["running"] = True
        data["last_line"] = _tail()
    return {
        "running": running,
        "pid": pid if running else 0,
        "started_at": data.get("started_at") or "",
        "ended_at": "" if running else (data.get("ended_at") or ""),
        "label": data.get("label") or "",
        "last_line": data.get("last_line") or _tail(),
    }


def _tail() -> str:
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1][:220] if lines else ""


def start(opts: dict) -> dict:
    current = status()
    if current["running"]:
        return {"ok": False, "error": "کراول همین حالا در حال اجراست.", **current}

    manage = str(Path(settings.BASE_DIR) / "manage.py")
    cmd = [sys.executable, "-u", manage, "crawl_rivals"]
    cmd += ["--workers", str(opts.get("workers") or 2)]
    cmd += ["--pause", str(opts.get("pause") or 0.4)]
    cmd += ["--per-page", str(opts.get("per_page") or 8)]
    if opts.get("limit"):
        cmd += ["--limit", str(opts["limit"])]
    if opts.get("family"):
        cmd += ["--family", opts["family"]]
    if opts.get("product_id"):
        cmd += ["--id", str(int(opts["product_id"]))]
    if opts.get("loose"):
        cmd.append("--loose")
    if opts.get("skip_done"):
        cmd.append("--skip-done")

    log = LOG_FILE.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(settings.BASE_DIR),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    label_bits = []
    if opts.get("product_id"):
        label_bits.append(f"کالای {opts['product_id']}")
    elif opts.get("family"):
        label_bits.append(opts["family"])
    else:
        label_bits.append("همهٔ کاتالوگ")
    if opts.get("loose"):
        label_bits.append("حساسیت کم")
    if opts.get("skip_done"):
        label_bits.append("فقط بدون نتیجه")
    payload = {
        "running": True,
        "pid": proc.pid,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ended_at": "",
        "label": " · ".join(label_bits),
        "last_line": "شروع شد",
        "cmd": cmd[3:],
    }
    _write(payload)
    return {"ok": True, **status()}


def stop() -> dict:
    current = status()
    pid = current.get("pid") or int(_read().get("pid") or 0)
    if not pid or not _alive(pid):
        return {"ok": True, "running": False, "last_line": "کراول در حال اجرا نبود."}
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 6
    while time.time() < deadline and _alive(pid):
        time.sleep(0.2)
    if _alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
    data = _read()
    data["running"] = False
    data["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data["last_line"] = "متوقف شد"
    _write(data)
    return {"ok": True, **status()}
