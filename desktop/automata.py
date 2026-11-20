"""Local desktop control panel for Esperanza TV."""
import json
import logging
import os
import queue
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from playout import Slot, make_block, run, save, Obs

DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AutomataTV"
SCHEDULE = DATA / "parrilla.json"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class Panel:
    def __init__(self, root):
        self.root = root
        self.events = queue.SimpleQueue()
        self.stop = threading.Event()
        self.worker = None
        self.slots = []
        self.fallback = ""
        self.snapshot = ((), "")
        if SCHEDULE.exists():
            saved = json.loads(SCHEDULE.read_text(encoding="utf-8"))
            self.slots = [Slot(**slot) for slot in saved["slots"]]
            self.fallback = saved["fallback"]
            self.snapshot = (tuple(self.slots), self.fallback)
        self.status = tk.StringVar(value="Automatización detenida")
        self.clock = tk.StringVar()
        self.continuity = tk.StringVar()
        self.start = tk.StringVar(value=datetime.now().replace(second=0).strftime(TIME_FORMAT))
        self.kind = tk.StringVar(value="Episodio")
        root.title("Automata TV · Esperanza TV")
        root.geometry("1050x640")
        root.minsize(840, 510)
        root.configure(bg="#111827")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#e5edf8")
        style.configure("Title.TLabel", font=("Segoe UI", 24, "bold"))
        style.configure("Accent.TButton", background="#18796c", foreground="white")
        style.map("Accent.TButton", background=[("active", "#15685d")])
        style.configure("Treeview", rowheight=30, background="#1f2937",
                        fieldbackground="#1f2937", foreground="#e5edf8")
        style.configure("Treeview.Heading", background="#dce7f4", foreground="#182336")
        style.map("Treeview", background=[("selected", "#236a73")])

        frame = ttk.Frame(root, padding=22)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Label(header, text="Automata TV", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Esperanza TV  ·  ", padding=(12, 8)).pack(side="left")
        ttk.Label(header, textvariable=self.clock).pack(side="right")

        connection = ttk.Frame(frame)
        connection.pack(fill="x", pady=(18, 7))
        self.scene = self.field(connection, "Escena OBS", "Automata TV")
        self.source = self.field(connection, "Fuente", "TV_PLAYER")
        self.password = self.field(connection, "Contraseña OBS", "", show="*")
        self.control = ttk.Button(connection, text="Activar automatización",
                                  style="Accent.TButton", command=self.toggle)
        self.control.pack(side="right")

        continuity = ttk.Frame(frame)
        continuity.pack(fill="x", pady=(4, 14))
        ttk.Button(continuity, text="Elegir MP4 de continuidad",
                   command=self.choose_fallback).pack(side="left")
        ttk.Label(continuity, textvariable=self.continuity, padding=(10, 0)).pack(side="left")

        editor = ttk.Frame(frame)
        editor.pack(fill="x", pady=(0, 8))
        ttk.Label(editor, text="Inicio local (AAAA-MM-DD HH:MM:SS)").pack(side="left")
        ttk.Entry(editor, textvariable=self.start, width=21).pack(side="left", padx=8)
        ttk.Combobox(editor, textvariable=self.kind, values=("Episodio", "Comercial", "Identificación"),
                     state="readonly", width=15).pack(side="left", padx=(0, 8))
        self.add_button = ttk.Button(editor, text="Agregar MP4", command=self.add)
        self.add_button.pack(side="left")
        ttk.Button(editor, text="Quitar seleccionado", command=self.remove).pack(side="right")

        table = ttk.Frame(frame)
        table.pack(fill="both", expand=True)
        self.grid = ttk.Treeview(table, columns=("start", "end", "kind", "file"), show="headings")
        for key, title, width in (("start", "Inicio local", 168), ("end", "Fin local", 168),
                                   ("kind", "Tipo", 120), ("file", "Archivo", 320)):
            self.grid.heading(key, text=title)
            self.grid.column(key, width=width, stretch=key == "file")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.grid.yview)
        self.grid.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.grid.pack(side="left", fill="both", expand=True)
        ttk.Label(frame, textvariable=self.status, wraplength=780).pack(anchor="w", pady=(12, 0))
        self.refresh()
        self.tick()
        root.protocol("WM_DELETE_WINDOW", self.close)

    @staticmethod
    def field(parent, label, default, **options):
        ttk.Label(parent, text=label).pack(side="left")
        value = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=value, width=15, **options).pack(side="left", padx=(5, 10))
        return value

    def refresh(self):
        self.grid.delete(*self.grid.get_children())
        for index, slot in enumerate(self.slots):
            self.grid.insert("", "end", iid=str(index), values=(
                datetime.fromtimestamp(slot.start).strftime(TIME_FORMAT),
                datetime.fromtimestamp(slot.end).strftime(TIME_FORMAT),
                slot.kind, Path(slot.path).name,
            ))
        self.continuity.set(Path(self.fallback).name if self.fallback else "Selecciona un video de respaldo")

    def update_schedule(self, slots, fallback):
        try:
            save(SCHEDULE, slots, fallback)
        except OSError as exc:
            messagebox.showerror("Error al guardar", str(exc))
            return
        self.slots, self.fallback = slots, fallback
        self.snapshot = (tuple(slots), fallback)
        self.refresh()

    def choose_fallback(self):
        path = filedialog.askopenfilename(filetypes=[("Video MP4", "*.mp4")])
        if path:
            self.update_schedule(self.slots, str(Path(path).resolve()))

    def add(self):
        try:
            local = datetime.strptime(self.start.get(), TIME_FORMAT)
            start = local.timestamp()
            if datetime.fromtimestamp(start) != local:
                raise ValueError("La hora local indicada no existe debido al cambio de hora.")
            if local.replace(fold=1).timestamp() != start:
                raise ValueError("La hora local es ambigua debido al cambio de hora.")
        except ValueError as exc:
            messagebox.showerror("Fecha y hora", str(exc))
            return
        paths = filedialog.askopenfilenames(filetypes=[("Video MP4", "*.mp4")])
        if paths:
            self.add_button.configure(state="disabled")
            threading.Thread(target=self.inspect, args=(paths, start, self.kind.get()),
                             daemon=True).start()

    def inspect(self, paths, start, kind):
        try:
            media = []
            for name in sorted(paths, key=str.casefold):
                path = Path(name).resolve()
                if path.suffix.lower() != ".mp4":
                    raise ValueError(f"El archivo debe ser MP4: {path.name}")
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                    capture_output=True, text=True, check=True, timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                media.append((path, float(result.stdout.strip())))
            self.events.put(("block", (start, media, kind)))
        except FileNotFoundError:
            self.events.put(("error", "Instala FFmpeg y agrega ffprobe al PATH. Luego abre nuevamente Automata TV."))
        except (ValueError, subprocess.SubprocessError) as exc:
            self.events.put(("error", f"No se pudo medir la duración de los MP4. {exc}"))

    def remove(self):
        selection = {int(index) for index in self.grid.selection()}
        if selection:
            self.update_schedule([slot for index, slot in enumerate(self.slots)
                                  if index not in selection], self.fallback)

    def toggle(self):
        if self.worker and self.worker.is_alive():
            self.stop.set()
            self.control.configure(state="disabled", text="Deteniendo…")
            return
        if not self.fallback or not Path(self.fallback).is_file():
            messagebox.showwarning("Continuidad", "Selecciona un MP4 de continuidad disponible.")
            return
        if not self.scene.get().strip() or not self.source.get().strip():
            messagebox.showwarning("OBS", "Ingresa los nombres de la escena y de la fuente.")
            return
        self.stop.clear()
        obs = Obs(self.password.get(), self.scene.get().strip(), self.source.get().strip())
        self.worker = threading.Thread(target=run, args=(
            obs, self.stop, lambda: self.snapshot,
            lambda message: self.events.put(("status", message)),
        ), daemon=True)
        self.control.configure(text="Ceder control a OBS")
        self.status.set("Conectando con OBS…")
        self.worker.start()

    def tick(self):
        self.clock.set(datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))
        while not self.events.empty():
            event, payload = self.events.get_nowait()
            if event == "status":
                self.status.set(payload)
                continue
            self.add_button.configure(state="normal")
            if event == "error":
                messagebox.showerror("Importar MP4", payload)
                continue
            try:
                self.update_schedule(make_block(self.slots, *payload), self.fallback)
            except ValueError as exc:
                messagebox.showerror("Parrilla", str(exc))
        if self.worker and not self.worker.is_alive():
            self.worker = None
            self.control.configure(state="normal", text="Activar automatización")
            self.status.set("Control manual en OBS · última fuente conservada")
        self.root.after(200, self.tick)

    def close(self):
        if self.worker and self.worker.is_alive():
            self.stop.set()
            self.root.after(150, self.close)
        else:
            self.root.destroy()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[RotatingFileHandler(DATA / "emision.log", maxBytes=500_000,
                                                      backupCount=3, encoding="utf-8")])
    root = tk.Tk()
    try:
        Panel(root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        root.withdraw()
        messagebox.showerror("Automata TV", f"No se pudo abrir la parrilla guardada. {exc}")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
