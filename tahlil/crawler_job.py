"""Start/stop the rival crawl from the web UI, without locking the request."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from django.conf import settings

STATUS_FILE = Path(settings.BASE_DIR) / "data" / "crawl-job.json"
LOG_FILE = Path(settings.BASE_DIR) / "data" / "crawl-job.log"
STOP_FILE = Path(settings.BASE_DIR) / "data" / "crawl-stop.flag"
EVENTS_FILE = Path(settings.BASE_DIR) / "data" / "crawl-events.jsonl"
REPORT_FILE = Path(settings.BASE_DIR) / "data" / "crawl-report.json"

_event_lock = threading.Lock()


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


def stop_requested() -> bool:
    return STOP_FILE.is_file()


def _clear_stop() -> None:
    try:
        STOP_FILE.unlink()
    except FileNotFoundError:
        pass


def _mark_stop() -> None:
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text("1", encoding="utf-8")


def _kill_crawl(pid: int) -> None:
    if pid > 0:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pid, sig)
            except OSError:
                try:
                    os.kill(pid, sig)
                except OSError:
                    pass
            if sig == signal.SIGTERM:
                time.sleep(0.2)
    try:
        subprocess.run(
            ["pkill", "-KILL", "-f", "manage.py crawl_rivals"],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def status() -> dict:
    data = _read()
    pid = int(data.get("pid") or 0)
    alive = _alive(pid)
    stopping = stop_requested()
    running = alive and not stopping
    if stopping and not alive:
        _clear_stop()
        data["running"] = False
        data["ended_at"] = data.get("ended_at") or time.strftime("%Y-%m-%d %H:%M:%S")
        data["last_line"] = "متوقف شد"
        _write(data)
    elif data.get("running") and not alive:
        data["running"] = False
        data["ended_at"] = data.get("ended_at") or time.strftime("%Y-%m-%d %H:%M:%S")
        data["last_line"] = _tail()
        _write(data)
    elif running:
        data["running"] = True
        data["last_line"] = _tail()
    last = "در حال توقف…" if (stopping and alive) else (data.get("last_line") or _tail())
    return {
        "running": running,
        "stopping": bool(stopping and alive),
        "pid": pid if alive else 0,
        "started_at": data.get("started_at") or "",
        "ended_at": "" if running else (data.get("ended_at") or ""),
        "label": data.get("label") or "",
        "last_line": last,
        "events": events_tail(),
        "report": report(),
    }


def events_tail(n: int = 80) -> list[dict]:
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def report() -> dict:
    try:
        data = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _refresh_report() -> None:
    events = events_tail(800)
    hits = [e for e in events if e.get("kind") == "hit"]
    searches = [e for e in events if e.get("kind") == "search"]
    by_shop: dict[str, int] = {}
    for h in hits:
        shop = h.get("shop") or h.get("host") or "?"
        by_shop[shop] = by_shop.get(shop, 0) + 1
    start = next((e for e in events if e.get("kind") == "start"), {})
    payload = {
        "hosts_line": start.get("hosts") or "",
        "searched": len(searches),
        "brought": len(hits),
        "match": sum(1 for h in hits if h.get("verdict") == "match"),
        "uncertain": sum(1 for h in hits if h.get("verdict") == "uncertain"),
        "by_shop": by_shop,
        "hits": hits[-50:],
        "summary": "",
    }
    if hits:
        shops = "، ".join(
            f"{name} ({n})" for name, n in sorted(by_shop.items(), key=lambda x: -x[1])
        )
        payload["summary"] = (
            f"رفتم این‌جاها: {shops}. "
            f"{payload['searched']} کالای خودمان را گشتم و "
            f"{payload['brought']} محصول رقیب آوردم "
            f"({payload['match']} همان کالا، {payload['uncertain']} شبیه)."
        )
    elif searches:
        payload["summary"] = (
            f"{len(searches)} کالای خودمان را در منابع گشتم؛ هنوز ردیفی که از فیلتر عکس/عنوان رد شود نیامد."
        )
    elif start:
        payload["summary"] = f"شروع شد. منابع: {start.get('hosts') or '—'}"
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def emit(kind: str, **fields) -> None:
    row = {"t": time.strftime("%H:%M:%S"), "kind": kind, **fields}
    with _event_lock:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _refresh_report()


def reset_feed() -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text("", encoding="utf-8")
    REPORT_FILE.write_text("{}", encoding="utf-8")


def log_text(n: int = 80) -> str:
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _tail() -> str:
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1][:220] if lines else ""


def start(opts: dict) -> dict:
    current = status()
    if current["running"] or current.get("stopping"):
        return {"ok": False, "error": "کراول همین حالا در حال اجراست.", **current}

    _clear_stop()
    reset_feed()
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
    if opts.get("shops"):
        for host in opts["shops"]:
            cmd += ["--shop", str(host)]
    if opts.get("no_html"):
        cmd.append("--no-html")
    if opts.get("no_market"):
        cmd.append("--no-market")
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
    if opts.get("mode_label"):
        label_bits.append(opts["mode_label"])
    if opts.get("product_id"):
        label_bits.append(f"کالای {opts['product_id']}")
    elif opts.get("family"):
        label_bits.append(opts["family"])
    elif not opts.get("mode_label"):
        label_bits.append("همهٔ کاتالوگ")
    if opts.get("shops"):
        label_bits.append(f"{len(opts['shops'])} منبع")
    elif opts.get("no_html") and opts.get("no_market"):
        label_bits.append("فقط ووکامرس")
    if opts.get("loose"):
        label_bits.append("حساسیت کم")
    else:
        label_bits.append("سخت‌گیرانه")
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
    _mark_stop()
    pid = int(_read().get("pid") or 0)
    _kill_crawl(pid)
    data = _read()
    data["running"] = False
    data["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data["last_line"] = "متوقف شد"
    _write(data)
    _refresh_report()
    return {"ok": True, **status()}
