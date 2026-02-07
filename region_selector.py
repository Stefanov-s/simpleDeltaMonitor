"""
Fullscreen overlay on X11: user draws a rectangle to select the screen region to monitor.
Returns (left, top, width, height) in screen coordinates for use with mss.
"""
from __future__ import annotations

import tkinter as tk


def select_region() -> tuple[int, int, int, int] | None:
    """
    Block until user draws a rectangle on screen. Returns (left, top, width, height)
    or None if cancelled (e.g. Escape).
    """
    result: list[tuple[int, int, int, int] | None] = [None]
    root = tk.Tk()
    root.configure(bg="gray20")
    # Force full-screen size on X11 (some WMs don't expand -fullscreen with overrideredirect)
    root.withdraw()
    root.update_idletasks()
    w = root.winfo_screenwidth()
    h = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+0+0")
    root.deiconify()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.25)
    except tk.TclError:
        pass
    root.overrideredirect(True)
    root.update_idletasks()
    root.update()
    # Re-apply full size in case WM ignored it
    root.geometry(f"{w}x{h}+0+0")
    root.update_idletasks()
    root.update()

    canvas = tk.Canvas(
        root,
        cursor="cross",
        highlightthickness=0,
        bg="gray20",
    )
    canvas.pack(fill=tk.BOTH, expand=True)

    start_x, start_y = [0], [0]
    rect_id: list[int | None] = [None]

    def on_press(e):
        start_x[0], start_y[0] = e.x, e.y
        if rect_id[0] is not None:
            canvas.delete(rect_id[0])
        rect_id[0] = canvas.create_rectangle(
            e.x, e.y, e.x, e.y, outline="lime", width=2
        )

    def on_drag(e):
        if rect_id[0] is not None:
            canvas.coords(rect_id[0], start_x[0], start_y[0], e.x, e.y)

    def on_release(e):
        x1, y1 = start_x[0], start_y[0]
        x2, y2 = e.x, e.y
        # Use mouse position at release to get true screen offset (winfo_rootx/y can be wrong on X11)
        root.update_idletasks()
        ptr_x = root.winfo_pointerx()
        ptr_y = root.winfo_pointery()
        win_x = ptr_x - e.x
        win_y = ptr_y - e.y
        left = min(x1, x2) + win_x
        top = min(y1, y2) + win_y
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        if width < 5 or height < 5:
            return
        result[0] = (left, top, width, height)
        root.quit()
        root.destroy()

    def cancel(_=None):
        result[0] = None
        root.quit()
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", cancel)

    root.mainloop()
    return result[0]


def select_point() -> tuple[int, int] | None:
    """
    Block until user clicks once on screen. Returns (x, y) in screen coordinates
    or None if cancelled (Escape).
    """
    result: list[tuple[int, int] | None] = [None]
    root = tk.Tk()
    root.configure(bg="gray20")
    root.withdraw()
    root.update_idletasks()
    w = root.winfo_screenwidth()
    h = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+0+0")
    root.deiconify()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.2)
    except tk.TclError:
        pass
    root.overrideredirect(True)
    root.update_idletasks()
    root.update()
    root.geometry(f"{w}x{h}+0+0")
    root.update_idletasks()
    root.update()

    canvas = tk.Canvas(root, cursor="cross", highlightthickness=0, bg="gray20")
    canvas.pack(fill=tk.BOTH, expand=True)

    def on_click(e):
        root.update_idletasks()
        ptr_x = root.winfo_pointerx()
        ptr_y = root.winfo_pointery()
        result[0] = (ptr_x, ptr_y)
        root.quit()
        root.destroy()

    def cancel(_=None):
        result[0] = None
        root.quit()
        root.destroy()

    canvas.bind("<ButtonRelease-1>", on_click)
    root.bind("<Escape>", cancel)
    root.mainloop()
    return result[0]
