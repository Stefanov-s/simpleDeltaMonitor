#!/usr/bin/env python3
"""
DeltaMonitorBot - Ubuntu X11. Select a screen region, read a number at an interval.
Win: trigger when the value *increases* by at least the win threshold (not on decrease).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from queue import Queue, Empty

from region_selector import select_region, select_point
from tracker import start_tracker, start_autoclicker
from reader import test_region
from threading import Event
import os
import sys
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows etc.; no single-instance lock

# Max lines to show in log
LOG_MAX = 100

# Button icons (Unicode; compact)
BTN_SELECT_REGION = "⊞"
BTN_TEST = "✓"
BTN_START = "▶"
BTN_STOP = "■"
BTN_SELECT_CLICK = "•"
BTN_AUTOCLICK = "↻"  # repeat/autoclick (avoid ⏱ - can cause X11 RenderAddGlyphs error on some setups)

# Icon colors (readable, distinct)
COLOR_ICON_SELECT = "#1565c0"   # blue
COLOR_ICON_TEST = "#7b1fa2"     # purple
COLOR_ICON_START = "#2e7d32"    # green
COLOR_ICON_STOP = "#c62828"     # red
COLOR_ICON_CLICK = "#e65100"    # orange
COLOR_ICON_AUTOCLICK = "#00838f"  # teal

# UI colors (colorful but good contrast)
COLOR_BG = "#e8ecf2"
COLOR_CARD = "#ffffff"
COLOR_TEXT = "#1a1d21"
COLOR_ACCENT = "#1565c0"
COLOR_ACCENT_WARM = "#e65100"
COLOR_LOG_BG = "#fafbfc"
COLOR_LOG_FG = "#1a1d21"
COLOR_LOG_SEL_BG = "#1565c0"
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
    # Install icon into ~/.local/share/icons so the menu finds it on any machine
    icon_name = "DeltaMonitorBot"
    icons_dir = os.path.expanduser("~/.local/share/icons")
    icon_line = f"Icon={icon_name}\n"
    if icon_path and os.path.isfile(icon_path):
        try:
            os.makedirs(icons_dir, exist_ok=True)
            dest = os.path.join(icons_dir, f"{icon_name}.png")
            import shutil
            shutil.copy2(icon_path, dest)
        except Exception:
            icon_line = f"Icon={icon_path}\n"  # fallback to full path
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


def _add_tooltip(widget: tk.Widget, text: str) -> None:
    """Show text in a small popup when hovering over widget."""
    tip = [None]
    def on_enter(e):
        tip[0] = tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{e.x_root+10}+{e.y_root+10}")
        tw.attributes("-topmost", True)
        lbl = tk.Label(tw, text=text, bg="#2d2d2d", fg="#eee", padx=6, pady=4, font=("", 9))
        lbl.pack()
    def on_leave(e):
        if tip[0]:
            tip[0].destroy()
            tip[0] = None
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


def _take_single_instance_lock() -> bool:
    """Try to take an exclusive lock so only one app instance runs. Returns True if we got it."""
    if fcntl is None:
        return True
    import tempfile
    lock_path = os.path.join(tempfile.gettempdir(), "deltamonitorbot.lock")
    try:
        f = open(lock_path, "w")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.write(str(os.getpid()))
        f.flush()
        App._lock_file = f  # type: ignore[attr-defined]
        return True
    except (OSError, BlockingIOError):
        try:
            f.close()
        except Exception:
            pass
        return False


class App:
    _lock_file = None

    def __init__(self):
        if not _take_single_instance_lock():
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(
                "Already running",
                "DeltaMonitorBot is already running.\nClose that window first, or run: killall python3",
            )
            root.destroy()
            raise SystemExit(0)
        self.root = tk.Tk()
        self.root.title("DeltaMonitorBot (X11)")
        self.root.minsize(360, 420)
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
        self.autoclicker_coords: tuple[int, int] | None = None
        self._autoclicker_stop_event: Event | None = None
        self.stop_event = Event()
        self.queue: Queue = Queue()
        self._poll_id: str | None = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self.root.update_idletasks()
        w = max(360, self.root.winfo_reqwidth() + 20)
        h = max(420, self.root.winfo_reqheight() + 20)
        self.root.geometry(f"{w}x{h}")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        # --- Settings ---
        settings = ttk.LabelFrame(main, text=" Settings ", padding=8)
        settings.pack(fill=tk.X, pady=(0, 10))

        row = ttk.Frame(settings)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="Check interval (sec):", width=20, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 6))
        self.interval_var = tk.StringVar(value="1")
        self.interval_entry = ttk.Entry(row, textvariable=self.interval_var, width=8)
        self.interval_entry.pack(side=tk.LEFT)
        ttk.Label(row, text="(e.g. 1)").pack(side=tk.LEFT, padx=(6, 0))

        row2 = ttk.Frame(settings)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="Win (trigger if value increases by ≥):", width=28, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 6))
        self.win_var = tk.StringVar(value="2")
        self.win_entry = ttk.Entry(row2, textvariable=self.win_var, width=8)
        self.win_entry.pack(side=tk.LEFT)

        row2b = ttk.Frame(settings)
        row2b.pack(fill=tk.X, pady=3)
        ttk.Label(row2b, text="Min baseline (prev must be ≥):", width=24, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 6))
        self.min_baseline_var = tk.StringVar(value="10")
        self.min_baseline_entry = ttk.Entry(row2b, textvariable=self.min_baseline_var, width=8)
        self.min_baseline_entry.pack(side=tk.LEFT)
        ttk.Label(row2b, text="(avoids false trigger after blips)").pack(side=tk.LEFT, padx=(6, 0))

        row2c = ttk.Frame(settings)
        row2c.pack(fill=tk.X, pady=3)
        ttk.Label(row2c, text="Max delta (increase must be ≤):", width=28, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 6))
        self.max_delta_var = tk.StringVar(value="")
        self.max_delta_entry = ttk.Entry(row2c, textvariable=self.max_delta_var, width=8)
        self.max_delta_entry.pack(side=tk.LEFT)
        ttk.Label(row2c, text="(empty = no limit, ignores OCR spikes)").pack(side=tk.LEFT, padx=(6, 0))

        row3 = ttk.Frame(settings)
        row3.pack(fill=tk.X, pady=6)
        self.region_label = ttk.Label(row3, text="Region: not set", width=20, anchor=tk.W)
        self.region_label.pack(side=tk.LEFT, padx=(0, 8))
        def _icon_btn(parent, icon: str, color: str, cmd, state: str = "normal") -> tk.Button:
            b = tk.Button(parent, text=icon, font=("", 14), fg=color, bg=COLOR_CARD,
                         activeforeground=color, activebackground="#e8eaed",
                         relief=tk.FLAT, borderwidth=1, cursor="hand2",
                         command=cmd, state=state, width=3)
            return b
        self.select_btn = _icon_btn(row3, BTN_SELECT_REGION, COLOR_ICON_SELECT, self._on_select_region)
        self.select_btn.pack(side=tk.LEFT, padx=2)
        _add_tooltip(self.select_btn, "Select region")
        self.test_btn = _icon_btn(row3, BTN_TEST, COLOR_ICON_TEST, self._on_test_region, "disabled")
        self.test_btn.pack(side=tk.LEFT, padx=2)
        _add_tooltip(self.test_btn, "Test region")
        self.start_btn = _icon_btn(row3, BTN_START, COLOR_ICON_START, self._on_start, "disabled")
        self.start_btn.pack(side=tk.LEFT, padx=2)
        _add_tooltip(self.start_btn, "Start")
        self.stop_btn = _icon_btn(row3, BTN_STOP, COLOR_ICON_STOP, self._on_stop, "disabled")
        self.stop_btn.pack(side=tk.LEFT, padx=2)
        _add_tooltip(self.stop_btn, "Stop")

        # --- Autoclicker ---
        autoclicker_frame = ttk.LabelFrame(main, text=" Autoclicker (runs while monitoring) ", padding=8)
        autoclicker_frame.pack(fill=tk.X, pady=(0, 10))
        self.autoclicker_enabled_var = tk.BooleanVar(value=False)
        row_ac = ttk.Frame(autoclicker_frame)
        row_ac.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row_ac, text="Enabled", variable=self.autoclicker_enabled_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(row_ac, text="Position:").pack(side=tk.LEFT, padx=(0, 4))
        self.autoclick_pos_btn = _icon_btn(row_ac, BTN_AUTOCLICK, COLOR_ICON_AUTOCLICK, self._on_select_autoclick_position)
        self.autoclick_pos_btn.pack(side=tk.LEFT, padx=2)
        _add_tooltip(self.autoclick_pos_btn, "Select autoclick position")
        self.autoclick_pos_label = ttk.Label(row_ac, text="not set", width=14, anchor=tk.W)
        self.autoclick_pos_label.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row_ac, text="Interval (sec):").pack(side=tk.LEFT, padx=(0, 4))
        self.autoclick_interval_var = tk.StringVar(value="1")
        ttk.Entry(row_ac, textvariable=self.autoclick_interval_var, width=6).pack(side=tk.LEFT)
        ttk.Label(row_ac, text="(e.g. 1 or 0.5)").pack(side=tk.LEFT, padx=(4, 0))

        # --- On win: action ---
        actions = ttk.LabelFrame(main, text=" On win reached ", padding=8)
        actions.pack(fill=tk.X, pady=(0, 10))

        self.click_action_var = tk.BooleanVar(value=False)
        row_act = ttk.Frame(actions)
        row_act.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(
            row_act,
            text="Click at position (then show alert)",
            variable=self.click_action_var,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.click_pos_btn = _icon_btn(row_act, BTN_SELECT_CLICK, COLOR_ICON_CLICK, self._on_select_click_position)
        self.click_pos_btn.pack(side=tk.LEFT, padx=2)
        _add_tooltip(self.click_pos_btn, "Select click position")
        self.click_pos_label = ttk.Label(row_act, text="Click: not set", width=18, anchor=tk.W)
        self.click_pos_label.pack(side=tk.LEFT, padx=(8, 0))

        # ntfy (custom topic + message)
        row_ntfy = ttk.Frame(actions)
        row_ntfy.pack(fill=tk.X, pady=4)
        ttk.Label(row_ntfy, text="ntfy topic:", width=12, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 4))
        self.ntfy_topic_var = tk.StringVar(value="")
        ttk.Entry(row_ntfy, textvariable=self.ntfy_topic_var, width=18).pack(side=tk.LEFT, padx=2)
        ttk.Label(row_ntfy, text="Custom message:", width=14, anchor=tk.W).pack(side=tk.LEFT, padx=(10, 4))
        self.ntfy_message_var = tk.StringVar(value="Win reached")
        ttk.Entry(row_ntfy, textvariable=self.ntfy_message_var, width=24).pack(side=tk.LEFT, padx=2)

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

    def _on_select_autoclick_position(self):
        self.root.withdraw()
        self.root.update()
        pt = select_point()
        self.root.deiconify()
        if pt is not None:
            self.autoclicker_coords = pt
            self.autoclick_pos_label.config(text=f"({pt[0]}, {pt[1]})")

    def _on_start(self):
        if self.region is None:
            messagebox.showwarning("No region", "Select a region first.")
            return
        try:
            interval = float(self.interval_var.get().strip())
            win = float(self.win_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid input", "Interval and Win must be numbers.")
            return
        if interval <= 0 or interval > 60:
            messagebox.showerror("Invalid input", "Interval must be between 0.01 and 60.")
            return
        if win < 0:
            messagebox.showerror("Invalid input", "Win must be >= 0.")
            return
        try:
            min_baseline = float(self.min_baseline_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid input", "Min baseline must be a number.")
            return
        if min_baseline < 0:
            messagebox.showerror("Invalid input", "Min baseline must be >= 0.")
            return

        max_delta: float | None = None
        max_str = (self.max_delta_var.get() or "").strip()
        if max_str:
            try:
                max_delta = float(max_str)
            except ValueError:
                messagebox.showerror("Invalid input", "Max delta must be a number or left empty.")
                return
            if max_delta < 0:
                messagebox.showerror("Invalid input", "Max delta must be >= 0.")
                return
            if max_delta < win:
                messagebox.showerror("Invalid input", "Max delta must be >= win.")
                return

        click_on_win: tuple[int, int] | None = None
        if self.click_action_var.get() and self.click_on_delta is not None:
            click_on_win = self.click_on_delta
        elif self.click_action_var.get():
            messagebox.showwarning("Click action", "Click on win is enabled but no position set. Select click position or disable the option.")
            return

        autoclicker_interval: float | None = None
        if self.autoclicker_enabled_var.get():
            if self.autoclicker_coords is None:
                messagebox.showwarning("Autoclicker", "Autoclicker is enabled but no position set. Select autoclick position or disable.")
                return
            try:
                autoclicker_interval = float(self.autoclick_interval_var.get().strip())
            except ValueError:
                messagebox.showerror("Invalid input", "Autoclicker interval must be a number (e.g. 1 or 0.5).")
                return
            if autoclicker_interval <= 0 or autoclicker_interval > 300:
                messagebox.showerror("Invalid input", "Autoclicker interval must be between 0.01 and 300 seconds.")
                return

        ntfy_topic = (self.ntfy_topic_var.get() or "").strip() or None
        ntfy_message = (self.ntfy_message_var.get() or "").strip() or "Win reached"

        self.stop_event.clear()
        self._autoclicker_stop_event = Event()
        self.queue = Queue()
        start_tracker(
            self.region, interval, win, self.stop_event, self.queue,
            click_on_win=click_on_win,
            ntfy_topic=ntfy_topic,
            ntfy_message=ntfy_message,
            min_baseline=min_baseline,
            max_delta=max_delta,
            autoclicker_stop_event=self._autoclicker_stop_event,
        )
        if autoclicker_interval is not None and self.autoclicker_coords is not None:
            start_autoclicker(
                self.autoclicker_coords,
                autoclicker_interval,
                self._autoclicker_stop_event,
            )
        self.status_var.set("Monitoring...")
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.select_btn.config(state=tk.DISABLED)
        self.test_btn.config(state=tk.DISABLED)
        self.click_pos_btn.config(state=tk.DISABLED)
        self.autoclick_pos_btn.config(state=tk.DISABLED)
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
        if self._autoclicker_stop_event is not None:
            self._autoclicker_stop_event.set()
        if self._poll_id:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            self.root.quit()
        except Exception:
            pass
        # Force process exit if Tk left something running (e.g. old instances)
        os._exit(0)

    def _on_stop(self):
        self.stop_event.set()
        if self._autoclicker_stop_event is not None:
            self._autoclicker_stop_event.set()
        self._set_stopped("Stopped by user")

    def _set_stopped(self, status: str):
        self.status_var.set(status)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.select_btn.config(state=tk.NORMAL)
        self.test_btn.config(state=tk.NORMAL)
        self.click_pos_btn.config(state=tk.NORMAL)
        self.autoclick_pos_btn.config(state=tk.NORMAL)
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
                    self._set_stopped("Stopped (win)")
                    gain = curr - prev
                    lines = [
                        f"Time: {ts}",
                        f"Win reached: {prev} → {curr} (gain: +{gain})",
                    ]
                    if clicked_at is not None:
                        lines.append(f"Clicked at ({clicked_at[0]}, {clicked_at[1]})")
                    else:
                        if getattr(self, "click_action_var", None) and self.click_action_var.get():
                            lines.append("Click was requested but did not execute.")
                    messagebox.showwarning("Win reached", "\n".join(lines))
                    return
        except Empty:
            pass
        if self.stop_btn["state"] != "disabled":
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
