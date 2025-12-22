import sys
import os

print("=== Python Environment Diagnostics ===\n")
print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}\n")

print("=== sys.path (module search paths) ===")
for i, path in enumerate(sys.path):
    marker = " ⚠️  QGIS PATH!" if "QGIS" in path.upper() else ""
    print(f"{i}: {path}{marker}")

print("\n=== Environment Variables ===")
for var in ['PATH', 'PYTHONPATH', 'PYTHONHOME', 'QGIS_PREFIX_PATH']:
    value = os.environ.get(var, 'NOT SET')
    print(f"{var}: {value[:100]}..." if len(value) > 100 else f"{var}: {value}")

print("\n=== Testing sqlite3 import ===")
try:
    import sqlite3
    print(f"✓ sqlite3 loaded from: {sqlite3.__file__}")
    print(f"  SQLite version: {sqlite3.sqlite_version}")
except ImportError as e:
    print(f"✗ sqlite3 failed: {e}")

print("\n=== Testing pystac_client import ===")
try:
    import pystac_client
    print(f"✓ pystac_client loaded successfully")
    print(f"  Location: {pystac_client.__file__}")
except ImportError as e:
    print(f"✗ pystac_client failed: {e}")