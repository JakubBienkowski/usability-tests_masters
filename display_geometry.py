from __future__ import annotations

import ctypes
import os
from typing import Any


def enable_dpi_awareness() -> str:
    """Make every Windows input and UI API use physical screen pixels."""
    if os.name != "nt":
        return "not_windows"
    user32 = ctypes.windll.user32
    try:
        # PER_MONITOR_AWARE_V2. It must be set before creating a window.
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per_monitor_v2"
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per_monitor"
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except Exception:
        return "unavailable"


DPI_AWARENESS = enable_dpi_awareness()


def primary_screen_geometry() -> dict[str, Any]:
    configured_width = os.getenv("UX_SCREEN_WIDTH")
    configured_height = os.getenv("UX_SCREEN_HEIGHT")
    if configured_width and configured_height:
        return {
            "width": int(configured_width),
            "height": int(configured_height),
            "origin_x": 0,
            "origin_y": 0,
            "dpi_awareness": DPI_AWARENESS,
            "source": "environment",
        }
    if os.name == "nt":
        user32 = ctypes.windll.user32
        return {
            "width": int(user32.GetSystemMetrics(0)),
            "height": int(user32.GetSystemMetrics(1)),
            "origin_x": 0,
            "origin_y": 0,
            "dpi_awareness": DPI_AWARENESS,
            "source": "win32_physical",
        }
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
        root.destroy()
        return {
            "width": width,
            "height": height,
            "origin_x": 0,
            "origin_y": 0,
            "dpi_awareness": DPI_AWARENESS,
            "source": "tk",
        }
    except Exception:
        return {
            "width": 1920,
            "height": 1080,
            "origin_x": 0,
            "origin_y": 0,
            "dpi_awareness": DPI_AWARENESS,
            "source": "fallback",
        }
