"""
BoyKisser Desktop
-----------------
Mascota de escritorio con tema pastel blanco-rosado ("boykisser").

Estructura de assets esperada:

    assets/
        main.png            -> imagen estática de repuesto si no hay stand.gif
        click/
            stand.gif       -> animación EN BUCLE mientras no se hace clic
            1.png           -> animación al hacer clic, se reproduce en orden
            2.png              numérico (1, 2, 3, ...) y al acabar vuelve al
            3.png              bucle de stand.gif
        bye/
            *.mp3/.wav/.ogg -> sonido de despedida al cerrar (aleatorio)
    sounds/
        *.mp3/.wav/.ogg -> sonido aleatorio al hacer clic

Si no existe ni assets/click/stand.gif ni assets/main.png, la app NO se
rompe: usa una imagen de repuesto y avisa con una notificación en pantalla.

Cambios respecto a la versión anterior:
- Tema visual único, pastel blanco-rosado, semitransparente (sin modo
  oscuro/deluxe ni selector de color: menos cosas que tocar por error).
- Ventana del bicho con fondo REALMENTE transparente en Windows (solo se
  ve el personaje sobre el escritorio, truco de "color clave"). En otros
  sistemas operativos usa un color pastel de respaldo.
- Estado de reposo animado: assets/click/stand.gif se reproduce en bucle
  cuando no hay clics. Al hacer clic se reproduce assets/click/1.png,
  2.png, 3.png... y al terminar vuelve al bucle.
- El ratón y el teclado cuentan como "clic" de forma INDEPENDIENTE: se
  pueden activar los dos a la vez, solo uno, o ninguno.
- Configuración drásticamente recortada: fuera selector de color, listas
  de imágenes múltiples, volumen aleatorio, sonido fijo, rutas de
  carpetas de sonido editables, hotkeys de texto libre, estilos de
  contador... Solo lo que un usuario normal necesita tocar.
- Sigue arreglado lo de antes: guardado atómico, sin listeners
  duplicados, sin corromper los valores por defecto al restaurar.
"""

import copy
import json
import logging
import logging.handlers
import os
import random
import re
import sys
import threading
import time
import webbrowser
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import pygame
from PIL import Image, ImageDraw, ImageSequence, ImageTk
from pynput import keyboard, mouse

# ---------------------- Constantes de tema (pastel boykisser) ----------------------

PASTEL_BG = "#fff5f8"        # fondo de panel (blanco con tinte rosa)
PASTEL_BG_ALT = "#ffe4ef"    # fondo de listas / zonas secundarias
PASTEL_ACCENT = "#ff8fc0"    # rosa de acento (botones)
PASTEL_ACCENT_DARK = "#ff6fae"  # rosa de acento al pulsar/activo
PASTEL_TEXT = "#6b4356"      # texto principal (ciruela suave, buen contraste)
PASTEL_MUTED = "#b98aa0"     # texto secundario
PANEL_ALPHA = 0.94           # semitransparencia del panel de configuración
MASCOT_FALLBACK_BG = "#ffe9f2"  # color de respaldo si no hay transparencia real
CHROMA_KEY = "#123456"       # color "imposible" usado para el recorte transparente

FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_LABEL = ("Segoe UI", 11)
FONT_LABEL_BOLD = ("Segoe UI", 11, "bold")

OPEN_SETTINGS_HOTKEY = "<ctrl>+<alt>+s"
TOGGLE_MUTE_HOTKEY = "<ctrl>+<alt>+m"

APP_NAME = "BoyKisser Desktop"
CONFIG_FILE = "config.json"
LOG_FILE = "boykisser.log"
SOUND_EXTS = (".mp3", ".wav", ".ogg")
IMAGE_EXTS = (".png", ".gif", ".bmp", ".jpg", ".jpeg")
CLICK_MILESTONES = [10, 100, 500, 1000, 50000, 1000000, 50000000]
LOOP_FRAME_START = 2  # nº de frame (1.png, 2.png...) donde empieza el bucle corto
LOOP_FRAME_END = 5    # nº de frame donde termina el bucle corto
MIN_CLICK_GAP_S = 0.05  # anti-rebote: ignora un segundo registro a <50ms del anterior
REQUIRED_EXTRA_TRIGGERS = 2  # nº de pulsaciones EXTRA necesarias para entrar en bucle

logger = logging.getLogger("boykisser")

# ---------------------- Config por defecto (recortada) ----------------------

DEFAULT_CONFIG = {
    "audio": {
        "muted": False,
        "volume": 0.9,
    },
    "appearance": {
        "size": [200, 200],
        "presets": [[150, 150], [200, 200], [300, 300]],
        "always_on_top": True,
        "transparent_background": True,
        "opacity": 1.0,
        "frame_delay_ms": 90,
        "window_pos": None,
    },
    "behavior": {
        "start_with_windows": False,
        "start_minimized": False,
        "draggable": True,
        "hotkeys_enabled": True,
        "count_mouse": True,
        "count_keyboard": False,
    },
    "advanced": {
        "debug_logging": False,
    },
    "counter": {
        "show_counter": True,
    },
    "click_count": 0,
}

# ---------------------- Utilidades ----------------------


def setup_logging(debug: bool):
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if debug else logging.WARNING)
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=512_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    if debug:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(console)


def deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return deep_merge(DEFAULT_CONFIG, cfg)
        except Exception as e:
            logger.warning("Error leyendo config.json, usando valores por defecto: %s", e)
    return copy.deepcopy(DEFAULT_CONFIG)


_save_lock = threading.Lock()


def save_config(cfg: dict):
    with _save_lock:
        tmp_path = CONFIG_FILE + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, CONFIG_FILE)
        except Exception as e:
            logger.error("Error guardando config: %s", e)


def list_sounds(folder: str) -> list:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(SOUND_EXTS))


def sorted_numeric_frames(folder: str) -> list:
    """Lista assets/click/1.png, 2.png, 10.png... ordenados por número.
    Ignora archivos sin prefijo numérico (por ejemplo stand.gif), que se
    tratan aparte como animación de reposo."""
    if not folder or not os.path.isdir(folder):
        return []
    entries = []
    for f in os.listdir(folder):
        if not f.lower().endswith(IMAGE_EXTS) or f.lower() == "stand.gif":
            continue
        m = re.match(r"(\d+)", os.path.splitext(f)[0])
        if not m:
            continue
        entries.append((int(m.group(1)), f))
    entries.sort(key=lambda t: t[0])
    return [os.path.join(folder, f) for _, f in entries]


def load_gif_frames(path: str):
    """Extrae los frames y duraciones (ms) de un GIF animado."""
    frames, durations = [], []
    try:
        img = Image.open(path)
        for frame in ImageSequence.Iterator(img):
            frames.append(frame.convert("RGBA"))
            durations.append(frame.info.get("duration", 100) or 100)
    except Exception as e:
        logger.warning("No se pudo cargar el GIF %s: %s", path, e)
    return frames, durations


def hex_to_rgba(hex_color: str, alpha: int = 255):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return (r, g, b, alpha)


def make_placeholder_heart(w: int, h: int) -> Image.Image:
    """Corazoncito pastel de repuesto para cuando falta assets/main.png."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = w / 2, h / 2
    r = min(w, h) * 0.28
    draw.ellipse([cx - r * 1.6, cy - r * 1.1, cx, cy + r * 0.6], fill=(255, 143, 192, 255))
    draw.ellipse([cx, cy - r * 1.1, cx + r * 1.6, cy + r * 0.6], fill=(255, 143, 192, 255))
    draw.polygon([(cx - r * 1.6, cy), (cx + r * 1.6, cy), (cx, cy + r * 2.1)], fill=(255, 143, 192, 255))
    return img


# ---------------------- App principal ----------------------


class GlobalInputApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = load_config()
        setup_logging(self.config["advanced"].get("debug_logging", False))

        self.click_count = int(self.config.get("click_count", 0))
        self._stop_event = threading.Event()
        self._mouse_listener = None
        self._kb_listener = None
        self._hotkey_listener = None
        self._click_anim_job = None
        self._click_anim_index = 0
        self._extra_triggers = 0
        self._last_register_ts = 0.0
        self._idle_job = None
        self._idle_index = 0

        self.base_dir = os.path.abspath(os.path.dirname(__file__))
        self.assets_dir = self._ensure_dir("assets")
        self.click_frames_dir = self._ensure_dir("assets/click")
        self.bye_sounds_path = self._ensure_dir("assets/bye")
        self.sounds_path = self._ensure_dir("sounds")

        # ¿Podemos recortar de verdad el fondo de la ventana? (solo Windows)
        self._chroma_enabled = False

        self.root.title(APP_NAME)
        w, h = self.config["appearance"]["size"]
        self.root.geometry(f"{w}x{h}")
        self.root.attributes("-topmost", self.config["appearance"].get("always_on_top", True))
        opacity = self.config["appearance"].get("opacity", 1.0)
        if opacity < 1.0:
            try:
                self.root.attributes("-alpha", float(opacity))
            except Exception:
                pass

        self._apply_transparency_mode()

        pos = self.config["appearance"].get("window_pos")
        if pos:
            try:
                self.root.geometry(f"+{int(pos[0])}+{int(pos[1])}")
            except Exception:
                pass

        self.root.overrideredirect(True)

        pygame.mixer.init()
        self.max_channels = 32
        pygame.mixer.set_num_channels(self.max_channels)
        self._click_sounds = list_sounds(self.sounds_path)
        self._bye_sounds = list_sounds(self.bye_sounds_path)

        self._missing_main_image = False
        self.load_images()

        bg = self._bg_key()
        self.label = tk.Label(root, image=self.img_main, bg=bg, borderwidth=0)
        self.label.pack(expand=True, fill="both")

        if self.config["behavior"].get("draggable", True):
            self.label.bind("<Button-1>", self.start_move)
            self.label.bind("<B1-Motion>", self.do_move)
        self.label.bind("<ButtonRelease-1>", self._on_release)
        self.label.bind("<Button-3>", self.show_context_menu)

        self.menu = tk.Menu(
            self.root, tearoff=0, bg=PASTEL_BG_ALT, fg=PASTEL_TEXT,
            activebackground=PASTEL_ACCENT, activeforeground="#ffffff",
            font=FONT_LABEL_BOLD,
        )
        self.menu.add_command(label="🛠 Abrir configuración...", command=self.open_settings)
        self.menu.add_separator()
        self.menu.add_command(label="❌ Cerrar programa", command=self.on_close)

        self._x = 0
        self._y = 0
        self._dragged = False

        self.counter_label = tk.Label(self.root, text="", bg=PASTEL_BG_ALT, fg=PASTEL_ACCENT_DARK, font=FONT_LABEL_BOLD)
        self.update_counter_label()

        # Arranca el bucle de reposo (stand.gif) si hay frames cargados
        self._show_idle()

        if self.config["behavior"].get("hotkeys_enabled", True):
            self.start_hotkeys_listener()
        if self.config["behavior"].get("count_mouse", True):
            self.start_mouse_listener()
        if self.config["behavior"].get("count_keyboard", False):
            self.start_keyboard_listener()

        if self.config["behavior"].get("start_minimized", False):
            self.root.withdraw()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if self._missing_main_image and not self._idle_frames:
            self.root.after(600, lambda: self.show_toast("Falta assets/click/stand.gif · usando imagen provisional"))

    # ---------------- Utilidades internas ----------------
    def _ensure_dir(self, rel_path: str) -> str:
        path = os.path.join(self.base_dir, rel_path)
        os.makedirs(path, exist_ok=True)
        return path

    def _apply_transparency_mode(self):
        want_transparent = self.config["appearance"].get("transparent_background", True)
        if want_transparent and sys.platform.startswith("win"):
            try:
                self.root.configure(bg=CHROMA_KEY)
                self.root.attributes("-transparentcolor", CHROMA_KEY)
                self._chroma_enabled = True
                return
            except Exception as e:
                logger.warning("No se pudo activar el fondo transparente: %s", e)
        self._chroma_enabled = False
        self.root.configure(bg=MASCOT_FALLBACK_BG)

    def _bg_key(self) -> str:
        return CHROMA_KEY if self._chroma_enabled else MASCOT_FALLBACK_BG

    # ---------------- Imágenes ----------------
    def _flatten(self, img: Image.Image, w: int, h: int) -> ImageTk.PhotoImage:
        img = img.convert("RGBA").resize((w, h))
        bg = Image.new("RGBA", (w, h), hex_to_rgba(self._bg_key()))
        composed = Image.alpha_composite(bg, img).convert("RGB")
        return ImageTk.PhotoImage(composed)

    def load_images(self):
        w, h = self.config["appearance"].get("size", [200, 200])

        # 1) Animación de reposo en bucle: assets/click/stand.gif
        stand_path = os.path.join(self.click_frames_dir, "stand.gif")
        self._idle_frames = []
        self._idle_durations = []
        if os.path.exists(stand_path):
            raw_frames, raw_durations = load_gif_frames(stand_path)
            for f in raw_frames:
                try:
                    self._idle_frames.append(self._flatten(f, w, h))
                except Exception as e:
                    logger.warning("No se pudo procesar un frame de stand.gif: %s", e)
            self._idle_durations = raw_durations

        # 2) Imagen estática de repuesto (solo se usa si no hay stand.gif)
        main_path = os.path.join(self.assets_dir, "main.png")
        try:
            main_img = Image.open(main_path)
            self._missing_main_image = False
        except Exception:
            main_img = make_placeholder_heart(w, h)
            self._missing_main_image = True
        self.img_main = self._flatten(main_img, w, h)

        # 3) Animación de clic: assets/click/1.png, 2.png, 3.png...
        self._click_frame_paths = sorted_numeric_frames(self.click_frames_dir)
        self._click_frames = []
        for p in self._click_frame_paths:
            try:
                self._click_frames.append(self._flatten(Image.open(p), w, h))
            except Exception as e:
                logger.warning("No se pudo cargar el frame de clic %s: %s", p, e)

    def reload_assets(self):
        """Recarga imágenes y sonidos desde disco (por si el usuario los cambió)."""
        self._click_sounds = list_sounds(self.sounds_path)
        self._bye_sounds = list_sounds(self.bye_sounds_path)
        self.load_images()
        self._show_idle()

    # ---------------- Ventana de configuración ----------------
    def open_settings(self):
        if hasattr(self, "settings_win") and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return

        self.settings_win = tk.Toplevel(self.root)
        self.settings_win.title("Configuración — BoyKisser")
        self.settings_win.geometry("640x460")
        self.settings_win.configure(bg=PASTEL_BG)
        try:
            self.settings_win.attributes("-alpha", PANEL_ALPHA)
        except Exception:
            pass

        self._style_pastel()

        left = ttk.Frame(self.settings_win, width=170, style="Boy.TFrame")
        left.pack(side="left", fill="y")
        right = ttk.Frame(self.settings_win, style="Boy.TFrame")
        right.pack(side="right", fill="both", expand=True)

        tk.Label(left, text="💗 BoyKisser", bg=PASTEL_BG, fg=PASTEL_ACCENT_DARK, font=FONT_TITLE).pack(pady=(16, 10), padx=12)

        sections = ["Apariencia", "Audio", "Comportamiento", "Redes sociales", "Avanzado"]
        self.section_list = tk.Listbox(
            left, activestyle="none", bd=0, highlightthickness=0,
            bg=PASTEL_BG_ALT, fg=PASTEL_TEXT, selectbackground=PASTEL_ACCENT,
            selectforeground="#ffffff", font=FONT_LABEL_BOLD,
        )
        for s in sections:
            self.section_list.insert("end", s)
        self.section_list.pack(fill="both", expand=True, padx=10, pady=4)
        self.section_list.bind("<<ListboxSelect>>", lambda e: self._show_section(right))
        self.section_list.selection_set(0)

        self._show_section(right)

    def _style_pastel(self):
        style = ttk.Style(self.settings_win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Boy.TFrame", background=PASTEL_BG)
        style.configure("Boy.TLabel", background=PASTEL_BG, foreground=PASTEL_TEXT, font=FONT_LABEL)
        style.configure("BoyTitle.TLabel", background=PASTEL_BG, foreground=PASTEL_ACCENT_DARK, font=FONT_TITLE)
        style.configure("Boy.TButton", background=PASTEL_ACCENT, foreground="#ffffff", borderwidth=0, relief="flat", font=FONT_LABEL_BOLD, padding=8)
        style.map("Boy.TButton", background=[("active", PASTEL_ACCENT_DARK)])
        style.configure("Boy.TCheckbutton", background=PASTEL_BG, foreground=PASTEL_TEXT, font=FONT_LABEL)
        style.map("Boy.TCheckbutton", background=[("active", PASTEL_BG)])
        style.configure("Boy.Horizontal.TScale", background=PASTEL_BG)

    def _show_section(self, parent):
        for w in parent.winfo_children():
            w.destroy()
        sel = self.section_list.get(self.section_list.curselection())
        {
            "Apariencia": self._appearance_ui,
            "Audio": self._audio_ui,
            "Comportamiento": self._behavior_ui,
            "Redes sociales": self._social_ui,
            "Avanzado": self._advanced_ui,
        }[sel](parent)

    def _section_title(self, parent, text):
        ttk.Label(parent, text=text, style="BoyTitle.TLabel").pack(anchor="nw", padx=18, pady=(16, 6))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=16, pady=(0, 8))

    # ------------------ Apariencia ------------------
    def _appearance_ui(self, frame):
        self._section_title(frame, "Apariencia")
        cfg = self.config["appearance"]

        ttk.Label(frame, text="Tamaño", style="Boy.TLabel").pack(anchor="nw", padx=18, pady=(4, 2))
        sizes_row = ttk.Frame(frame, style="Boy.TFrame")
        sizes_row.pack(anchor="nw", padx=18, pady=2)
        for preset in cfg.get("presets", [[150, 150], [200, 200], [300, 300]]):
            ttk.Button(sizes_row, text=f"{preset[0]}x{preset[1]}", style="Boy.TButton",
                       command=lambda p=preset: self.change_size(p[0], p[1])).pack(side="left", padx=4)

        top_var = tk.BooleanVar(value=cfg.get("always_on_top", True))
        ttk.Checkbutton(frame, text="Mantener siempre encima", variable=top_var, style="Boy.TCheckbutton",
                        command=lambda: (self.root.attributes("-topmost", top_var.get()), self._set_and_save("appearance", "always_on_top", top_var.get()))).pack(anchor="nw", padx=18, pady=8)

        trans_var = tk.BooleanVar(value=cfg.get("transparent_background", True))

        def toggle_transparent():
            self._set_and_save("appearance", "transparent_background", trans_var.get())
            self._apply_transparency_mode()
            self.label.configure(bg=self._bg_key())
            self.reload_assets()

        ttk.Checkbutton(frame, text="Fondo transparente (solo se ve el personaje)", variable=trans_var,
                        style="Boy.TCheckbutton", command=toggle_transparent).pack(anchor="nw", padx=18, pady=4)
        if not sys.platform.startswith("win"):
            ttk.Label(frame, text="⚠ La transparencia total solo funciona en Windows.", style="Boy.TLabel", foreground=PASTEL_MUTED).pack(anchor="nw", padx=18)

        ttk.Label(frame, text="Opacidad de la ventana", style="Boy.TLabel").pack(anchor="nw", padx=18, pady=(12, 2))
        opa_var = tk.DoubleVar(value=cfg.get("opacity", 1.0))

        def on_opa(v):
            try:
                val = float(v)
                self.root.attributes("-alpha", val)
                self._set_and_save("appearance", "opacity", val)
            except Exception:
                pass

        ttk.Scale(frame, from_=0.4, to=1.0, variable=opa_var, style="Boy.Horizontal.TScale", command=on_opa).pack(anchor="nw", padx=18, pady=2, fill="x")

        ttk.Separator(frame, orient="horizontal").pack(fill="x", padx=16, pady=14)
        info = (
            "📁 Reposo en bucle: assets/click/stand.gif\n"
            "📁 Animación de clic: assets/click/1.png, 2.png, 3.png...\n"
            "📁 Sonidos de clic: sounds/     📁 Sonidos al cerrar: assets/bye/\n"
            "(usa PNG con fondo transparente para que no se vea ningún recuadro)"
        )
        ttk.Label(frame, text=info, style="Boy.TLabel", foreground=PASTEL_MUTED, justify="left").pack(anchor="nw", padx=18, pady=4)
        ttk.Button(frame, text="🔄 Recargar imágenes y sonidos", style="Boy.TButton", command=self.reload_assets).pack(anchor="nw", padx=18, pady=(6, 4))

    # ------------------ Audio ------------------
    def _audio_ui(self, frame):
        self._section_title(frame, "Audio")
        cfg = self.config["audio"]

        mute_var = tk.BooleanVar(value=cfg.get("muted", False))
        ttk.Checkbutton(frame, text="Silenciar audio", variable=mute_var, style="Boy.TCheckbutton",
                        command=lambda: self._set_and_save("audio", "muted", mute_var.get())).pack(anchor="nw", padx=18, pady=6)

        ttk.Label(frame, text="Volumen", style="Boy.TLabel").pack(anchor="nw", padx=18, pady=(8, 2))
        vol_var = tk.DoubleVar(value=cfg.get("volume", 0.9))
        ttk.Scale(frame, from_=0.0, to=1.0, variable=vol_var, style="Boy.Horizontal.TScale",
                  command=lambda v: self._set_and_save("audio", "volume", float(v))).pack(anchor="nw", padx=18, pady=2, fill="x")

        ttk.Button(frame, text="🔊 Probar sonido", style="Boy.TButton",
                   command=lambda: threading.Thread(target=self.play_random_sound, daemon=True).start()).pack(anchor="nw", padx=18, pady=14)

    # ------------------ Comportamiento ------------------
    def _behavior_ui(self, frame):
        self._section_title(frame, "Comportamiento")
        cfg = self.config["behavior"]

        ttk.Label(frame, text="¿Qué cuenta como interacción?", style="Boy.TLabel", font=FONT_LABEL_BOLD).pack(anchor="nw", padx=18, pady=(2, 2))

        mouse_var = tk.BooleanVar(value=cfg.get("count_mouse", True))

        def toggle_mouse():
            val = mouse_var.get()
            self._set_and_save("behavior", "count_mouse", val)
            if val:
                self.start_mouse_listener()
            else:
                self.stop_mouse_listener()

        ttk.Checkbutton(frame, text="Contar clics de ratón", variable=mouse_var, style="Boy.TCheckbutton", command=toggle_mouse).pack(anchor="nw", padx=18, pady=4)

        kb_count_var = tk.BooleanVar(value=cfg.get("count_keyboard", False))

        def toggle_kb_count():
            val = kb_count_var.get()
            self._set_and_save("behavior", "count_keyboard", val)
            if val:
                self.start_keyboard_listener()
            else:
                self.stop_keyboard_listener()

        ttk.Checkbutton(frame, text="Contar pulsaciones de teclado", variable=kb_count_var, style="Boy.TCheckbutton", command=toggle_kb_count).pack(anchor="nw", padx=18, pady=4)
        ttk.Label(frame, text="Puedes activar los dos a la vez, solo uno, o ninguno.", style="Boy.TLabel", foreground=PASTEL_MUTED).pack(anchor="nw", padx=18, pady=(0, 8))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", padx=16, pady=6)

        start_var = tk.BooleanVar(value=cfg.get("start_with_windows", False))
        ttk.Checkbutton(frame, text="Iniciar con Windows", variable=start_var, style="Boy.TCheckbutton",
                        command=lambda: (self._toggle_startup(), self._set_and_save("behavior", "start_with_windows", start_var.get()))).pack(anchor="nw", padx=18, pady=6)

        min_var = tk.BooleanVar(value=cfg.get("start_minimized", False))
        ttk.Checkbutton(frame, text="Iniciar minimizado", variable=min_var, style="Boy.TCheckbutton",
                        command=lambda: self._set_and_save("behavior", "start_minimized", min_var.get())).pack(anchor="nw", padx=18, pady=6)

        drag_var = tk.BooleanVar(value=cfg.get("draggable", True))

        def toggle_drag():
            val = drag_var.get()
            if val:
                self.label.bind("<Button-1>", self.start_move)
                self.label.bind("<B1-Motion>", self.do_move)
            else:
                self.label.unbind("<Button-1>")
                self.label.unbind("<B1-Motion>")
            self._set_and_save("behavior", "draggable", val)

        ttk.Checkbutton(frame, text="Permitir arrastrar", variable=drag_var, style="Boy.TCheckbutton", command=toggle_drag).pack(anchor="nw", padx=18, pady=6)

        counter_var = tk.BooleanVar(value=self.config["counter"].get("show_counter", True))
        ttk.Checkbutton(frame, text="Mostrar contador de clics", variable=counter_var, style="Boy.TCheckbutton",
                        command=lambda: (self._set_and_save("counter", "show_counter", counter_var.get()), self.update_counter_label())).pack(anchor="nw", padx=18, pady=6)

        hk_var = tk.BooleanVar(value=cfg.get("hotkeys_enabled", True))

        def toggle_hotkeys():
            val = hk_var.get()
            self._set_and_save("behavior", "hotkeys_enabled", val)
            if val:
                self.start_hotkeys_listener()
            else:
                self.stop_hotkeys_listener()

        ttk.Checkbutton(frame, text="Activar atajos de teclado", variable=hk_var, style="Boy.TCheckbutton", command=toggle_hotkeys).pack(anchor="nw", padx=18, pady=(12, 2))
        ttk.Label(frame, text=f"  {OPEN_SETTINGS_HOTKEY} → abrir configuración   ·   {TOGGLE_MUTE_HOTKEY} → silenciar",
                  style="Boy.TLabel", foreground=PASTEL_MUTED).pack(anchor="nw", padx=18)

    # ------------------ Redes sociales ------------------
    def _social_ui(self, frame):
        self._section_title(frame, "Redes sociales")
        btns = ttk.Frame(frame, style="Boy.TFrame")
        btns.pack(anchor="center", pady=40)
        ttk.Button(btns, text="💬 Discord", style="Boy.TButton",
                   command=lambda: webbrowser.open("https://discord.gg/uxRavuMMdm")).pack(side="left", padx=8, ipadx=14, ipady=6)
        ttk.Button(btns, text="🐙 GitHub", style="Boy.TButton",
                   command=lambda: webbrowser.open("https://github.com/dotva/BoyKisser_DesktopPartner")).pack(side="left", padx=8, ipadx=14, ipady=6)

    # ------------------ Avanzado ------------------
    def _advanced_ui(self, frame):
        self._section_title(frame, "Avanzado")
        cfg = self.config["advanced"]

        dbg_var = tk.BooleanVar(value=cfg.get("debug_logging", False))

        def toggle_debug():
            val = dbg_var.get()
            self._set_and_save("advanced", "debug_logging", val)
            setup_logging(val)

        ttk.Checkbutton(frame, text="Registro de depuración (boykisser.log)", variable=dbg_var, style="Boy.TCheckbutton", command=toggle_debug).pack(anchor="nw", padx=18, pady=6)

        def export_cfg():
            f = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
            if f:
                with open(f, "w", encoding="utf-8") as fh:
                    json.dump(self.config, fh, indent=4, ensure_ascii=False)
                messagebox.showinfo("Exportado", "Configuración exportada")

        def import_cfg():
            f = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
            if f:
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        imported = json.load(fh)
                    self.config = deep_merge(DEFAULT_CONFIG, deep_merge(self.config, imported))
                    save_config(self.config)
                    messagebox.showinfo("Importado", "Configuración importada. Reinicia la app para aplicar todo.")
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo importar: {e}")

        ttk.Button(frame, text="Exportar configuración...", style="Boy.TButton", command=export_cfg).pack(anchor="nw", padx=18, pady=6)
        ttk.Button(frame, text="Importar configuración...", style="Boy.TButton", command=import_cfg).pack(anchor="nw", padx=18, pady=6)

        ttk.Separator(frame, orient="horizontal").pack(fill="x", padx=16, pady=10)

        def reset_clicks():
            if messagebox.askyesno("Confirmar", "¿Reiniciar el contador de clics a 0?"):
                self.click_count = 0
                self.config["click_count"] = 0
                save_config(self.config)
                self.update_counter_label()

        ttk.Button(frame, text="Reiniciar contador de clics", style="Boy.TButton", command=reset_clicks).pack(anchor="nw", padx=18, pady=6)

    # ---------------- Helpers de guardado ----------------
    def _set_and_save(self, section, key, value):
        self.config.setdefault(section, {})
        self.config[section][key] = value
        save_config(self.config)

    # ---------------- Sonido ----------------
    def play_random_sound(self):
        cfg = self.config["audio"]
        if cfg.get("muted", False):
            return
        try:
            if not self._click_sounds:
                self._click_sounds = list_sounds(self.sounds_path)
            if not self._click_sounds:
                logger.debug("No hay sonidos en la carpeta sounds/")
                return
            sound_file = random.choice(self._click_sounds)
            ch = pygame.mixer.find_channel()
            if ch is None:
                pygame.mixer.set_num_channels(min(self.max_channels + 8, 128))
                ch = pygame.mixer.find_channel()
                if ch is None:
                    return
            sound = pygame.mixer.Sound(sound_file)
            sound.set_volume(max(0.0, min(1.0, float(cfg.get("volume", 0.9)))))
            ch.play(sound)
            logger.debug("Reproduciendo: %s", sound_file)
        except Exception as e:
            logger.debug("Error reproduciendo sonido: %s", e)

    # ---------------- Contador y hitos ----------------
    def _register_click(self):
        now = time.monotonic()
        if (now - self._last_register_ts) < MIN_CLICK_GAP_S:
            # Rebote / doble disparo del mismo clic o tecla: se ignora,
            # no cuenta como una segunda pulsación.
            return
        self._last_register_ts = now

        self.click_count += 1
        self.config["click_count"] = self.click_count
        save_config(self.config)
        self.root.after(0, self.update_counter_label)
        self.root.after(0, self._trigger_click_animation)
        threading.Thread(target=self.play_random_sound, daemon=True).start()
        if self.click_count in CLICK_MILESTONES:
            self.root.after(0, self._on_milestone)

    def _on_milestone(self):
        self.show_toast(f"🎉 ¡{self.click_count} clics!")
        threading.Thread(target=self.play_random_sound, daemon=True).start()

    def show_toast(self, text: str):
        try:
            notif = tk.Toplevel(self.root)
            notif.overrideredirect(True)
            notif.attributes("-topmost", True)
            notif.configure(bg=PASTEL_BG_ALT)
            x = self.root.winfo_x() + 10
            y = self.root.winfo_y() + self.root.winfo_height() + 10
            notif.geometry(f"+{x}+{y}")
            tk.Label(notif, text=text, bg=PASTEL_BG_ALT, fg=PASTEL_ACCENT_DARK, font=FONT_LABEL_BOLD, padx=14, pady=8).pack()
            self.root.after(2200, lambda: threading.Thread(target=self._fade_out_notification, args=(notif,), daemon=True).start())
        except Exception as e:
            logger.debug("Error mostrando notificación: %s", e)

    def _fade_out_notification(self, notif):
        try:
            for i in range(10, -1, -1):
                notif.attributes("-alpha", i / 10)
                notif.update()
                time.sleep(0.03)
            notif.destroy()
        except Exception:
            pass

    def update_counter_label(self):
        if not self.config["counter"].get("show_counter", True):
            self.counter_label.place_forget()
            return
        self.counter_label.config(text=f"Clics: {self.click_count}")
        self.counter_label.place(x=8, y=8)

    # ---------------- Animación de reposo (bucle) ----------------
    def _cancel_idle_job(self):
        if self._idle_job:
            try:
                self.root.after_cancel(self._idle_job)
            except Exception:
                pass
            self._idle_job = None

    def _show_idle(self):
        """Estado de reposo: bucle de stand.gif si existe, si no imagen estática."""
        self._cancel_idle_job()
        if self._idle_frames:
            self._idle_index = 0
            self._advance_idle_frame()
        else:
            try:
                self.label.configure(image=self.img_main)
            except Exception:
                pass

    def _advance_idle_frame(self):
        if not self._idle_frames:
            return
        try:
            self.label.configure(image=self._idle_frames[self._idle_index])
        except Exception:
            pass
        duration = self._idle_durations[self._idle_index] if self._idle_index < len(self._idle_durations) else 100
        self._idle_index = (self._idle_index + 1) % len(self._idle_frames)
        self._idle_job = self.root.after(max(20, int(duration)), self._advance_idle_frame)

    # ---------------- Animación de clic ----------------
    def _trigger_click_animation(self):
        """Se llama en cada clic/tecla. Si ya hay una animación en marcha,
        NO la reinicia: solo acumula que ha llegado actividad extra. Hacen
        falta REQUIRED_EXTRA_TRIGGERS disparos extra (no uno solo, que
        podría ser un clic fantasma o un rebote) para entrar en el bucle
        corto entre LOOP_FRAME_START y LOOP_FRAME_END. La animación, una
        vez empieza, siempre llega hasta el final antes de volver al gif
        de reposo."""
        if self._click_anim_job is not None:
            self._extra_triggers += 1
            return
        if not self._click_frames:
            return
        self._cancel_idle_job()
        self._extra_triggers = 0
        self._click_anim_index = 0
        self._advance_click_frame()

    def _advance_click_frame(self):
        frames = self._click_frames
        n = len(frames)
        if n == 0:
            self._click_anim_job = None
            self._show_idle()
            return

        idx = self._click_anim_index
        self.label.configure(image=frames[idx])

        loop_start = min(LOOP_FRAME_START - 1, n - 1)
        loop_end = min(LOOP_FRAME_END - 1, n - 1)
        delay = int(self.config["appearance"].get("frame_delay_ms", 90))

        if idx >= loop_end and self._extra_triggers >= REQUIRED_EXTRA_TRIGGERS:
            # Ha llegado actividad de sobra (varios clics/teclas de verdad,
            # no un disparo fantasma aislado): nos quedamos en el bucle
            # corto en vez de continuar hacia el final.
            self._extra_triggers = 0
            self._click_anim_index = loop_start
            self._click_anim_job = self.root.after(delay, self._advance_click_frame)
            return

        next_idx = idx + 1
        if next_idx >= n:
            # Ya no llega más entrada (o solo un disparo suelto): se
            # completó la animación entera.
            self._click_anim_job = None
            self._extra_triggers = 0
            self._show_idle()
            return

        self._click_anim_index = next_idx
        self._click_anim_job = self.root.after(delay, self._advance_click_frame)

    def change_size(self, w, h):
        self.config["appearance"]["size"] = [w, h]
        save_config(self.config)
        self.root.geometry(f"{w}x{h}")
        self.load_images()
        self.label.configure(bg=self._bg_key())
        self._show_idle()

    # ---------------- Listeners: ratón ----------------
    def start_mouse_listener(self):
        self.stop_mouse_listener()

        def run():
            def on_click(x, y, button, pressed):
                if pressed:
                    self._register_click()

            with mouse.Listener(on_click=on_click) as listener:
                self._mouse_listener = listener
                listener.join()

        threading.Thread(target=run, daemon=True).start()

    def stop_mouse_listener(self):
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    # ---------------- Listeners: teclado (cuenta como clic) ----------------
    def start_keyboard_listener(self):
        self.stop_keyboard_listener()

        def run():
            pressed_keys = set()

            def on_press(key):
                if key not in pressed_keys:
                    pressed_keys.add(key)
                    self._register_click()

            def on_release(key):
                pressed_keys.discard(key)

            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._kb_listener = listener
            listener.run()

        threading.Thread(target=run, daemon=True).start()

    def stop_keyboard_listener(self):
        if self._kb_listener:
            try:
                self._kb_listener.stop()
            except Exception:
                pass
            self._kb_listener = None

    # ---------------- Movimiento de ventana ----------------
    def start_move(self, event):
        if self.config["behavior"].get("draggable", True):
            self._x, self._y = event.x, event.y
            self._dragged = False

    def do_move(self, event):
        if self.config["behavior"].get("draggable", True):
            self._dragged = True
            x = self.root.winfo_pointerx() - self._x
            y = self.root.winfo_pointery() - self._y
            self.root.geometry(f"+{x}+{y}")

    def _on_release(self, _event):
        if self._dragged:
            try:
                self.config["appearance"]["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
                save_config(self.config)
            except Exception:
                pass
        self._dragged = False

    # ---------------- Inicio con Windows ----------------
    def _toggle_startup(self):
        try:
            import win32com.client  # noqa: F401
        except Exception:
            messagebox.showwarning("pywin32 falta", "pywin32 no está instalado. No se puede crear acceso directo.")
            return
        startup = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        shortcut_path = os.path.join(startup, "BoyKisserDesktop.lnk")
        if os.path.exists(shortcut_path):
            try:
                os.remove(shortcut_path)
                messagebox.showinfo("Startup", "Acceso directo eliminado")
            except Exception as e:
                messagebox.showerror("Error", str(e))
        else:
            try:
                shell = win32com.client.Dispatch("WScript.Shell")
                shortcut = shell.CreateShortCut(shortcut_path)
                shortcut.Targetpath = sys.executable
                shortcut.Arguments = f'"{os.path.abspath(__file__)}"'
                shortcut.WorkingDirectory = os.path.dirname(os.path.abspath(__file__))
                shortcut.IconLocation = os.path.abspath(__file__)
                shortcut.save()
                messagebox.showinfo("Startup", "Acceso directo creado")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ---------------- Menú contextual ----------------
    def show_context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ---------------- Cierre ----------------
    def on_close(self):
        try:
            self.config["appearance"]["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        except Exception:
            pass

        if self._bye_sounds:
            try:
                bye_path = random.choice(self._bye_sounds)
                ch = pygame.mixer.find_channel()
                if ch is None:
                    pygame.mixer.set_num_channels(min(self.max_channels + 8, 128))
                    ch = pygame.mixer.find_channel()
                if ch is not None:
                    sound = pygame.mixer.Sound(bye_path)
                    sound.set_volume(1.0)
                    ch.play(sound)
                    time.sleep(min(sound.get_length(), 3))
            except Exception as e:
                logger.debug("Error reproduciendo sonido de despedida: %s", e)

        self.stop_mouse_listener()
        self.stop_keyboard_listener()
        self.stop_hotkeys_listener()
        save_config(self.config)
        self.root.destroy()

    # ---------------- Atajos de teclado ----------------
    def start_hotkeys_listener(self):
        self.stop_hotkeys_listener()

        def hotkey_to_set(hotkey_str):
            keys = set()
            for part in hotkey_str.lower().replace("<", "").replace(">", "").split("+"):
                if part == "ctrl":
                    keys.update([keyboard.Key.ctrl_l, keyboard.Key.ctrl_r])
                elif part == "alt":
                    keys.update([keyboard.Key.alt_l, keyboard.Key.alt_r])
                elif part == "shift":
                    keys.add(keyboard.Key.shift)
                elif len(part) == 1:
                    keys.add(part)
            return keys

        open_keys = hotkey_to_set(OPEN_SETTINGS_HOTKEY)
        mute_keys = hotkey_to_set(TOGGLE_MUTE_HOTKEY)
        pressed = set()

        def key_match(hotkey_keys, pressed_keys):
            for k in hotkey_keys:
                if isinstance(k, keyboard.Key):
                    if k not in pressed_keys:
                        return False
                elif not any(isinstance(pk, keyboard.KeyCode) and pk.char == k for pk in pressed_keys):
                    return False
            return True

        def on_press(key):
            pressed.add(key)
            if key_match(open_keys, pressed):
                self.root.after(0, self.open_settings)
            if key_match(mute_keys, pressed):
                self.config["audio"]["muted"] = not self.config["audio"].get("muted", False)
                save_config(self.config)
                state = "silenciado" if self.config["audio"]["muted"] else "activado"
                self.root.after(0, lambda: self.show_toast(f"Audio {state}"))

        def on_release(key):
            pressed.discard(key)

        def run():
            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._hotkey_listener = listener
            listener.run()

        threading.Thread(target=run, daemon=True).start()

    def stop_hotkeys_listener(self):
        if self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None


if __name__ == "__main__":
    root = tk.Tk()
    app = GlobalInputApp(root)
    root.mainloop()