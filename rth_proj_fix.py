import os
import sys

# -----------------------------------------------------------------------
# PyInstaller Runtime-Hook: PROJ / GDAL Pfadkorrektur
# -----------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _base = sys._MEIPASS

    # --- 1: QGIS/OSGEO Pfade IMMER entfernen ---
    for _var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA", "GDAL_DRIVER_PATH", "GDAL_PLUGINS"):
        _val = os.environ.get(_var, "")
        if any(k in _val.upper() for k in ("QGIS", "OSGEO", "OSGEO4W")):
            os.environ.pop(_var, None)

    # --- 2: Bundled proj.db setzen ---
    for _candidate in (
        os.path.join(_base, "rasterio", "proj_data"),
        os.path.join(_base, "pyproj", "proj_dir"),
        os.path.join(_base, "proj_dir"),
        os.path.join(_base, "share", "proj"),
    ):
        if os.path.isfile(os.path.join(_candidate, "proj.db")):
            os.environ["PROJ_LIB"]  = _candidate
            os.environ["PROJ_DATA"] = _candidate
            break

    # --- 3: Bundled gdal-data setzen ---
    for _candidate in (
        os.path.join(_base, "rasterio", "gdal_data"),
        os.path.join(_base, "gdal-data"),
        os.path.join(_base, "osgeo", "gdal_data"),
    ):
        if os.path.isdir(_candidate):
            os.environ.setdefault("GDAL_DATA", _candidate)
            break

    # --- 4: PROJ/GDAL Settings optimieren ---
    os.environ.setdefault("PROJ_NETWORK", "OFF")
    os.environ.setdefault("GTIFF_SRS_SOURCE", "EPSG") # Unterdrueckt die nervige EPSG:2056 Warnung
