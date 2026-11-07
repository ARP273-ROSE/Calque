"""Calque — cloner un disque (système Windows compris) sur un disque plus grand."""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    __version__ = "0.0.0"
