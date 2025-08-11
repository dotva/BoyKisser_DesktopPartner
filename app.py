import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
from pynput import keyboard, mouse
import os
import threading
import sys
import random
import pygame
import json
import time

# ---------------------- Config defaults ----------------------
DEFAULT_CONFIG = {
    "audio": {
        "muted": False,
        "allow_overlap": True,
        "fixed_sound": False,
        "fixed_file": "",
        "volume": 0.9,
        "random_volume": False,
        "random_volume_min": 0.6,
        "random_volume_max": 1.0
    },
    "appearance": {
        "size": [400, 400],
        "presets": [[200,200],[400,400],[600,600]],
        "always_on_top": True,
        "show_title_bar": False,
        "opacity": 1.0,
        "main_image": "assets/main.png",
        "hover_image": "assets/hover.png",
        "dark_mode": False,
        "deluxe_mode": False  # <--- NUEVO
    },
    "behavior": {
        "start_with_windows": False,
        "start_minimized": False,
        "draggable": True
    },
    "hotkeys": {
        "enabled": True,
        "open_settings": "<ctrl>+<alt>+s",
        "toggle_mute": "<ctrl>+<alt>+m"
    },
    "advanced": {
        "debug_logging": False
    }
}

CONFIG_FILE = "config.json"

# ---------------------- Helper funcs ----------------------

def resource_path(rel):
    # In case of PyInstaller later
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base, rel)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # merge with defaults to avoid missing keys
            merged = DEFAULT_CONFIG.copy()
            for k, v in cfg.items():
                if isinstance(v, dict) and k in merged:
                    merged[k].update(v)
                else:
                    merged[k] = v
            return merged
        except Exception as e:
            print("Error leyendo config.json, usando valores por defecto:", e)
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("Error guardando config:", e)

# ---------------------- Main app ----------------------

class GlobalInputApp:
    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.click_count = self.config.get("click_count", 0)  # Carga el valor guardado
        self.click_milestones = [10, 100, 500, 1000, 50000, 1000000, 50000000]

        # ----------- NUEVO: Estilos modernos y modo oscuro/claro -----------
        self.style = ttk.Style()
        self.theme = "dark" if self.config["appearance"].get("dark_mode", False) else "light"
        if self.theme == "dark":
            self.root.configure(bg="#222")
            self.style.configure("TFrame", background="#222")
            self.style.configure("TLabel", background="#222", foreground="#eee")
            self.style.configure("TButton", background="#333", foreground="#eee", borderwidth=0, relief="flat")
            self.style.map("TButton", background=[("active", "#444")])
        else:
            self.root.configure(bg="#f7f7f7")
            self.style.configure("TFrame", background="#f7f7f7")
            self.style.configure("TLabel", background="#f7f7f7", foreground="#222")
            self.style.configure("TButton", background="#e0e0e0", foreground="#222", borderwidth=0, relief="flat")
            self.style.map("TButton", background=[("active", "#d0d0d0")])

        # ----------- FIN NUEVO -----------

        # Inicializaciones
        self.root.title("BoyKisser Desktop")
        w, h = self.config["appearance"]["size"]
        self.root.geometry(f"{w}x{h}")
        self.root.configure(bg="white")
        self.root.attributes("-topmost", self.config["appearance"].get("always_on_top", True))
        if self.config["appearance"].get("opacity", 1.0) < 1.0:
            try:
                self.root.attributes("-alpha", float(self.config["appearance"]["opacity"]))
            except Exception:
                pass

        # Title bar
        self.title_bar_visible = self.config["appearance"].get("show_title_bar", False)
        self.set_title_bar(self.title_bar_visible)

        # Paths
        self.base_dir = os.path.abspath(os.path.dirname(__file__))
        self.sounds_path = os.path.join(self.base_dir, "sounds")
        if not os.path.exists(self.sounds_path):
            os.makedirs(self.sounds_path)
        self.assets_dir = os.path.join(self.base_dir, "assets")
        if not os.path.exists(self.assets_dir):
            os.makedirs(self.assets_dir)

        # Pygame mixer
        pygame.mixer.init()
        self.max_channels = 32
        pygame.mixer.set_num_channels(self.max_channels)

        # Cargar images
        self.load_images()

        # Label imagen
        self.label = tk.Label(root, image=self.img_main, bg="white", borderwidth=0)
        self.label.pack(expand=True, fill="both")

        # Bind drag and context menu
        if self.config["behavior"].get("draggable", True):
            self.label.bind("<Button-1>", self.start_move)
            self.label.bind("<B1-Motion>", self.do_move)
        self.label.bind("<Button-3>", self.show_context_menu)

        # Context menu
        # Context menu decorado
        self.menu = tk.Menu(self.root, tearoff=0, bg="#222", fg="#fff", activebackground="#444", activeforeground="#00fff7", font=("Arial", 11, "bold"))
        self.menu.add_command(label="🛠 Abrir configuración...", command=self.open_settings)
        self.menu.add_separator()
        self.menu.add_command(label="❌ Cerrar programa", command=self.on_close)  # <--- Cambia aquí

        # State
        self._x = 0
        self._y = 0

        # Hotkeys listener (optional)
        self.hotkey_thread = None
        self.keyboard_listener = None
        self.mouse_listener = None

        # Click tracking
        self.click_milestones = [10, 100, 500, 1000, 50000, 1000000, 50000000]

        # Start listeners
        if self.config["hotkeys"].get("enabled", True):
            self.start_hotkeys_listener()
        threading.Thread(target=self.listen_mouse, daemon=True).start()

        # Apply start_minimized
        if self.config["behavior"].get("start_minimized", False):
            self.root.withdraw()

        # Save config on exit
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- NUEVO: Inicializa contador ---
        self.show_counter = True
        self.counter_style = "default"
        self.counter_label = tk.Label(self.root, text=f"Clics: {self.click_count}", bg="white", fg="#222", font=("Arial", 12, "bold"))
        self.counter_label.place(x=10, y=10)
        self.update_counter_label()
        # --- FIN NUEVO ---

        # --- NUEVO: Inicia listener de hotkeys ---
        self.start_hotkeys_listener()
        # --- FIN NUEVO ---

    # ---------------- Image helpers ----------------
    def load_images(self):
        main_img_path = resource_path(self.config["appearance"].get("main_image", "assets/main.png"))
        hover_img_path = resource_path(self.config["appearance"].get("hover_image", "assets/hover.png"))
        w, h = self.config["appearance"].get("size", [400,400])
        try:
            main = Image.open(main_img_path).convert("RGBA").resize((w, h))
            hover = Image.open(hover_img_path).convert("RGBA").resize((w, h))
        except Exception:
            # Fallback: create solid color images
            main = Image.new("RGBA", (w, h), (230,230,250))
            hover = Image.new("RGBA", (w, h), (220,240,220))
        self.img_main = ImageTk.PhotoImage(main)
        self.img_hover = ImageTk.PhotoImage(hover)

    # ---------------- Config window ----------------
    def open_settings(self):
        # Si ya existe, solo actualiza el estilo y trae al frente
        if hasattr(self, "settings_win") and self.settings_win.winfo_exists():
            self.apply_settings_style()
            self.settings_win.lift()
            return

        self.settings_win = tk.Toplevel(self.root)
        self.settings_win.title("Configuración")
        self.settings_win.geometry("800x480")
        self.apply_settings_style()

        # layout: left list (30%), right content (70%)
        left = ttk.Frame(self.settings_win, width=220)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self.settings_win)
        right.pack(side="right", fill="both", expand=True)

        sections = ["Audio", "Apariencia", "Comportamiento", "Atajos", "Avanzado", "Redes sociales"]  # <--- Añade aquí
        self.section_list = tk.Listbox(left, activestyle="none", bd=0, highlightthickness=0,
            bg="#333" if self.theme == "dark" else "#fff",
            fg="#eee" if self.theme == "dark" else "#222",
            selectbackground="#444" if self.theme == "dark" else "#e0e0e0",
            font=("Segoe UI", 12))
        for s in sections:
            self.section_list.insert("end", s)
        self.section_list.pack(fill="both", expand=True, padx=8, pady=8)
        self.section_list.bind("<<ListboxSelect>>", lambda e: self._show_section(right))
        self.section_list.selection_set(0)

        # footer: save/reset/import/export
        footer = ttk.Frame(left)
        footer.pack(fill="x", side="bottom", pady=6)
        ttk.Button(footer, text="Guardar ahora", command=lambda: (save_config(self.config), messagebox.showinfo("Guardado","Configuración guardada"))).pack(fill="x", padx=8, pady=3)
        ttk.Button(footer, text="Restaurar por defecto", command=self._restore_defaults).pack(fill="x", padx=8, pady=3)

        # Initially show first section
        self._show_section(right)

    def apply_settings_style(self):
        deluxe = self.config["appearance"].get("deluxe_mode", False)
        if not hasattr(self, "settings_win") or not self.settings_win.winfo_exists():
            return
        if deluxe:
            self.settings_win.configure(bg="#000000")
            self.settings_win.attributes("-alpha", 0.8)
            style = ttk.Style(self.settings_win)
            style.theme_use("clam")
            style.configure("TFrame", background="#000000")
            style.configure("TLabel", background="#000000", foreground="#ffffff", font=("Arial", 12, "bold"))
            style.configure("TButton", background="#222", foreground="#ffffff", borderwidth=0, relief="flat", font=("Arial", 11, "bold"))
            style.configure("TCheckbutton", background="#000000", foreground="#ffffff", font=("Arial", 11, "bold"))
            style.map("TButton", background=[("active", "#333")])
        else:
            self.settings_win.configure(bg="#222" if self.theme == "dark" else "#f7f7f7")
            self.settings_win.attributes("-alpha", 1.0)
            style = ttk.Style(self.settings_win)
            style.theme_use("clam")
            style.configure("TFrame", background="#222" if self.theme == "dark" else "#f7f7f7")
            style.configure("TLabel", background="#222" if self.theme == "dark" else "#f7f7f7", foreground="#eee" if self.theme == "dark" else "#222", font=("Segoe UI", 12))
            style.configure("TButton", background="#333" if self.theme == "dark" else "#e0e0e0", foreground="#eee" if self.theme == "dark" else "#222", borderwidth=0, relief="flat", font=("Segoe UI", 11))
            style.configure("TCheckbutton", background="#222" if self.theme == "dark" else "#f7f7f7", foreground="#eee" if self.theme == "dark" else "#222", font=("Segoe UI", 11))
            style.map("TButton", background=[("active", "#444" if self.theme == "dark" else "#d0d0d0")])

    def _show_section(self, parent_frame):
        for w in parent_frame.winfo_children():
            w.destroy()
        sel = self.section_list.get(self.section_list.curselection())
        if sel == "Audio":
            self._audio_ui(parent_frame)
        elif sel == "Apariencia":
            self._appearance_ui(parent_frame)
        elif sel == "Comportamiento":
            self._behavior_ui(parent_frame)
        elif sel == "Atajos":
            self._hotkeys_ui(parent_frame)
        elif sel == "Avanzado":
            self._advanced_ui(parent_frame)
        elif sel == "Redes sociales":
            self._social_ui(parent_frame)  # <--- Añade esto

    def _social_ui(self, frame):
        import webbrowser

        # Usa tk.Frame para poder cambiar el fondo
        social_frame = tk.Frame(frame, bg="#222")
        social_frame.pack(expand=True, fill="both")

        # Título
        tk.Label(social_frame, text="Redes sociales", font=("Arial", 16, "bold"), fg="#5865F2", bg="#222").pack(anchor="n", pady=(30,10))

        tk.Frame(social_frame, height=2, bg="#444").pack(fill="x", padx=12, pady=8)

        # Frame centrado para los botones
        btns_frame = tk.Frame(social_frame, bg="#222")
        btns_frame.pack(anchor="center", pady=40)

        def open_discord():
            webbrowser.open("https://discord.gg/uxRavuMMdm")
        def open_github():
            webbrowser.open("https://github.com/dotva/BoyKisser_DesktopPartner")

        style = ttk.Style()
        style.configure("Social.TButton",
                        font=("Arial", 14, "bold"),
                        background="#5865F2",
                        foreground="#fff",
                        borderwidth=0,
                        relief="flat",
                        padding=12)
        style.map("Social.TButton",
                  background=[("active", "#404EED"), ("!active", "#5865F2")],
                  foreground=[("active", "#fff")])

        discord_btn = ttk.Button(btns_frame, text="Discord", command=open_discord, style="Social.TButton")
        discord_btn.pack(side="left", padx=(0,20), ipadx=20, ipady=10)
        github_btn = ttk.Button(btns_frame, text="GitHub", command=open_github, style="Social.TButton")
        github_btn.pack(side="left", ipadx=20, ipady=10)

        for btn in [discord_btn, github_btn]:
            btn.configure(cursor="hand2")
            btn.update()
            btn['style'] = "Social.TButton"

    # ------------------- Audio UI -------------------
    def _audio_ui(self, frame):
        tk.Label(frame, text="Audio", font=("Segoe UI", 14, "bold"), bg="white").pack(anchor="nw", pady=8, padx=12)
        cfg = self.config["audio"]

        # Mute
        mute_var = tk.BooleanVar(value=cfg.get("muted", False))
        tk.Checkbutton(frame, text="Silenciar audio", variable=mute_var, bg="white", command=lambda: self._set_and_save("audio","muted", mute_var.get())).pack(anchor="nw", padx=12, pady=4)

        # Allow overlap
        overlap_var = tk.BooleanVar(value=cfg.get("allow_overlap", True))
        tk.Checkbutton(frame, text="Permitir solapamiento de sonidos", variable=overlap_var, bg="white", command=lambda: self._set_and_save("audio","allow_overlap", overlap_var.get())).pack(anchor="nw", padx=12, pady=4)

        # Fixed sound
        fixed_var = tk.BooleanVar(value=cfg.get("fixed_sound", False))
        tk.Checkbutton(frame, text="Usar siempre el mismo sonido", variable=fixed_var, bg="white", command=lambda: self._set_and_save("audio","fixed_sound", fixed_var.get())).pack(anchor="nw", padx=12, pady=4)

        # Fixed file selector
        def choose_fixed():
            file = filedialog.askopenfilename(title="Seleccionar archivo de audio", filetypes=[("Audio files","*.mp3 *.wav *.ogg")])
            if file:
                self._set_and_save("audio","fixed_file", file)
                lbl_fixed.config(text=os.path.basename(file))
                fixed_var.set(True)
                self._set_and_save("audio","fixed_sound", True)

        btn = tk.Button(frame, text="Elegir archivo fijo...", command=choose_fixed)
        btn.pack(anchor="nw", padx=12, pady=6)
        lbl_fixed = tk.Label(frame, text=os.path.basename(cfg.get("fixed_file","")) or "Ninguno seleccionado", bg="white")
        lbl_fixed.pack(anchor="nw", padx=12)

        # Volume
        tk.Label(frame, text="Volumen (global)", bg="white").pack(anchor="nw", padx=12, pady=(12,0))
        vol_var = tk.DoubleVar(value=cfg.get("volume", 0.9))
        def on_vol(v):
            self._set_and_save("audio","volume", float(v))
        vol_scale = tk.Scale(frame, from_=0.0, to=1.0, resolution=0.01, orient="horizontal", variable=vol_var, command=on_vol, bg="white", length=420)
        vol_scale.pack(anchor="nw", padx=12)

        # Random volume
        rand_vol_var = tk.BooleanVar(value=cfg.get("random_volume", False))
        tk.Checkbutton(frame, text="Volumen aleatorio entre rangos", variable=rand_vol_var, bg="white", command=lambda: self._set_and_save("audio","random_volume", rand_vol_var.get())).pack(anchor="nw", padx=12, pady=6)
        rng_frame = tk.Frame(frame, bg="white")
        rng_frame.pack(anchor="nw", padx=12)
        tk.Label(rng_frame, text="Mín:", bg="white").grid(row=0,column=0)
        min_var = tk.DoubleVar(value=cfg.get("random_volume_min",0.6))
        tk.Entry(rng_frame, textvariable=min_var, width=6).grid(row=0,column=1, padx=6)
        tk.Label(rng_frame, text="Máx:", bg="white").grid(row=0,column=2)
        max_var = tk.DoubleVar(value=cfg.get("random_volume_max",1.0))
        tk.Entry(rng_frame, textvariable=max_var, width=6).grid(row=0,column=3, padx=6)
        def save_rng():
            a = float(min_var.get()); b = float(max_var.get())
            if a < 0 or b > 1 or a > b:
                messagebox.showerror("Rango inválido","Introduce valores entre 0.0 y 1.0 y min <= max")
                return
            self._set_and_save("audio","random_volume_min", a)
            self._set_and_save("audio","random_volume_max", b)
        tk.Button(frame, text="Guardar rango", command=save_rng).pack(anchor="nw", padx=12, pady=6)

        # Test sound
        tk.Button(frame, text="Probar sonido (aleatorio)", command=lambda: threading.Thread(target=self._play_random_sound_thread, daemon=True).start()).pack(anchor="nw", padx=12, pady=10)

    # ------------------ Appearance UI ------------------
    def _appearance_ui(self, frame):
        cfg = self.config["appearance"]
        deluxe = cfg.get("deluxe_mode", False)
        theme_bg = "#000000" if deluxe else ("#222" if self.theme == "dark" else "#f7f7f7")
        theme_fg = "#ffffff" if deluxe else ("#eee" if self.theme == "dark" else "#222")
        accent = "#ffffff" if deluxe else ("#4e8cff" if self.theme == "dark" else "#1976d2")
        neon_font = ("Arial", 13, "bold") if deluxe else ("Segoe UI", 13, "bold")

        # Switch Deluxe
        deluxe_var = tk.BooleanVar(value=deluxe)
        def toggle_deluxe():
            val = deluxe_var.get()
            self._set_and_save("appearance", "deluxe_mode", val)
            self.apply_settings_style()
            self._show_section(frame)

        deluxe_chk = ttk.Checkbutton(frame, text="Modo Deluxe (neón futurista)", variable=deluxe_var, command=toggle_deluxe)
        deluxe_chk.pack(anchor="nw", padx=16, pady=8)

        title = ttk.Label(frame, text="Apariencia", font=("Arial", 16, "bold") if deluxe else ("Segoe UI", 16, "bold"), foreground=accent, background=theme_bg)
        title.pack(anchor="nw", pady=(12,4), padx=16)

        sep = ttk.Separator(frame, orient="horizontal")
        sep.pack(fill="x", padx=12, pady=6)

        # Tamaño
        size_lbl = ttk.Label(frame, text="Tamaño de ventana", font=neon_font, foreground=theme_fg, background=theme_bg)
        size_lbl.pack(anchor="nw", padx=16, pady=(8,2))
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(anchor="nw", padx=16, pady=2)
        for preset in cfg.get("presets", [[200,200],[400,400],[600,600]]):
            b = ttk.Button(btn_frame, text=f"{preset[0]}x{preset[1]}", style="Accent.TButton", command=lambda p=preset: self.change_size(p[0],p[1]))
            b.pack(side="left", padx=4)

        sep2 = ttk.Separator(frame, orient="horizontal")
        sep2.pack(fill="x", padx=12, pady=8)

        # Fondo
        bg_lbl = ttk.Label(frame, text="Color de fondo", font=neon_font, foreground=theme_fg, background=theme_bg)
        bg_lbl.pack(anchor="nw", padx=16, pady=(8,2))
        def choose_bg():
            from tkinter.colorchooser import askcolor
            color = askcolor()[1]
            if color:
                self.root.configure(bg=color)
                self._set_and_save("appearance", "bg_color", color)
        bg_btn = ttk.Button(frame, text="Elegir color...", command=choose_bg)
        bg_btn.pack(anchor="nw", padx=16, pady=2)

        sep3 = ttk.Separator(frame, orient="horizontal")
        sep3.pack(fill="x", padx=12, pady=8)

        # Always on top
        top_var = tk.BooleanVar(value=cfg.get("always_on_top", True))
        top_chk = ttk.Checkbutton(frame, text="Siempre encima", variable=top_var, command=lambda: (self.root.attributes("-topmost", top_var.get()), self._set_and_save("appearance","always_on_top", top_var.get())))
        top_chk.pack(anchor="nw", padx=16, pady=4)

        # Barra de título
        title_var = tk.BooleanVar(value=cfg.get("show_title_bar", False))
        title_chk = ttk.Checkbutton(frame, text="Mostrar barra de título", variable=title_var, command=lambda: (self.set_title_bar(title_var.get()), self._set_and_save("appearance","show_title_bar", title_var.get())))
        title_chk.pack(anchor="nw", padx=16, pady=4)

        # Opacidad
        opa_lbl = ttk.Label(frame, text="Opacidad", font=neon_font, foreground=theme_fg, background=theme_bg)
        opa_lbl.pack(anchor="nw", padx=16, pady=(8,2))
        opa_var = tk.DoubleVar(value=cfg.get("opacity",1.0))
        def on_opa(v):
            try:
                val = float(v)
                self.root.attributes("-alpha", val)
                self._set_and_save("appearance","opacity", val)
            except Exception:
                pass
        opa_scale = ttk.Scale(frame, from_=0.3, to=1.0, variable=opa_var, command=on_opa)
        opa_scale.pack(anchor="nw", padx=16, pady=2)

        sep4 = ttk.Separator(frame, orient="horizontal")
        sep4.pack(fill="x", padx=12, pady=8)

        # Imágenes
        img_lbl = ttk.Label(frame, text="Imágenes (main / hover)", font=neon_font, foreground=theme_fg, background=theme_bg)
        img_lbl.pack(anchor="nw", padx=16, pady=(8,2))
        img_frame = ttk.Frame(frame)
        img_frame.pack(anchor="nw", padx=16, pady=2)
        def set_main_img():
            f = filedialog.askopenfilename(title="Seleccionar main image", filetypes=[("Imagen","*.png *.jpg *.jpeg *.gif")])
            if f:
                rel = os.path.relpath(f, self.base_dir)
                self._set_and_save("appearance","main_image", rel)
                self.load_images(); self.label.configure(image=self.img_main)
        def set_hover_img():
            f = filedialog.askopenfilename(title="Seleccionar hover image", filetypes=[("Imagen","*.png *.jpg *.jpeg *.gif")])
            if f:
                rel = os.path.relpath(f, self.base_dir)
                self._set_and_save("appearance","hover_image", rel)
                self.load_images(); self.label.configure(image=self.img_main)
        main_btn = ttk.Button(img_frame, text="Elegir main...", command=set_main_img)
        main_btn.pack(side="left", padx=6)
        hover_btn = ttk.Button(img_frame, text="Elegir hover...", command=set_hover_img)
        hover_btn.pack(side="left", padx=6)

        # --- Contador de clics ---
        ttk.Separator(frame, orient="horizontal").pack(fill="x", padx=12, pady=8)
        ttk.Label(frame, text="Contador de clics", font=("Arial", 13, "bold")).pack(anchor="nw", padx=16, pady=(8,2))

        style_var = tk.StringVar(value=getattr(self, "counter_style", "default"))
        def set_style():
            self.counter_style = style_var.get()
            self.update_counter_label()
        ttk.Label(frame, text="Estilo:").pack(anchor="nw", padx=16, pady=(8,2))
        ttk.Combobox(frame, textvariable=style_var, values=["default", "neon", "minimal"], state="readonly").pack(anchor="nw", padx=16, pady=2)
        ttk.Button(frame, text="Aplicar estilo", command=set_style).pack(anchor="nw", padx=16, pady=2)

    # ---------------- Behavior UI ----------------
    def _behavior_ui(self, frame):
        tk.Label(frame, text="Comportamiento", font=("Segoe UI", 14, "bold"), bg="white").pack(anchor="nw", pady=8, padx=12)
        cfg = self.config["behavior"]

        # Startup with windows
        start_var = tk.BooleanVar(value=cfg.get("start_with_windows", False))
        tk.Checkbutton(frame, text="Iniciar con Windows (acceso directo)", variable=start_var, bg="white", command=lambda: (self._toggle_startup(), self._set_and_save("behavior","start_with_windows", start_var.get()))).pack(anchor="nw", padx=12, pady=6)

        # Start minimized
        min_var = tk.BooleanVar(value=cfg.get("start_minimized", False))
        tk.Checkbutton(frame, text="Iniciar minimizado", variable=min_var, bg="white", command=lambda: self._set_and_save("behavior","start_minimized", min_var.get())).pack(anchor="nw", padx=12, pady=6)

        # Draggable
        drag_var = tk.BooleanVar(value=cfg.get("draggable", True))
        def toggle_drag():
            val = drag_var.get()
            if val:
                self.label.bind("<Button-1>", self.start_move);
                self.label.bind("<B1-Motion>", self.do_move)
            else:
                self.label.unbind("<Button-1>"); self.label.unbind("<B1-Motion>")
            self._set_and_save("behavior","draggable", val)
        tk.Checkbutton(frame, text="Permitir arrastrar ventana", variable=drag_var, bg="white", command=toggle_drag).pack(anchor="nw", padx=12, pady=6)

    # ---------------- Hotkeys UI ----------------
    def _hotkeys_ui(self, frame):
        tk.Label(frame, text="Atajos (Hotkeys)", font=("Segoe UI", 14, "bold"), bg="white").pack(anchor="nw", pady=8, padx=12)
        cfg = self.config["hotkeys"]

        enabled_var = tk.BooleanVar(value=cfg.get("enabled", True))
        def toggle_hotkeys():
            val = enabled_var.get()
            self._set_and_save("hotkeys","enabled", val)
            # (Re)start listeners
            # For simplicity we won't implement full dynamic rebind here; informing user
            messagebox.showinfo("Hotkeys","Cambio aplicado. Reinicia la aplicaci\u00f3n para aplicar cambios de hotkeys.")
        tk.Checkbutton(frame, text="Habilitar escuchador de teclas/mouse global", variable=enabled_var, bg="white", command=toggle_hotkeys).pack(anchor="nw", padx=12, pady=6)

        tk.Label(frame, text="Atajo: Abrir configuraci\u00f3n (informativo)", bg="white").pack(anchor="nw", padx=12, pady=(8,0))
        tk.Label(frame, text=cfg.get("open_settings","<ctrl>+<alt>+s"), bg="white").pack(anchor="nw", padx=12)
        tk.Label(frame, text="Atajo: Silenciar/activar audio (informativo)", bg="white").pack(anchor="nw", padx=12, pady=(8,0))
        tk.Label(frame, text=cfg.get("toggle_mute","<ctrl>+<alt>+m"), bg="white").pack(anchor="nw", padx=12)

        tk.Label(frame, text="Nota: Cambiar hotkeys en caliente no est\u00e1 implementado en esta versi\u00f3n.", bg="white", fg="gray").pack(anchor="nw", padx=12, pady=10)

    # ---------------- Advanced UI ----------------
    def _advanced_ui(self, frame):
        tk.Label(frame, text="Avanzado", font=("Segoe UI", 14, "bold"), bg="white").pack(anchor="nw", pady=8, padx=12)
        cfg = self.config["advanced"]
        dbg_var = tk.BooleanVar(value=cfg.get("debug_logging", False))
        tk.Checkbutton(frame, text="Activar logging de depuración", variable=dbg_var, bg="white", command=lambda: self._set_and_save("advanced","debug_logging", dbg_var.get())).pack(anchor="nw", padx=12, pady=6)

        def export_cfg():
            f = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
            if f:
                with open(f, "w", encoding="utf-8") as fh:
                    json.dump(self.config, fh, indent=4, ensure_ascii=False)
                messagebox.showinfo("Exportado","Configuración exportada")
        def import_cfg():
            f = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
            if f:
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        imported = json.load(fh)
                    self.config.update(imported)
                    save_config(self.config)
                    messagebox.showinfo("Importado","Configuración importada. Reinicia la app para aplicar cambios.")
                except Exception as e:
                    messagebox.showerror("Error","No se pudo importar: %s"%e)
        tk.Button(frame, text="Exportar configuración...", command=export_cfg).pack(anchor="nw", padx=12, pady=6)
        tk.Button(frame, text="Importar configuración...", command=import_cfg).pack(anchor="nw", padx=12, pady=6)

        # --- BOTÓN PARA FORMATEAR CONTADOR DE CLICS ---
        ttk.Separator(frame, orient="horizontal").pack(fill="x", padx=12, pady=8)
        ttk.Label(frame, text="Contador de clics", font=("Arial", 13, "bold")).pack(anchor="nw", padx=16, pady=(8,2))

        def reset_clicks():
            if messagebox.askyesno("Confirmar", "¿Seguro que quieres reestablecer el contador de clics a 0?"):
                self.click_count = 0
                self.config["click_count"] = 0
                save_config(self.config)
                self.update_counter_label()
        ttk.Button(frame, text="Reestablecer contador de clics", command=reset_clicks).pack(anchor="nw", padx=16, pady=6)

    # ---------------- Utility UI helpers ----------------
    def _set_and_save(self, section, key, value):
        self.config.setdefault(section, {})
        self.config[section][key] = value
        save_config(self.config)

    def _restore_defaults(self):
        if messagebox.askyesno("Confirmar","Restaurar valores por defecto? Esto reiniciara la configuracion."):
            self.config = DEFAULT_CONFIG.copy()
            save_config(self.config)
            messagebox.showinfo("Restaurado","Configuracion restaurada. Reinicia la app para aplicar todos los cambios.")

    # ---------------- Sound playback ----------------
    def _play_random_sound_thread(self):
        """Thread helper that calls play_random_sound safely."""
        self.play_random_sound()

    def play_random_sound(self):
        cfg = self.config["audio"]
        if cfg.get("muted", False):
            return
        try:
            if cfg.get("fixed_sound") and cfg.get("fixed_file"):
                sound_file = cfg.get("fixed_file")
                if not os.path.isabs(sound_file):
                    sound_file = os.path.join(self.base_dir, sound_file)
            else:
                files = [os.path.join(self.sounds_path, f) for f in os.listdir(self.sounds_path) if f.lower().endswith((".mp3",".wav",".ogg"))]
                if not files:
                    if self.config["advanced"].get("debug_logging"):
                        print("No hay archivos de audio en carpeta sounds")
                    return
                sound_file = random.choice(files)

            ch = pygame.mixer.find_channel()
            if ch is None:
                # no channel free; if overlap not allowed, stop oldest or skip
                if not cfg.get("allow_overlap", True):
                    return
                else:
                    # try to set more channels
                    pygame.mixer.set_num_channels(min(self.max_channels+8, 128))
                    ch = pygame.mixer.find_channel()
                    if ch is None:
                        return

            sound = pygame.mixer.Sound(sound_file)
            volume = cfg.get("volume", 0.9)
            if cfg.get("random_volume"):
                mn = cfg.get("random_volume_min", 0.6)
                mx = cfg.get("random_volume_max", 1.0)
                try:
                    volume = random.uniform(mn, mx)
                except Exception:
                    pass
            sound.set_volume(max(0.0, min(1.0, float(volume))))
            ch.play(sound)
            if self.config["advanced"].get("debug_logging"):
                print(f"Playing: {sound_file} vol={volume}")
        except Exception as e:
            if self.config["advanced"].get("debug_logging"):
                print("Error reproduciendo sonido:", e)

    # ---------------- Listeners ----------------
    def listen_keyboard(self):
        pressed_keys = set()
        def on_press(key):
            if key not in pressed_keys:
                pressed_keys.add(key)
                try:
                    self.click_count += 1
                    self.config["click_count"] = self.click_count
                    save_config(self.config)
                    self.update_counter_label()
                    self.root.after(0, self.set_hover)
                    threading.Thread(target=self._play_random_sound_thread, daemon=True).start()
                except Exception:
                    pass
        def on_release(key):
            pressed_keys.discard(key)
            try:
                self.root.after(0, self.set_main)
            except Exception:
                pass
        threading.Thread(target=lambda: keyboard.Listener(on_press=on_press, on_release=on_release).run(), daemon=True).start()

    def listen_mouse(self):
        def on_click(x, y, button, pressed):
            if pressed:
                try:
                    self.click_count += 1
                    self.config["click_count"] = self.click_count  # <--- Guarda el contador
                    save_config(self.config)  # <--- Guarda en disco
                    self.update_counter_label()
                    self.root.after(0, self.set_hover)
                    threading.Thread(target=self._play_random_sound_thread, daemon=True).start()
                except Exception:
                    pass
            else:
                try:
                    self.root.after(0, self.set_main)
                except Exception:
                    pass
        with mouse.Listener(on_click=on_click) as listener:
            listener.join()

    # ---------------- Window movement ----------------
    def start_move(self, event):
        if not self.title_bar_visible and self.config["behavior"].get("draggable", True):
            self._x = event.x
            self._y = event.y

    def do_move(self, event):
        if not self.title_bar_visible and self.config["behavior"].get("draggable", True):
            x = self.root.winfo_pointerx() - self._x
            y = self.root.winfo_pointery() - self._y
            self.root.geometry(f"+{x}+{y}")

    # ---------------- Title bar ----------------
    def set_title_bar(self, visible: bool):
        self.title_bar_visible = visible
        if visible:
            self.root.overrideredirect(False)
        else:
            self.root.overrideredirect(True)

    # ---------------- Startup shortcut ----------------
    def _toggle_startup(self):
        # create/remove shortcut in startup folder
        try:
            import pythoncom
            import win32com.client
        except Exception:
            messagebox.showwarning("pywin32 falta","pywin32 no est\u00e1 instalado. No se puede crear acceso directo.")
            return
        startup = os.path.join(os.environ.get("APPDATA",""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        shortcut_path = os.path.join(startup, "BoyKisserDesktop.lnk")
        if os.path.exists(shortcut_path):
            try:
                os.remove(shortcut_path)
                messagebox.showinfo("Startup","Acceso directo eliminado")
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
                messagebox.showinfo("Startup","Acceso directo creado")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ---------------- Context menu ----------------
    def show_context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ---------------- Misc ----------------
    def set_hover(self):
        try:
            self.label.configure(image=self.img_hover)
            # Cambia a imagen principal después de 0.3 segundos
            self.root.after(100, self.set_main)
        except Exception:
            pass

    def set_main(self):
        try:
            self.label.configure(image=self.img_main)
        except Exception:
            pass

    def change_size(self, w, h):
        self.config["appearance"]["size"] = [w,h]
        save_config(self.config)
        self.root.geometry(f"{w}x{h}")
        self.load_images()
        self.label.configure(image=self.img_main)

    def on_close(self):
        # Reproducir sonido de despedida aleatorio antes de cerrar
        bye_files = [os.path.join(self.assets_dir, "bye.mp3"), os.path.join(self.assets_dir, "bye2.mp3")]
        bye_choices = [f for f in bye_files if os.path.exists(f)]
        if bye_choices:
            try:
                bye_path = random.choice(bye_choices)
                ch = pygame.mixer.find_channel()
                if ch is None:
                    pygame.mixer.set_num_channels(min(self.max_channels+8, 128))
                    ch = pygame.mixer.find_channel()
                if ch is not None:
                    sound = pygame.mixer.Sound(bye_path)
                    sound.set_volume(1.0)
                    ch.play(sound)
                    # Espera a que termine el sonido (máx 3 segundos)
                    time.sleep(min(sound.get_length(), 3))
            except Exception:
                pass
        save_config(self.config)
        self.root.destroy()

    def _fade_out_notification(self, notif):
        # Fade-out
        for i in range(10, -1, -1):
            notif.attributes("-alpha", i/10)
            notif.update()
            time.sleep(0.03)
        notif.destroy()


    def update_counter_label(self):
        if hasattr(self, "counter_label"):
            self.counter_label.config(text=f"Clics: {self.click_count}")
        else:
            if getattr(self, "show_counter", True):
                self.counter_label.place(x=10, y=10)
                style = getattr(self, "counter_style", "default")
                if style == "neon":
                    self.counter_label.config(bg="#222", fg="#00fff7", font=("Arial", 14, "bold"))
                elif style == "minimal":
                    self.counter_label.config(bg="#fff", fg="#888", font=("Segoe UI", 11))
                else:
                    self.counter_label.config(bg="#222", fg="#fff", font=("Arial", 12, "bold"))
                self.counter_label.config(text=f"Clics: {self.click_count}")
            else:
                self.counter_label.place_forget()

    # -------- NUEVO: Hotkeys listener -----------
    def start_hotkeys_listener(self):
        hotkeys = self.config.get("hotkeys", {})
        open_settings_hotkey = hotkeys.get("open_settings", "<ctrl>+<alt>+s")
        toggle_mute_hotkey = hotkeys.get("toggle_mute", "<ctrl>+<alt>+m")

        # Helper para convertir string a set de teclas
        def hotkey_to_set(hotkey_str):
            keys = set()
            for part in hotkey_str.lower().replace("<", "").replace(">", "").split("+"):
                if part == "ctrl":
                    keys.add(keyboard.Key.ctrl_l)
                    keys.add(keyboard.Key.ctrl_r)
                elif part == "alt":
                    keys.add(keyboard.Key.alt_l)
                    keys.add(keyboard.Key.alt_r)
                elif part == "shift":
                    keys.add(keyboard.Key.shift)
                elif len(part) == 1:
                    keys.add(part)
            return keys

        open_settings_keys = hotkey_to_set(open_settings_hotkey)
        toggle_mute_keys = hotkey_to_set(toggle_mute_hotkey)

        pressed = set()

        def key_match(hotkey_keys, pressed_keys):
            # hotkey_keys puede tener Key y str, pressed_keys igual
            for k in hotkey_keys:
                if isinstance(k, keyboard.Key):
                    if k not in pressed_keys:
                        return False
                else:
                    found = False
                    for pk in pressed_keys:
                        if isinstance(pk, keyboard.KeyCode) and pk.char == k:
                            found = True
                            break
                    if not found:
                        return False
            return True

        def on_press(key):
            pressed.add(key)
            # Abrir configuración
            if key_match(open_settings_keys, pressed):
                self.root.after(0, self.open_settings)
            # Silenciar audio
            if key_match(toggle_mute_keys, pressed):
                self.config["audio"]["muted"] = not self.config["audio"].get("muted", False)
                save_config(self.config)
                messagebox.showinfo("Audio", f'Audio {"silenciado" if self.config["audio"]["muted"] else "activado"}')

        def on_release(key):
            pressed.discard(key)

        self.hotkey_thread = threading.Thread(target=lambda: keyboard.Listener(on_press=on_press, on_release=on_release).run(), daemon=True)
        self.hotkey_thread.start()
    # -------- FIN NUEVO -----------


if __name__ == "__main__":
    root = tk.Tk()
    app = GlobalInputApp(root)
    root.mainloop()
