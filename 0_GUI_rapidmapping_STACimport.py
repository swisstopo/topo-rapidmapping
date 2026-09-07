#!/usr/bin/env python3
"""
Rapid Mapping Processor — GUI-Einstiegspunkt.

Dünner Wrapper um gui.app.RapidMappingApp. Die eigentliche Verarbeitung
läuft weiterhin über rapidmapping_processor.py/.exe, als Subprocess
gestartet von gui/runner.py — dieses Skript selbst braucht daher keine
GDAL/rasterio-Umgebung.

Usage:
    python 0_GUI_rapidmapping_STACimport.py
"""

from gui.app import main

if __name__ == "__main__":
    main()
