#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FREEZER v1.0
Process freeze tool for Windows.
Deps: psutil, pynput  →  pip install psutil pynput
"""

import sys, os, subprocess

# ── Auto-install deps ────────────────────────────────────────────────────────
def _ensure(pkg, import_as=None):
    import_as = import_as or pkg
    try:
        __import__(import_as)
    except ImportError:
        print(f"[FREEZER] Installing {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

_ensure("psutil")
_ensure("pynput")

# ── Imports ──────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import font as tkfont
import ctypes, ctypes.wintypes
import json, threading, time
import psutil
from pynput import keyboard as pynkb, mouse as pynms

# ── Windows API ──────────────────────────────────────────────────────────────
ntdll    = ctypes.WinDLL("ntdll")
kernel32 = ctypes.windll.kernel32

def _open_proc(pid: int):
    return kernel32.OpenProcess(0x1F0FFF, False, pid)

def suspend_process(pid: int):
    h = _open_proc(pid)
    if h:
        ntdll.NtSuspendProcess(h)
        kernel32.CloseHandle(h)

def resume_process(pid: int):
    h = _open_proc(pid)
    if h:
        ntdll.NtResumeProcess(h)
        kernel32.CloseHandle(h)

def find_pid(name: str):
    n = name.lower()
    if not n.endswith(".exe"):
        n += ".exe"
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == n:
                return p.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None

# ── Settings ─────────────────────────────────────────────────────────────────
_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freezer.json")
_DEFAULTS = {"process": "", "duration_ms": 500, "hotkey": None}

def load_cfg() -> dict:
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                d = _DEFAULTS.copy(); d.update(json.load(f)); return d
        except Exception:
            pass
    return _DEFAULTS.copy()

def save_cfg(cfg: dict):
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ── Palette ──────────────────────────────────────────────────────────────────
C = {
    "bg":       "#080C18",
    "surface":  "#0E1525",
    "raised":   "#141E33",
    "border":   "#1E2D4A",
    "accent":   "#3B82F6",
    "accent_h": "#60A5FA",
    "ice":      "#BAE6FD",
    "text":     "#E2E8F0",
    "muted":    "#64748B",
    "green":    "#4ADE80",
    "red":      "#F87171",
    "orange":   "#FB923C",
}

# ── App ──────────────────────────────────────────────────────────────────────
class FreezerApp:
    def __init__(self, root: tk.Tk):
        self.root   = root
        self.cfg    = load_cfg()
        self.frozen = False
        self.binding = False
        self._lock  = threading.Lock()
        self._kb    = None
        self._ms    = None

        self._build()
        self._apply_cfg()
        self._start_listeners()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Build UI ─────────────────────────────────────────────────────────────
    def _build(self):
        r = self.root
        r.title("FREEZER")
        r.configure(bg=C["bg"])
        r.resizable(False, False)
        W, H = 440, 370
        sx, sy = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry(f"{W}x{H}+{(sx-W)//2}+{(sy-H)//2}")

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(r, bg=C["surface"], height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="❄", font=("Segoe UI", 26),
                 bg=C["surface"], fg=C["ice"]).pack(side="left", padx=(16,6))

        ttl_f = tk.Frame(hdr, bg=C["surface"])
        ttl_f.pack(side="left", fill="y", pady=10)
        tk.Label(ttl_f, text="FREEZER", font=("Consolas", 17, "bold"),
                 bg=C["surface"], fg=C["text"]).pack(anchor="w")
        tk.Label(ttl_f, text="process suspension tool", font=("Segoe UI", 8),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w")

        # Status pill
        self._status_var = tk.StringVar(value="● READY")
        self._status_fg  = C["green"]
        self._status_lbl = tk.Label(hdr, textvariable=self._status_var,
                                    font=("Segoe UI", 9, "bold"),
                                    bg=C["raised"], fg=C["green"],
                                    padx=10, pady=4)
        self._status_lbl.pack(side="right", padx=14, pady=16)
        _round_corners(self._status_lbl)

        # ── Divider ──────────────────────────────────────────────────────────
        tk.Frame(r, bg=C["border"], height=1).pack(fill="x")

        # ── Body ─────────────────────────────────────────────────────────────
        body = tk.Frame(r, bg=C["bg"], padx=22, pady=18)
        body.pack(fill="both", expand=True)

        # Process name
        _label(body, "ИМЯ ПРОЦЕССА")
        self._proc_var = tk.StringVar()
        self._proc_e   = _entry(body, self._proc_var, "notepad.exe")
        self._proc_e.pack(fill="x", pady=(4,14))

        # Duration
        _label(body, "ДЛИТЕЛЬНОСТЬ  (МС)")
        self._dur_var = tk.StringVar(value="500")
        dur_row = tk.Frame(body, bg=C["bg"])
        dur_row.pack(fill="x", pady=(4,14))

        self._dur_e = _entry(dur_row, self._dur_var, "500")
        self._dur_e.pack(side="left", fill="x", expand=True)

        # Quick presets
        for ms in (100, 250, 500, 1000):
            ms_val = ms
            b = tk.Button(dur_row, text=f"{ms}", font=("Segoe UI", 8),
                          bg=C["raised"], fg=C["muted"], relief="flat", bd=0,
                          padx=7, pady=4, cursor="hand2",
                          activebackground=C["border"], activeforeground=C["text"],
                          command=lambda v=ms_val: self._dur_var.set(str(v)))
            b.pack(side="left", padx=(4,0))

        # Hotkey row
        _label(body, "ХОТКЕЙ (КЛАВИША / КНОПКА МЫШИ)")
        hk_row = tk.Frame(body, bg=C["bg"])
        hk_row.pack(fill="x", pady=(4,0))

        hk_box = tk.Frame(hk_row, bg=C["raised"],
                          highlightbackground=C["border"], highlightthickness=1)
        hk_box.pack(side="left", fill="x", expand=True)
        self._hk_var = tk.StringVar(value="—")
        self._hk_lbl = tk.Label(hk_box, textvariable=self._hk_var,
                                 bg=C["raised"], fg=C["muted"],
                                 font=("Consolas", 11), anchor="w")
        self._hk_lbl.pack(fill="x", padx=12, pady=8)

        self._bind_btn = tk.Button(hk_row, text="НАЗНАЧИТЬ",
                                    font=("Segoe UI", 8, "bold"),
                                    bg=C["accent"], fg=C["text"],
                                    relief="flat", bd=0, padx=12, pady=6,
                                    cursor="hand2",
                                    activebackground=C["accent_h"],
                                    activeforeground=C["text"],
                                    command=self._start_bind)
        self._bind_btn.pack(side="left", padx=(6,0))

        clr_btn = tk.Button(hk_row, text="✕",
                             font=("Segoe UI", 9),
                             bg=C["raised"], fg=C["muted"],
                             relief="flat", bd=0, padx=9, pady=6,
                             cursor="hand2",
                             activebackground=C["red"],
                             activeforeground=C["text"],
                             command=self._clear_hk)
        clr_btn.pack(side="left", padx=(3,0))

        # ── Bottom bar ───────────────────────────────────────────────────────
        tk.Frame(r, bg=C["border"], height=1).pack(fill="x")
        bar = tk.Frame(r, bg=C["surface"], padx=22, pady=12)
        bar.pack(fill="x")

        save_btn = tk.Button(bar, text="💾  СОХРАНИТЬ",
                              font=("Segoe UI", 9),
                              bg=C["raised"], fg=C["muted"],
                              relief="flat", bd=0, padx=12, pady=6,
                              cursor="hand2",
                              activebackground=C["border"],
                              activeforeground=C["text"],
                              command=self._save)
        save_btn.pack(side="left")

        self._freeze_btn = tk.Button(bar, text="❄  ЗАМОРОЗИТЬ",
                                      font=("Segoe UI", 10, "bold"),
                                      bg=C["accent"], fg=C["text"],
                                      relief="flat", bd=0, padx=20, pady=6,
                                      cursor="hand2",
                                      activebackground=C["accent_h"],
                                      activeforeground=C["text"],
                                      command=self._manual_freeze)
        self._freeze_btn.pack(side="right")

        # Version tag
        tk.Label(bar, text="v1.0", font=("Segoe UI", 8),
                 bg=C["surface"], fg=C["muted"]).pack(side="right", padx=8)

    # ── Config helpers ────────────────────────────────────────────────────────
    def _apply_cfg(self):
        self._proc_var.set(self.cfg.get("process", ""))
        self._dur_var.set(str(self.cfg.get("duration_ms", 500)))
        hk = self.cfg.get("hotkey")
        if hk:
            self._hk_var.set(hk)
            self._hk_lbl.config(fg=C["ice"])
        else:
            self._hk_var.set("—")

    def _save(self):
        self.cfg["process"]     = self._proc_var.get().strip()
        try: self.cfg["duration_ms"] = max(1, int(self._dur_var.get()))
        except ValueError: self.cfg["duration_ms"] = 500
        save_cfg(self.cfg)
        self._set_status("✓ СОХРАНЕНО", C["green"], 1400)

    # ── Status helper ─────────────────────────────────────────────────────────
    def _set_status(self, text, color, reset_ms=0):
        self._status_var.set(text)
        self._status_lbl.config(fg=color)
        if reset_ms:
            self.root.after(reset_ms, lambda: (
                self._status_var.set("● READY"),
                self._status_lbl.config(fg=C["green"])
            ))

    # ── Freeze logic ──────────────────────────────────────────────────────────
    def _manual_freeze(self):
        self._do_freeze()

    def _do_freeze(self):
        if self.frozen or self.binding:
            return
        proc = self._proc_var.get().strip()
        if not proc:
            self._set_status("✗ ЗАДАЙ ПРОЦЕСС", C["red"], 1600)
            return
        try:
            ms = max(1, int(self._dur_var.get()))
        except ValueError:
            ms = 500
        pid = find_pid(proc)
        if not pid:
            self._set_status(f"✗ НЕ НАЙДЕН: {proc[:20]}", C["red"], 2000)
            return
        threading.Thread(target=self._freeze_thread, args=(pid, ms), daemon=True).start()

    def _freeze_thread(self, pid: int, ms: int):
        if not self._lock.acquire(blocking=False):
            return
        try:
            self.frozen = True
            self.root.after(0, lambda: self._set_status("❄  ЗАМОРОЖЕН", C["ice"]))
            self.root.after(0, lambda: self._freeze_btn.config(
                bg=C["raised"], text="❄  ЗАМОРОЖЕН"))

            suspend_process(pid)
            time.sleep(ms / 1000.0)
            resume_process(pid)

        except Exception:
            self.root.after(0, lambda: self._set_status("✗ ОШИБКА (ПРАВА?)", C["red"], 2500))
        finally:
            self.frozen = False
            self.root.after(0, lambda: self._set_status("● READY", C["green"]))
            self.root.after(0, lambda: self._freeze_btn.config(
                bg=C["accent"], text="❄  ЗАМОРОЗИТЬ"))
            self._lock.release()

    # ── Hotkey binding ────────────────────────────────────────────────────────
    def _start_bind(self):
        self.binding = True
        self._bind_btn.config(text="НАЖМИ...", bg=C["orange"])
        self._hk_var.set("Ждём нажатия...")
        self._hk_lbl.config(fg=C["orange"])

    def _finish_bind(self, key_name: str):
        self.binding = False
        self.cfg["hotkey"] = key_name
        self._hk_var.set(key_name)
        self._hk_lbl.config(fg=C["ice"])
        self.root.after(0, lambda: self._bind_btn.config(
            text="НАЗНАЧИТЬ", bg=C["accent"]))

    def _clear_hk(self):
        self.binding = False
        self.cfg["hotkey"] = None
        self._hk_var.set("—")
        self._hk_lbl.config(fg=C["muted"])
        self._bind_btn.config(text="НАЗНАЧИТЬ", bg=C["accent"])

    # ── Listeners ─────────────────────────────────────────────────────────────
    def _start_listeners(self):
        self._kb = pynkb.Listener(on_press=self._on_key)
        self._kb.daemon = True
        self._kb.start()

        self._ms = pynms.Listener(on_click=self._on_click)
        self._ms.daemon = True
        self._ms.start()

    def _on_key(self, key):
        try:
            name = key.name.upper() if hasattr(key, "name") and key.name else None
            if name is None:
                name = str(key).strip("'").upper()
        except Exception:
            return

        if self.binding:
            if name in ("ESC", "ESCAPE"):
                self.binding = False
                hk = self.cfg.get("hotkey")
                self.root.after(0, lambda: (
                    self._bind_btn.config(text="НАЗНАЧИТЬ", bg=C["accent"]),
                    self._hk_var.set(hk if hk else "—"),
                    self._hk_lbl.config(fg=C["ice"] if hk else C["muted"])
                ))
                return
            self.root.after(0, lambda n=name: self._finish_bind(n))
            return

        hk = self.cfg.get("hotkey")
        if hk and name == hk.upper() and not self.frozen:
            self._do_freeze()

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        if button == pynms.Button.x1:
            bname = "MOUSE4"
        elif button == pynms.Button.x2:
            bname = "MOUSE5"
        else:
            return

        if self.binding:
            self.root.after(0, lambda n=bname: self._finish_bind(n))
            return

        hk = self.cfg.get("hotkey")
        if hk and bname == hk.upper() and not self.frozen:
            self._do_freeze()

    def _on_close(self):
        self._save()
        if self._kb:  self._kb.stop()
        if self._ms:  self._ms.stop()
        self.root.destroy()


# ── Widget helpers ────────────────────────────────────────────────────────────
def _label(parent, text: str):
    tk.Label(parent, text=text, font=("Segoe UI", 7, "bold"),
             bg=C["bg"], fg=C["muted"]).pack(anchor="w")

def _entry(parent, var: tk.StringVar, placeholder: str = ""):
    frame = tk.Frame(parent, bg=C["raised"],
                     highlightbackground=C["border"], highlightthickness=1)
    e = tk.Entry(frame, textvariable=var, bg=C["raised"], fg=C["text"],
                 insertbackground=C["accent"], font=("Consolas", 11),
                 relief="flat", bd=0)
    e.pack(fill="x", padx=12, pady=8)

    # Placeholder
    if placeholder and not var.get():
        e.config(fg=C["muted"])
        e.insert(0, placeholder)

        def on_focus_in(_):
            if e.get() == placeholder:
                e.delete(0, "end")
                e.config(fg=C["text"])

        def on_focus_out(_):
            if not e.get():
                e.insert(0, placeholder)
                e.config(fg=C["muted"])

        e.bind("<FocusIn>",  on_focus_in)
        e.bind("<FocusOut>", on_focus_out)

    return frame

def _round_corners(widget):
    """Not real rounding in tkinter, but sets the relief."""
    widget.config(relief="flat")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform != "win32":
        print("FREEZER работает только на Windows!")
        sys.exit(1)

    root = tk.Tk()

    # Remove default title bar for clean look, but keep it for simplicity
    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    app = FreezerApp(root)
    root.mainloop()
