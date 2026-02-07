#!/usr/bin/env python3
"""
DeltaMonitorBot - Ubuntu X11. Select a screen region, read a number at an interval,
alert when the value changes by at least delta between two checks.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from queue import Queue, Empty

from region_selector import select_region, select_point
from tracker import start_tracker
from reader import test_region
from threading import Event
import os
import sys

# Max lines to show in log
LOG_MAX = 100

# Professional, readable colors (no bright/yellow)
COLOR_BG = "#eef1f5"
COLOR_CARD = "#ffffff"
COLOR_TEXT = "#1a1d21"
COLOR_ACCENT = "#4a6fa5"
COLOR_LOG_BG = "#ffffff"
COLOR_LOG_FG = "#1a1d21"
COLOR_LOG_SEL_BG = "#4a6fa5"
COLOR_LOG_SEL_FG = "#ffffff"


def _ensure_icon(app_dir: str) -> str | None:
    """Create icon.png if missing; return path. Used for window and .desktop."""
    path = os.path.join(app_dir, "icon.png")
    if os.path.isfile(path):
        return path
    try:
        from PIL import Image, ImageDraw
        size = 64
        img = Image.new("RGB", (size, size), color="#3d5a80")
        draw = ImageDraw.Draw(img)
        # White "Δ" (delta) – triangle
        margin = 12
        draw.polygon(
            [(size // 2, margin), (size - margin, size - margin), (margin, size - margin)],
            fill="#e8ecf0", outline="#5a7aa0",
        )
        img.save(path)
        return path
    except Exception:
        return None


def _install_desktop_entry(app_dir: str, icon_path: str | None) -> None:
    """Create or update .desktop file so the app appears in the menu with icon."""
    if sys.platform != "linux":
        return
    exe = sys.executable
    main_py = os.path.join(app_dir, "main.py")
    icon_line = f"Icon={icon_path}\n" if icon_path and os.path.isfile(icon_path) else ""
    content = f"""[Desktop Entry]
Type=Application
Name=DeltaMonitorBot
Comment=Monitor a screen region and alert on number change (X11)
Exec={exe} {main_py}
Path={app_dir}
{icon_line}Terminal=false
Categories=Utility;
"""
    desktop_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(desktop_dir, exist_ok=True)
    desktop_path = os.path.join(desktop_dir, "DeltaMonitorBot.desktop")
    try:
        with open(desktop_path, "w") as f:
            f.write(content)
    except Exception:
        pass


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("DeltaMonitorBot (X11)")
        self.root.minsize(440, 420)
        self.root.geometry("460x500")
        self.root.resizable(True, True)
        self.root.configure(bg=COLOR_BG)

        app_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = _ensure_icon(app_dir)
        if icon_path:
            try:
                abs_icon = os.path.abspath(icon_path)
                self.root.iconphoto(True, tk.PhotoImage(file=abs_icon))
            except Exception:
                pass
            _install_desktop_entry(app_dir, os.path.abspath(icon_path))

        # Professional ttk style
        style = ttk.Style()
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("", 10))
        style.configure("TLabelframe", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("TLabelframe.Label", background=COLOR_CARD, foreground=COLOR_TEXT, font=("", 10, "bold"))
        style.configure("TButton", font=("", 10))
        style.configure("TEntry", fieldbackground=COLOR_CARD, foreground=COLOR_TEXT)
        style.map("TButton", background=[("active", COLOR_ACCENT)])

        self.region: tuple[int, int, int, int] | None = None
        self.click_on_delta: tuple[int, int] | None = None
        self.stop_event = Event()
        self.queue: Queue = Queue()
        self._poll_id: str | None = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        # --- Settings ---
        settings = ttk.LabelFrame(main, text=" Settings ", padding=8)
        settings.pack(fill=tk.X, pady=(0, 10))

        row = ttk.Frame(settings)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="Check interval (sec):", width=20, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 6))
        self.interval_var = tk.StringVar(value="0.5")
        self.interval_entry = ttk.Entry(row, textvariable=self.interval_var, width=8)
        self.interval_entry.pack(side=tk.LEFT)
        ttk.Label(row, text="(e.g. 0.5)").pack(side=tk.LEFT, padx=(6, 0))

        row2 = ttk.Frame(settings)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="Delta (alert if change ≥):", width=20, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 6))
        self.delta_var = tk.StringVar(value="2")
        self.delta_entry = ttk.Entry(row2, textvariable=self.delta_var, width=8)
        self.delta_entry.pack(side=tk.LEFT)

        row3 = ttk.Frame(settings)
        row3.pack(fill=tk.X, pady=6)
        self.region_label = ttk.Label(row3, text="Region: not set", width=20, anchor=tk.W)
        self.region_label.pack(side=tk.LEFT, padx=(0, 8))
        self.select_btn = ttk.Button(row3, text="Select region", command=self._on_select_region)
        self.select_btn.pack(side=tk.LEFT, padx=2)
        self.test_btn = ttk.Button(row3, text="Test region", command=self._on_test_region, state=tk.DISABLED)
        self.test_btn.pack(side=tk.LEFT, padx=2)
        self.start_btn = ttk.Button(row3, text="Start", command=self._on_start, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=2)
        self.stop_btn = ttk.Button(row3, text="Stop", command=self._on_stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        # --- On delta: action ---
        actions = ttk.LabelFrame(main, text=" On delta reached ", padding=8)
        actions.pack(fill=tk.X, pady=(0, 10))

        self.click_action_var = tk.BooleanVar(value=False)
        row_act = ttk.Frame(actions)
        row_act.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(
            row_act,
            text="Click at position (then show alert)",
            variable=self.click_action_var,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.click_pos_btn = ttk.Button(row_act, text="Select click position", command=self._on_select_click_position)
        self.click_pos_btn.pack(side=tk.LEFT, padx=2)
        self.click_pos_label = ttk.Label(row_act, text="Click: not set", width=18, anchor=tk.W)
        self.click_pos_label.pack(side=tk.LEFT, padx=(8, 0))

        # --- Status ---
        self.status_var = tk.StringVar(value="Idle")
        status_row = ttk.Frame(main)
        status_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(status_row, text="Status:", width=8, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.status_var, font=("", 10, "bold")).pack(side=tk.LEFT)

        # --- Recent readings ---
        log_section = ttk.LabelFrame(main, text=" Recent readings ", padding=6)
        log_section.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        log_frame = ttk.Frame(log_section)
        log_frame.pack(fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame)
        self.log_listbox = tk.Listbox(
            log_frame,
            height=20,
            font=("Consolas", 10),
            yscrollcommand=scroll.set,
            relief=tk.FLAT,
            highlightthickness=0,
            borderwidth=1,
            bg=COLOR_LOG_BG,
            fg=COLOR_LOG_FG,
            selectbackground=COLOR_LOG_SEL_BG,
            selectforeground=COLOR_LOG_SEL_FG,
        )
        scroll.config(command=self.log_listbox.yview)
        self.log_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_select_region(self):
        self.root.withdraw()
        self.root.update()
        reg = select_region()
        self.root.deiconify()
        if reg is not None:
            self.region = reg
            self.region_label.config(text=f"Region: ({reg[0]},{reg[1]}) {reg[2]}×{reg[3]}")
            self.start_btn.config(state=tk.NORMAL)
            self.test_btn.config(state=tk.NORMAL)

    def _on_select_click_position(self):
        self.root.withdraw()
        self.root.update()
        pt = select_point()
        self.root.deiconify()
        if pt is not None:
            self.click_on_delta = pt
            self.click_pos_label.config(text=f"Click: ({pt[0]}, {pt[1]})")

    def _on_start(self):
        if self.region is None:
            messagebox.showwarning("No region", "Select a region first.")
            return
        try:
            interval = float(self.interval_var.get().strip())
            delta = float(self.delta_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid input", "Interval and Delta must be numbers.")
            return
        if interval <= 0 or interval > 60:
            messagebox.showerror("Invalid input", "Interval must be between 0.01 and 60.")
            return
        if delta < 0:
            messagebox.showerror("Invalid input", "Delta must be >= 0.")
            return

        click_on_delta: tuple[int, int] | None = None
        if self.click_action_var.get() and self.click_on_delta is not None:
            click_on_delta = self.click_on_delta
        elif self.click_action_var.get():
            messagebox.showwarning("Click action", "Click on delta is enabled but no position set. Select click position or disable the option.")
            return

        self.stop_event.clear()
        self.queue = Queue()
        start_tracker(self.region, interval, delta, self.stop_event, self.queue, click_on_delta)
        self.status_var.set("Monitoring...")
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.select_btn.config(state=tk.DISABLED)
        self.test_btn.config(state=tk.DISABLED)
        self.click_pos_btn.config(state=tk.DISABLED)
        self._poll_queue()

    def _on_test_region(self):
        if self.region is None:
            return
        base = os.path.dirname(os.path.abspath(__file__))
        save_path = os.path.join(base, "debug_capture.png")
        pre_path = os.path.join(base, "debug_preprocessed.png")
        raw_text, num, path = test_region(self.region, save_path, pre_path)
        win = tk.Toplevel(self.root)
        win.title("Test region – debug")
        win.geometry("500x300")
        r = self.region
        ttk.Label(win, text=f"Region sent to mss: left={r[0]} top={r[1]} width={r[2]} height={r[3]}", font=("", 9)).pack(anchor=tk.W, padx=8, pady=2)
        ttk.Label(win, text=f"Raw capture: {path}", font=("", 9)).pack(anchor=tk.W, padx=8, pady=2)
        ttk.Label(win, text=f"Preprocessed (sent to Tesseract): {pre_path}", font=("", 9)).pack(anchor=tk.W, padx=8, pady=2)
        ttk.Label(win, text=f"Extracted number: {num}", font=("", 9)).pack(anchor=tk.W, padx=8, pady=2)
        ttk.Label(win, text="Raw OCR text (Tesseract):").pack(anchor=tk.W, padx=8, pady=(8, 0))
        txt = tk.Text(win, height=8, wrap=tk.WORD, font=("Consolas", 9))
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        txt.insert(tk.END, raw_text)
        txt.config(state=tk.DISABLED)

    def _on_close(self):
        """Handle window close (X button): stop tracking and quit."""
        self.stop_event.set()
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        self.root.quit()
        self.root.destroy()

    def _on_stop(self):
        self.stop_event.set()
        self._set_stopped("Stopped by user")

    def _set_stopped(self, status: str):
        self.status_var.set(status)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.select_btn.config(state=tk.NORMAL)
        self.test_btn.config(state=tk.NORMAL)
        self.click_pos_btn.config(state=tk.NORMAL)
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "reading":
                    _, ts, value = item
                    line = f"{ts}  {value if value is not None else '(no number)'}"
                    self.log_listbox.insert(tk.END, line)
                    n = self.log_listbox.size()
                    if n > LOG_MAX:
                        self.log_listbox.delete(0, n - LOG_MAX - 1)
                    self.log_listbox.see(tk.END)
                elif item[0] == "alert":
                    _, ts, prev, curr, clicked_at = item
                    self._set_stopped("Stopped (delta alert)")
                    change = curr - prev
                    change_str = f"+{change}" if change >= 0 else str(change)
                    lines = [
                        f"Time: {ts}",
                        f"Delta reached: previous {prev} → current {curr} (change: {change_str})",
                    ]
                    if clicked_at is not None:
                        lines.append(f"Clicked at ({clicked_at[0]}, {clicked_at[1]})")
                    else:
                        if getattr(self, "click_action_var", None) and self.click_action_var.get():
                            lines.append("Click was requested but did not execute.")
                    messagebox.showwarning("Delta alert", "\n".join(lines))
                    return
        except Empty:
            pass
        if self.stop_btn.state() != (tk.DISABLED,):
            self._poll_id = self.root.after(100, self._poll_queue)

    def run(self):
        self.root.mainloop()


def _check_tesseract() -> bool:
    """Verify Tesseract is available (not a venv PATH issue). Return True if OK."""
    import sys
    try:
        import pytesseract
        # On Linux, venv often has minimal PATH; point to system tesseract explicitly
        if sys.platform == "linux":
            pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
        pytesseract.get_tesseract_version()
        return True
    except Exception as e:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Tesseract not found",
            f"Tesseract OCR is not available.\n\n"
            f"Install: sudo apt install tesseract-ocr\n\n"
            f"Error: {e}\n\n"
            f"(Running in a venv does not change this; Tesseract is a system program.)"
        )
        root.destroy()
        return False


if __name__ == "__main__":
    if not _check_tesseract():
        raise SystemExit(1)
    App().run()
