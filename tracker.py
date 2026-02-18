"""
Background thread: capture region at interval, OCR number, compare with previous.
Triggers only when value *increases* by >= win. Optional click, ntfy, then alert.
"""
from __future__ import annotations

import time
from queue import Queue
from threading import Event, Thread
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from reader import capture_region, image_to_number


def _send_ntfy(topic: str, message: str) -> bool:
    """POST to ntfy.sh topic. Returns True if sent successfully."""
    topic = (topic or "").strip()
    if not topic:
        return False
    url = f"https://ntfy.sh/{topic}"
    try:
        req = Request(url, data=message.encode("utf-8"), method="POST")
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        urlopen(req, timeout=10)
        return True
    except (URLError, OSError):
        return False


def run_autoclicker(
    coords: tuple[int, int],
    interval: float,
    stop_event: Event,
) -> None:
    """Click at coords every interval seconds until stop_event is set."""
    import pyautogui
    cx, cy = coords
    while not stop_event.is_set():
        if stop_event.wait(timeout=interval):
            return
        try:
            pyautogui.click(cx, cy)
        except Exception:
            pass


def start_autoclicker(
    coords: tuple[int, int],
    interval: float,
    stop_event: Event,
) -> Thread:
    """Start autoclicker in daemon thread; returns the thread."""
    t = Thread(
        target=run_autoclicker,
        args=(coords, interval, stop_event),
        daemon=True,
    )
    t.start()
    return t


def run_tracker(
    region: tuple[int, int, int, int],
    interval: float,
    win: float,
    stop_event: Event,
    out_queue: "Queue[Any]",
    click_on_win: tuple[int, int] | None = None,
    ntfy_topic: str | None = None,
    ntfy_message: str = "",
    min_baseline: float = 0,
    max_delta: float | None = None,
    autoclicker_stop_event: Event | None = None,
) -> None:
    """
    Run in a background thread. Every `interval` seconds, capture region,
    OCR number, push (timestamp_str, value) to out_queue. Trigger only when
    prev >= min_baseline and value *increases* by >= win (avoids false trigger
    after OCR blips or tiny baseline). On win: stop autoclicker (if any),
    then optional click, ntfy, alert.
    """
    left, top, width, height = region
    prev: float | None = None

    while not stop_event.is_set():
        t0 = time.monotonic()
        img = capture_region(left, top, width, height)
        value = image_to_number(img)
        ts = time.strftime("%H:%M:%S", time.localtime())

        if value is not None:
            out_queue.put(("reading", ts, value))
            # Trigger only when baseline OK, delta in [win, max_delta]
            delta = value - prev
            if (
                prev is not None
                and prev >= min_baseline
                and delta >= win
                and (max_delta is None or delta <= max_delta)
            ):
                # 1. Stop autoclicker immediately
                if autoclicker_stop_event is not None:
                    autoclicker_stop_event.set()
                # 2. Click on win position (if configured)
                clicked_at: tuple[int, int] | None = None
                if click_on_win:
                    try:
                        import pyautogui
                        cx, cy = click_on_win
                        pyautogui.click(cx, cy)
                        clicked_at = (cx, cy)
                    except Exception:
                        clicked_at = None
                # 3. ntfy notification
                if ntfy_topic and ntfy_topic.strip():
                    msg = (ntfy_message or "Win reached").strip() or "Win reached"
                    body = f"{msg} Delta from {prev} to {value}"
                    _send_ntfy(ntfy_topic.strip(), body)
                # 4. Alert to UI
                out_queue.put(("alert", ts, prev, value, clicked_at))
                return
            prev = value
        else:
            out_queue.put(("reading", ts, None))  # log failed read

        elapsed = time.monotonic() - t0
        sleep_for = max(0.01, interval - elapsed)
        if stop_event.wait(timeout=sleep_for):
            return


def start_tracker(
    region: tuple[int, int, int, int],
    interval: float,
    win: float,
    stop_event: Event,
    out_queue: "Queue[Any]",
    click_on_win: tuple[int, int] | None = None,
    ntfy_topic: str | None = None,
    ntfy_message: str = "",
    min_baseline: float = 0,
    max_delta: float | None = None,
    autoclicker_stop_event: Event | None = None,
) -> Thread:
    """Start the tracker in a daemon thread; returns the thread."""
    t = Thread(
        target=run_tracker,
        args=(region, interval, win, stop_event, out_queue, click_on_win, ntfy_topic, ntfy_message, min_baseline, max_delta, autoclicker_stop_event),
        daemon=True,
    )
    t.start()
    return t
