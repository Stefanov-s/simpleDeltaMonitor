"""
Background thread: capture region at interval, OCR number, compare with previous.
Puts log entries and optional alert on a queue for the UI thread.
"""
from __future__ import annotations

import time
from queue import Queue
from threading import Event, Thread
from typing import Any

from reader import capture_region, image_to_number


def run_tracker(
    region: tuple[int, int, int, int],
    interval: float,
    delta: float,
    stop_event: Event,
    out_queue: "Queue[Any]",
    click_on_delta: tuple[int, int] | None = None,
) -> None:
    """
    Run in a background thread. Every `interval` seconds, capture region,
    OCR number, push (timestamp_str, value) to out_queue. If value changed
    by >= delta: optionally click at click_on_delta (and wait for success),
    then push ("alert", ts, prev, curr, clicked_at) and return.
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
            if prev is not None and abs(value - prev) >= delta:
                clicked_at: tuple[int, int] | None = None
                if click_on_delta:
                    try:
                        import pyautogui
                        cx, cy = click_on_delta
                        pyautogui.click(cx, cy)
                        clicked_at = (cx, cy)
                    except Exception:
                        clicked_at = None
                out_queue.put(("alert", ts, prev, value, clicked_at))
                return
            prev = value
        else:
            out_queue.put(("reading", ts, None))  # log failed read

        # Sleep for the rest of the interval
        elapsed = time.monotonic() - t0
        sleep_for = max(0.01, interval - elapsed)
        if stop_event.wait(timeout=sleep_for):
            return


def start_tracker(
    region: tuple[int, int, int, int],
    interval: float,
    delta: float,
    stop_event: Event,
    out_queue: "Queue[Any]",
    click_on_delta: tuple[int, int] | None = None,
) -> Thread:
    """Start the tracker in a daemon thread; returns the thread."""
    t = Thread(
        target=run_tracker,
        args=(region, interval, delta, stop_event, out_queue, click_on_delta),
        daemon=True,
    )
    t.start()
    return t
