"""
Gemeinsame GDAL-Hilfsfunktionen.

Bündelt die Performance-Flags und die "-progress"-Fähigkeitsprüfung, die
zuvor an mehreren Stellen (rapidmapping_processor.py, photo_processor.py,
mosaic_processor.py) unabhängig voneinander hart getippt bzw. neu
implementiert waren.
"""

import subprocess

# Performance flags injected into every GDAL command that processes pixels.
# --config NUM_THREADS ALL_CPUS  → multi-thread COG tile/overview generation
# --config GDAL_CACHEMAX 512     → 512 MB block cache (avoids repeated disk reads)
GDAL_PERF_FLAGS = [
    "--config", "NUM_THREADS", "ALL_CPUS",
    "--config", "GDAL_CACHEMAX", "512",
]

_GDAL_PROGRESS_SUPPORTED: dict = {}  # cache per executable, e.g. {'gdal_translate': True}


def supports_progress(exe: str) -> bool:
    """Probe once whether this GDAL build accepts -progress for the given tool."""
    if exe not in _GDAL_PROGRESS_SUPPORTED:
        r = subprocess.run([exe, "--help"], capture_output=True, text=True)
        _GDAL_PROGRESS_SUPPORTED[exe] = "-progress" in r.stdout or "-progress" in r.stderr
    return _GDAL_PROGRESS_SUPPORTED[exe]
