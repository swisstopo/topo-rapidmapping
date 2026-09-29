"""
ProcessRunner — startet rapidmapping_processor (.py oder .exe) als Subprocess
und streamt dessen Ausgabe live in eine Queue, \r/\n-bewusst.

Warum nicht zeilenweise lesen (proc.stdout readline/for-line-in):
main_multipart_upload_via_api.py und rapidmapping_processor.py selbst
schreiben Fortschrittsbalken mit "\r...\r...\r...100%\n" — bei zeilenweisem
Lesen kommt das erst als EIN riesiger Block an, sobald die 100%-Zeile mit
"\n" endet. Hier wird stattdessen roh gelesen und selbst in "neue Zeile"
(\n) vs. "Zeile ersetzen" (\r) unterschieden, damit Fortschrittsbalken im
GUI-Log auch wirklich live und an Ort und Stelle aktualisiert werden.
"""

import glob
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_EXE = REPO_ROOT / "rapidmapping_processor.exe"
CLI_PY = REPO_ROOT / "rapidmapping_processor.py"

# Bekannte Installationspfade für QGIS/OSGeo4W — deren "bin"-Ordner enthält
# sowohl python3.exe als auch die GDAL-Kommandozeilentools (gdalinfo,
# gdal_translate, ...), die rapidmapping_processor.py per subprocess aufruft.
_KNOWN_OSGEO_PYTHONS = [
    r"C:\Program Files\QGIS 3.42.1\bin\python3.exe",
    r"C:\OSGeo4W\bin\python3.exe",
    r"C:\OSGeo4W64\bin\python3.exe",
]


def detect_osgeo_python(saved_path: str = None) -> str:
    """
    Ermittelt eine Python-Installation, deren "bin"-Ordner die GDAL-Tools
    enthält — nötig wenn weder eine gebaute .exe noch ein aktiviertes
    .venv/OSGeo4W-Shell vorliegt.

    Priorität:
      1. Gespeicherter Pfad (z.B. aus gui_config.json), falls die Datei noch existiert
      2. Aktuell laufende Python, falls "rasterio" dort bereits installiert ist
         (z.B. weil aus einem aktivierten .venv gestartet)
      3. Bekannte QGIS-/OSGeo4W-Installationspfade (inkl. Versions-Scan)

    Liefert bei Misserfolg sys.executable zurück — kein Fehler, nur ein
    Startpunkt für die manuelle Auswahl im GUI.
    """
    if saved_path and Path(saved_path).is_file():
        return saved_path

    try:
        import importlib.util
        if importlib.util.find_spec("rasterio") is not None:
            return sys.executable
    except Exception:
        pass

    candidates = list(_KNOWN_OSGEO_PYTHONS)
    for pattern in (
        r"C:\Program Files\QGIS*\bin\python3.exe",
        r"C:\Program Files (x86)\QGIS*\bin\python3.exe",
    ):
        candidates.extend(sorted(glob.glob(pattern), reverse=True))

    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate

    return sys.executable


def resolve_cli_command(python_path: str = None) -> list:
    """
    Wählt die auszuführende CLI: bevorzugt die gebaute .exe (keine
    Python-Umgebung nötig), fällt sonst auf "<python_path> rapidmapping_processor.py"
    zurück — mit `python_path` = frei wählbarer Interpreter (siehe
    detect_osgeo_python) oder sys.executable als Default.
    """
    if CLI_EXE.exists():
        return [str(CLI_EXE)]
    return [python_path or sys.executable, str(CLI_PY)]


class ProcessRunner:
    """
    Führt einen einzelnen rapidmapping_processor-Lauf in einem Hintergrund-
    Thread aus und liefert Events über eine Queue:

        ("line", text)      — eine vollständige, neue Zeile
        ("progress", text)  — Ersetzt die zuletzt ausgegebene Zeile (\r-Update)
        ("done", returncode) — Prozess beendet (0=Erfolg, 1=Fehler, 130=Abbruch)

    Aufrufer pollt die Queue z.B. via root.after(...) — niemals aus dem
    Hintergrund-Thread direkt auf Tk-Widgets zugreifen.
    """

    def __init__(self):
        self.events: "queue.Queue" = queue.Queue()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    def start(self, args: list, python_path: str = None) -> None:
        """
        Startet den Subprocess mit den gegebenen CLI-Argumenten (ohne
        Programmname).

        python_path: Pfad zu einer python3.exe mit GDAL-Tools im selben
            "bin"-Ordner (z.B. QGIS/OSGeo4W). Wird nur als Interpreter
            verwendet, falls keine rapidmapping_processor.exe existiert;
            in jedem Fall wird der zugehörige "bin"-Ordner vorn ins PATH
            des Subprozesses gehängt, damit gdalinfo/gdal_translate/...
            auch ohne aktive OSGeo4W-Shell gefunden werden.
        """
        if self._thread and self._thread.is_alive():
            raise RuntimeError("ProcessRunner läuft bereits")

        cmd = resolve_cli_command(python_path) + args
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run, args=(cmd, python_path), daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        """Bricht den laufenden Prozess ab (terminate, nach kurzer Frist kill)."""
        self._cancelled = True
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self, cmd: list, python_path: str = None) -> None:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        if python_path:
            bin_dir = str(Path(python_path).parent)
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(REPO_ROOT),
                env=env,
                bufsize=0,
            )
        except Exception as e:
            self.events.put(("line", f"✗ Konnte Prozess nicht starten: {e}"))
            self.events.put(("done", 1))
            return

        self._stream_output(self._proc.stdout)

        returncode = self._proc.wait()
        if self._cancelled and returncode not in (0,):
            returncode = 130
        self.events.put(("done", returncode))

    def _stream_output(self, pipe) -> None:
        """
        Liest rohe Bytes und zerlegt sie in "neue Zeile" (\n oder \r\n) vs.
        "Zeile ersetzen" (bare \r, ohne folgendes \n).

        Wichtig: Python schreibt auf Windows \n standardmäßig als \r\n —
        ein naiver "jedes \r ist ein Fortschritts-Update"-Parser würde also
        JEDE normale Log-Zeile fälschlich als Fortschrittsbalken behandeln.
        Deshalb hier explizites 1-Byte-Lookahead nach \r, um CRLF von einem
        echten bare-\r-Fortschritts-Update zu unterscheiden.
        """
        buf = bytearray()
        pushback = None

        def next_byte():
            nonlocal pushback
            if pushback is not None:
                b = pushback
                pushback = None
                return b
            chunk = pipe.read(1)
            return chunk[0] if chunk else None

        while True:
            b = next_byte()
            if b is None:
                break
            if b == 0x0A:  # \n ohne vorangehendes \r
                self.events.put(("line", buf.decode("utf-8", errors="replace")))
                buf.clear()
            elif b == 0x0D:  # \r — nächstes Byte entscheidet CRLF vs. bare CR
                text = buf.decode("utf-8", errors="replace")
                buf.clear()
                nxt = next_byte()
                if nxt is None:
                    self.events.put(("progress", text))
                    break
                if nxt == 0x0A:
                    self.events.put(("line", text))
                else:
                    self.events.put(("progress", text))
                    pushback = nxt
            else:
                buf.append(b)

        if buf:
            self.events.put(("line", buf.decode("utf-8", errors="replace")))
        pipe.close()
