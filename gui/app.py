"""
RapidMappingApp — Hauptfenster des GUI.

Formular (Umgebung, Input-Verzeichnis, Produkttyp, Zeitstempel, Upload,
Debug, Netzwerk-Modus) → baut daraus dieselben CLI-Flags, die
rapidmapping_processor.py schon unterstützt, und führt sie via
gui.runner.ProcessRunner als Subprocess aus. Live-Log + echter
Abbrechen-Button. Validierung nutzt dieselben Funktionen wie die CLI
selbst (configuration.py, utilities/file_handler.py) — kein eigenes,
potenziell abweichendes Regelwerk.
"""

import os
import queue
import shutil
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from configuration import normalize_cli_timestamp, validate_timestamp  # noqa: E402
from utilities.file_handler import validate_directory  # noqa: E402
from utilities.proxy_handler import get_configured_proxy_names  # noqa: E402

from gui import config as gui_config  # noqa: E402
from gui.runner import ProcessRunner, detect_osgeo_python  # noqa: E402
from gui.theme import DARK, LIGHT, apply_theme, set_titlebar_dark  # noqa: E402

# (Anzeige-Label, CLI-Wert, Zeitstempel-Format: "date" YYYY-MM-DD oder "timestamp" YYYY-MM-DDthhmmss[cc])
PRODUCTS = [
    ("EBN — Einzelbilder Nadir",              "ebn",       "date"),
    ("EBO — Einzelbilder Oblique",            "ebo",       "date"),
    ("QDOP RGB — Quickmosaik RGB",            "qdop-rgb",  "timestamp"),
    ("QDOP NRG — Quickmosaik NRG",            "qdop-nrg",  "timestamp"),
    ("QDOP DMC4 — 4-Kanal Bildstreifen",      "qdop-dmc4", "timestamp"),
]

DONE_MARKERS_OK = ("VERARBEITUNG ERFOLGREICH",)
DONE_MARKERS_FAIL = ("VERARBEITUNG MIT FEHLERN",)


class RapidMappingApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Rapid Mapping — STAC Import Tool")
        self.geometry("880x720")
        self.minsize(760, 600)

        self._settings = gui_config.load()
        self._dark = bool(self._settings.get("dark_mode", True))

        self.runner: ProcessRunner = None
        self._awaiting_done = False
        self._progress_active = False
        self._progress_start_index = None

        self.style = ttk.Style(self)

        self._build_ui()
        self._apply_theme()
        self._restore_settings()
        self._revalidate()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self):
        header = tk.Frame(self, height=48)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        self._header = header

        self._title_label = tk.Label(
            header, text="Rapid Mapping — STAC Import Tool", font=("Segoe UI", 12, "bold")
        )
        self._title_label.pack(side="left", padx=14)

        self._theme_btn = ttk.Button(header, text="Dunkel/Hell", command=self._toggle_theme, width=12)
        self._theme_btn.pack(side="right", padx=10, pady=8)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        form = ttk.Frame(body)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        row = 0

        # OSGeo4W - Python Interpreter (python3.exe einer QGIS/OSGeo4W-Installation)
        # — nur relevant wenn GDAL-Tools nicht schon über eine aktive OSGeo4W-Shell
        # auf dem PATH liegen; wird sonst als "bereits verfügbar" markiert.
        ttk.Label(form, text="OSGeo4W - Python Interpreter:").grid(row=row, column=0, sticky="w", pady=6)
        interp_frame = ttk.Frame(form)
        interp_frame.grid(row=row, column=1, sticky="ew")
        interp_frame.columnconfigure(0, weight=1)
        self.interp_var = tk.StringVar()
        self.interp_entry = ttk.Entry(interp_frame, textvariable=self.interp_var)
        self.interp_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(interp_frame, text="Durchsuchen…", command=self._browse_interpreter).grid(
            row=0, column=1, padx=(8, 0)
        )
        row += 1
        self.interp_hint = ttk.Label(form, text="", foreground=self._hint_color())
        self.interp_hint.grid(row=row, column=1, sticky="w")
        row += 1

        # Umgebung
        ttk.Label(form, text="Umgebung:").grid(row=row, column=0, sticky="w", pady=6)
        env_frame = ttk.Frame(form)
        env_frame.grid(row=row, column=1, sticky="w")
        self.env_var = tk.StringVar(value="INT")
        ttk.Radiobutton(env_frame, text="INT (Test)", variable=self.env_var, value="INT").pack(side="left")
        ttk.Radiobutton(env_frame, text="PROD (produktiv)", variable=self.env_var, value="PROD").pack(
            side="left", padx=(14, 0)
        )
        row += 1

        # Input-Verzeichnis
        ttk.Label(form, text="Input-Verzeichnis:").grid(row=row, column=0, sticky="w", pady=6)
        dir_frame = ttk.Frame(form)
        dir_frame.grid(row=row, column=1, sticky="ew")
        dir_frame.columnconfigure(0, weight=1)
        self.input_dir_var = tk.StringVar()
        self.dir_entry = ttk.Entry(dir_frame, textvariable=self.input_dir_var)
        self.dir_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(dir_frame, text="Durchsuchen…", command=self._browse_input_dir).grid(
            row=0, column=1, padx=(8, 0)
        )
        row += 1
        self.dir_hint = ttk.Label(form, text="", foreground=self._hint_color())
        self.dir_hint.grid(row=row, column=1, sticky="w")
        row += 1

        # Produkttyp
        ttk.Label(form, text="Produkttyp:").grid(row=row, column=0, sticky="w", pady=6)
        self.product_var = tk.StringVar()
        self.product_combo = ttk.Combobox(
            form, textvariable=self.product_var, state="readonly",
            values=[label for label, _, _ in PRODUCTS], width=40
        )
        self.product_combo.grid(row=row, column=1, sticky="w")
        row += 1

        # Zeitstempel/Datum
        self.timestamp_label = ttk.Label(form, text="Datum:")
        self.timestamp_label.grid(row=row, column=0, sticky="w", pady=6)
        self.timestamp_var = tk.StringVar()
        self.ts_entry = ttk.Entry(form, textvariable=self.timestamp_var)
        self.ts_entry.grid(row=row, column=1, sticky="w")
        row += 1
        self.ts_hint = ttk.Label(form, text="", foreground=self._hint_color())
        self.ts_hint.grid(row=row, column=1, sticky="w")
        row += 1

        # STAC-Upload / Debug
        opts_frame = ttk.Frame(form)
        opts_frame.grid(row=row, column=1, sticky="w", pady=6)
        self.upload_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts_frame, text="STAC-Upload aktiv", variable=self.upload_var).pack(side="left")
        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_frame, text="Debug-Modus (sequentiell)", variable=self.debug_var).pack(
            side="left", padx=(20, 0)
        )
        row += 1

        # Netzwerk-Modus
        ttk.Label(form, text="Netzwerk-Modus:").grid(row=row, column=0, sticky="w", pady=6)
        proxy_values = ["auto", "direct", "system"] + get_configured_proxy_names()
        self.proxy_var = tk.StringVar(value="auto")
        self.proxy_combo = ttk.Combobox(
            form, textvariable=self.proxy_var, state="readonly", values=proxy_values, width=20
        )
        self.proxy_combo.grid(row=row, column=1, sticky="w")
        row += 1

        self.creds_hint = ttk.Label(form, text="", foreground=self._hint_color())
        self.creds_hint.grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Separator(body).pack(fill="x", pady=12)

        # Zusammenfassung
        self.summary_label = ttk.Label(body, text="", justify="left")
        self.summary_label.pack(fill="x", pady=(0, 10))

        # Start / Abbrechen
        btn_frame = ttk.Frame(body)
        btn_frame.pack(fill="x")
        self.start_btn = ttk.Button(
            btn_frame, text="▶  Verarbeitung starten", style="Accent.TButton",
            command=self._on_start_clicked
        )
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(
            btn_frame, text="■  Abbrechen", command=self._on_cancel_clicked, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=(10, 0))
        ttk.Button(btn_frame, text="Projektordner öffnen", command=self._open_project_folder).pack(
            side="right"
        )

        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 6))

        # Log
        log_frame = ttk.LabelFrame(body, text="Log")
        log_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.log = scrolledtext.ScrolledText(
            log_frame, height=14, font=("Consolas", 9), wrap="word", state="disabled"
        )
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        # Live-Validierung an Änderungen koppeln
        self.input_dir_var.trace_add("write", self._revalidate)
        self.timestamp_var.trace_add("write", self._revalidate)
        self.upload_var.trace_add("write", self._revalidate)
        self.interp_var.trace_add("write", self._revalidate)
        self.product_combo.bind("<<ComboboxSelected>>", self._on_product_changed)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _hint_color(self) -> str:
        return (DARK if self._dark else LIGHT)["hint"]

    def _ok_color(self) -> str:
        return (DARK if self._dark else LIGHT)["ok"]

    def _set_hint(self, label: ttk.Label, text: str, ok: bool = False):
        """Setzt Hinweistext + Farbe: grün wenn ok=True (Pflichtfeld erfüllt),
        sonst amber (Hinweis/ungültig)."""
        label.configure(text=text, foreground=self._ok_color() if ok else self._hint_color())

    def _apply_theme(self):
        T = apply_theme(self, self.style, self._dark)
        self._header.configure(bg=T["hdr_bg"])
        self._title_label.configure(bg=T["hdr_bg"], fg=T["hdr_fg"])
        self.log.configure(bg=T["log_bg"], fg=T["log_fg"], insertbackground=T["log_fg"])
        self.log.tag_configure("err", foreground=T["err"])
        self.log.tag_configure("warn", foreground=T["hint"])
        self.log.tag_configure("ok", foreground=T["ok"])
        try:
            self.log.vbar.configure(
                background=T["accent"], activebackground=T["accent"],
                troughcolor=T["panel"], highlightthickness=0, bd=0, relief="flat",
            )
        except Exception:
            pass
        set_titlebar_dark(self, self._dark)
        # DWM übernimmt die Titelleisten-Farbe manchmal erst, nachdem das
        # Fenster tatsächlich sichtbar ist (beim ersten Start vor mainloop()
        # noch nicht der Fall) — daher ein verzögerter zweiter Versuch.
        self.after(200, lambda: set_titlebar_dark(self, self._dark))
        # Hinweistext-Farben (amber/grün) werden von _revalidate() gesetzt,
        # das nach jedem _apply_theme()-Aufruf ohnehin folgt.

    def _toggle_theme(self):
        self._dark = not self._dark
        self._apply_theme()
        self._revalidate()
        gui_config.save({"dark_mode": self._dark})

    # ------------------------------------------------------------------
    # Einstellungen wiederherstellen
    # ------------------------------------------------------------------
    def _restore_settings(self):
        self.interp_var.set(detect_osgeo_python(self._settings.get("osgeo_python", "")))

        last_dir = self._settings.get("last_input_dir", "")
        if last_dir:
            self.input_dir_var.set(last_dir)

        last_product = self._settings.get("last_product", "")
        labels = [label for label, cli, _ in PRODUCTS if cli == last_product]
        self.product_combo.set(labels[0] if labels else PRODUCTS[0][0])
        self._on_product_changed()

        last_proxy = self._settings.get("last_proxy_mode", "auto")
        if last_proxy in self.proxy_combo["values"]:
            self.proxy_var.set(last_proxy)

    def _current_product(self):
        idx = self.product_combo.current()
        if idx < 0:
            return PRODUCTS[0]
        return PRODUCTS[idx]

    def _on_product_changed(self, *_):
        _, _, fmt = self._current_product()
        if fmt == "date":
            self.timestamp_label.configure(text="Datum:")
            self.ts_hint.configure(text='Format: JJJJ-MM-TT  (z.B. 2025-09-03)')
        else:
            self.timestamp_label.configure(text="Zeitstempel:")
            self.ts_hint.configure(text='Format: JJJJ-MM-TTthhmmss  (z.B. 2024-07-15t143000)')
        self._revalidate()

    # ------------------------------------------------------------------
    # Validierung — nutzt dieselben Funktionen wie die CLI
    # ------------------------------------------------------------------
    def _validate_input_dir(self) -> bool:
        text = self.input_dir_var.get().strip()
        if not text:
            return False
        try:
            validate_directory(text)
            return True
        except Exception:
            return False

    def _validate_timestamp(self) -> bool:
        text = self.timestamp_var.get().strip()
        if not text:
            return False
        _, _, fmt = self._current_product()
        if fmt == "date":
            try:
                datetime.strptime(text, "%Y-%m-%d")
                return True
            except ValueError:
                return False
        norm = normalize_cli_timestamp(text.lower())
        return validate_timestamp(norm)

    def _credentials_available(self) -> bool:
        if os.environ.get("STAC_USERNAME") and os.environ.get("STAC_PASSWORD"):
            return True
        return (REPO_ROOT / "secrets" / "stac_credentials.json").exists()

    def _gdal_on_path(self) -> bool:
        """True wenn gdalinfo bereits über das geerbte PATH auffindbar ist
        (z.B. weil aus einer aktiven OSGeo4W-Shell gestartet) — dann ist
        das Interpreter-Feld nur noch informativ, kein Pflichtfeld."""
        return shutil.which("gdalinfo") is not None

    def _gdal_available(self) -> bool:
        if self._gdal_on_path():
            return True
        path = self.interp_var.get().strip()
        if not path:
            return False
        p = Path(path)
        return p.is_file() and (p.parent / "gdalinfo.exe").is_file()

    def _revalidate(self, *_):
        ok_dir = self._validate_input_dir()
        ok_ts = self._validate_timestamp()
        ok_creds = (not self.upload_var.get()) or self._credentials_available()
        ok_gdal = self._gdal_available()

        self.dir_entry.configure(style="TEntry" if ok_dir else "Invalid.TEntry")
        self.ts_entry.configure(style="TEntry" if ok_ts else "Invalid.TEntry")
        self.interp_entry.configure(style="TEntry" if ok_gdal else "Invalid.TEntry")

        if not self.input_dir_var.get().strip():
            self._set_hint(self.dir_hint, "")
        elif ok_dir:
            self._set_hint(self.dir_hint, "✓ Verzeichnis gefunden", ok=True)
        else:
            self._set_hint(self.dir_hint, "✗ Verzeichnis existiert nicht")

        _, _, fmt = self._current_product()
        format_hint = (
            'Format: JJJJ-MM-TT  (z.B. 2025-09-03)' if fmt == "date"
            else 'Format: JJJJ-MM-TTthhmmss  (z.B. 2024-07-15t143000)'
        )
        if not self.timestamp_var.get().strip():
            self._set_hint(self.ts_hint, format_hint)
        elif ok_ts:
            self._set_hint(self.ts_hint, "✓ Format gültig", ok=True)
        else:
            self._set_hint(self.ts_hint, "✗ Ungültiges Format für den gewählten Produkttyp")

        if self._gdal_on_path():
            self._set_hint(
                self.interp_hint,
                "✓ GDAL-Tools bereits über PATH verfügbar (Feld optional)", ok=True
            )
        elif ok_gdal:
            self._set_hint(self.interp_hint, "✓ OSGeo4W - Python Interpreter gefunden", ok=True)
        else:
            self._set_hint(
                self.interp_hint,
                "✗ python3.exe einer QGIS/OSGeo4W-Installation wählen "
                "(gdalinfo.exe muss im selben Ordner liegen)"
            )

        if not self.upload_var.get():
            self._set_hint(self.creds_hint, "")
        elif ok_creds:
            self._set_hint(self.creds_hint, "✓ STAC-Credentials gefunden", ok=True)
        else:
            self._set_hint(
                self.creds_hint,
                "✗ Keine STAC-Credentials gefunden (secrets/stac_credentials.json "
                "oder STAC_USERNAME/STAC_PASSWORD)"
            )

        self._update_summary()

        all_ok = ok_dir and ok_ts and ok_creds and ok_gdal and not self._awaiting_done
        self.start_btn.configure(state="normal" if all_ok else "disabled")

    def _update_summary(self):
        label, _, _ = self._current_product()
        self.summary_label.configure(text=(
            f"Umgebung: {self.env_var.get()}   |   Produkt: {label}   |   "
            f"Upload: {'aktiv' if self.upload_var.get() else 'aus (→ ./output/)'}   |   "
            f"Debug: {'an' if self.debug_var.get() else 'aus'}"
        ))

    # ------------------------------------------------------------------
    # Verzeichnis wählen
    # ------------------------------------------------------------------
    def _browse_input_dir(self):
        initial = self.input_dir_var.get().strip() or str(Path.home())
        chosen = filedialog.askdirectory(initialdir=initial, title="Input-Verzeichnis wählen")
        if chosen:
            self.input_dir_var.set(chosen)

    def _browse_interpreter(self):
        current = self.interp_var.get().strip()
        initial = str(Path(current).parent) if current and Path(current).exists() else "C:/Program Files"
        chosen = filedialog.askopenfilename(
            title="python3.exe der QGIS/OSGeo4W-Installation wählen",
            initialdir=initial,
            filetypes=[("python3.exe", "python3.exe"), ("Alle Dateien", "*.*")],
        )
        if chosen:
            self.interp_var.set(chosen)
            gui_config.save({"osgeo_python": chosen})

    def _open_project_folder(self):
        try:
            os.startfile(str(REPO_ROOT))
        except Exception:
            messagebox.showinfo("Projektordner", str(REPO_ROOT))

    # ------------------------------------------------------------------
    # Start / Abbrechen
    # ------------------------------------------------------------------
    def _build_cli_args(self) -> list:
        _, product_cli, _ = self._current_product()
        args = [
            "--product", product_cli,
            "--input", self.input_dir_var.get().strip(),
            "--timestamp", self.timestamp_var.get().strip(),
            "--upload", "True" if self.upload_var.get() else "False",
            "--proxy", self.proxy_var.get().strip() or "auto",
        ]
        if self.env_var.get() == "PROD":
            args.append("--prod")
        if self.debug_var.get():
            args.append("--debug")
        return args

    def _on_start_clicked(self):
        label, _, _ = self._current_product()
        summary = (
            f"Umgebung:      {self.env_var.get()}\n"
            f"Verzeichnis:   {self.input_dir_var.get().strip()}\n"
            f"Produkttyp:    {label}\n"
            f"Zeitstempel:   {self.timestamp_var.get().strip()}\n"
            f"STAC-Upload:   {'aktiv' if self.upload_var.get() else 'AUS (nur lokal in ./output/)'}\n"
        )
        if not messagebox.askyesno("Verarbeitung starten?", summary + "\nJetzt starten?"):
            return

        self._clear_log()
        self._append_log_line("▶ Starte Verarbeitung…")

        gui_config.save({
            "last_input_dir": self.input_dir_var.get().strip(),
            "last_product": self._current_product()[1],
            "last_proxy_mode": self.proxy_var.get().strip(),
            "osgeo_python": self.interp_var.get().strip(),
        })

        self.runner = ProcessRunner()
        self._awaiting_done = True
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.start(12)

        try:
            self.runner.start(
                self._build_cli_args(),
                python_path=self.interp_var.get().strip() or None,
            )
        except Exception as e:
            self._append_log_line(f"✗ Konnte Prozess nicht starten: {e}", tag="err")
            self._on_run_done(1)
            return

        self.after(80, self._poll_runner)

    def _on_cancel_clicked(self):
        if not self.runner or not self.runner.is_running:
            return
        if messagebox.askyesno("Abbrechen?", "Laufenden Prozess wirklich abbrechen?"):
            self._append_log_line("⏹ Abbruch angefordert…", tag="warn")
            self.runner.cancel()

    def _poll_runner(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self.runner.events.get_nowait()
                if kind == "line":
                    self._handle_line(payload)
                elif kind == "progress":
                    self._update_progress_line(payload)
                elif kind == "done":
                    self._on_run_done(payload)
        except queue.Empty:
            pass

        if self._awaiting_done:
            self.after(80, self._poll_runner)

    def _on_run_done(self, returncode: int):
        self._awaiting_done = False
        self.progress.stop()
        self.cancel_btn.configure(state="disabled")

        if returncode == 0:
            self._append_log_line("✓ Verarbeitung erfolgreich abgeschlossen.", tag="ok")
        elif returncode == 130:
            self._append_log_line("⏹ Verarbeitung abgebrochen.", tag="warn")
        else:
            self._append_log_line(f"✗ Verarbeitung mit Fehlern beendet (Exit-Code {returncode}).", tag="err")

        self._revalidate()

    # ------------------------------------------------------------------
    # Log-Widget: \r-Fortschritt ersetzt die letzte Zeile, \n hängt an
    # ------------------------------------------------------------------
    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._progress_active = False
        self._progress_start_index = None

    def _classify(self, text: str):
        if text.startswith("ERROR") or text.startswith("✗"):
            return "err"
        if text.startswith("WARNING") or text.startswith("⏹"):
            return "warn"
        if "ERFOLGREICH" in text or text.startswith("✓"):
            return "ok"
        return None

    def _handle_line(self, text: str, tag: str = None):
        self.log.configure(state="normal")
        if self._progress_active:
            self.log.delete(self._progress_start_index, "end")
            self._progress_active = False
            self._progress_start_index = None
        tag = tag or self._classify(text)
        if tag:
            self.log.insert("end", text + "\n", tag)
        else:
            self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _append_log_line(self, text: str, tag: str = None):
        self._handle_line(text, tag=tag)

    def _update_progress_line(self, text: str):
        self.log.configure(state="normal")
        if self._progress_active:
            self.log.delete(self._progress_start_index, "end")
        else:
            self._progress_start_index = self.log.index("end-1c")
            self._progress_active = True
        self.log.insert(self._progress_start_index, text)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------
    def _on_close(self):
        if self.runner and self.runner.is_running:
            if not messagebox.askyesno(
                "Beenden?", "Ein Import läuft noch — trotzdem beenden und abbrechen?"
            ):
                return
            self.runner.cancel()
        self.destroy()


def main():
    app = RapidMappingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
