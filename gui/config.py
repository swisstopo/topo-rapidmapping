"""
Kleine, defensiv geladene/geschriebene GUI-Einstellungen (Theme, letztes
Input-Verzeichnis). Ein einzelnes JSON-Objekt neben dem GUI-Skript.

Fehler beim Lesen/Schreiben sind hier bewusst nicht fatal — eine kaputte
oder fehlende Config-Datei darf das GUI niemals am Starten hindern.
"""

import json
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path(__file__).resolve().parent.parent / "gui_config.json"

_DEFAULTS: Dict[str, Any] = {
    "dark_mode": True,
    "last_input_dir": "",
    "last_product": "",
    "last_proxy_mode": "auto",
    "osgeo_python": "",
    "last_cog_compress": "JPEG",
    "last_cog_quality": 85,
}


def load() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return dict(_DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(_DEFAULTS)
        merged.update({k: v for k, v in data.items() if k in _DEFAULTS})
        return merged
    except Exception:
        return dict(_DEFAULTS)


def save(values: Dict[str, Any]) -> None:
    try:
        current = load()
        current.update({k: v for k, v in values.items() if k in _DEFAULTS})
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
