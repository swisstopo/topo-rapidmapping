"""
Farben (Hell/Dunkel) und ttk-Styling für das Rapid-Mapping-GUI.

Ein einziger Satz Farbdicts + eine einzige apply_theme()-Funktion, die
sowohl ttk-Widgets (via Style) als auch rohe tk-Widgets (via .configure())
einfärbt. Wird von gui/app.py aufgerufen; nichts hier ist app-spezifisch.
"""

import tkinter as tk
from tkinter import ttk

LIGHT = {
    "root":      "#f0f0f0",
    "panel":     "#f5f5f5",
    "input":     "#ffffff",
    "fg":        "#1a1a1a",
    "fg_dim":    "#666666",
    "accent":    "#0063b1",
    "hdr_bg":    "#1a3a5c",
    "hdr_fg":    "#ffffff",
    "btn":       "#e1e1e1",
    "btn_hover": "#c8c8c8",
    "log_bg":    "#1e1e1e",
    "log_fg":    "#d4d4d4",
    "sep":       "#c0c0c0",
    "ok":        "#2e7d32",
    "err":       "#c62828",
    "hint":      "#8a6f2e",
}

DARK = {
    "root":      "#1e1e1e",
    "panel":     "#252526",
    "input":     "#3c3c3c",
    "fg":        "#cccccc",
    "fg_dim":    "#7a7a7a",
    "accent":    "#4fc3f7",
    "hdr_bg":    "#1a1a1a",
    "hdr_fg":    "#cccccc",
    "btn":       "#3c3c3c",
    "btn_hover": "#505050",
    "log_bg":    "#1e1e1e",
    "log_fg":    "#d4d4d4",
    "sep":       "#3c3c3c",
    "ok":        "#66bb6a",
    "err":       "#ef5350",
    "hint":      "#c9a84c",
}


def apply_theme(root: tk.Tk, style: ttk.Style, dark: bool) -> dict:
    """
    Wendet Hell/Dunkel-Theme auf root + ttk-Style an.

    Deckt nur ttk-Widgets ab (Style erreicht keine rohen tk-Widgets wie
    Text/Listbox). Der Aufrufer färbt eigene rohe tk-Widgets selbst ein,
    mit dem hier zurückgegebenen Farbdict.

    Args:
        root:  Hauptfenster (für .configure(bg=...))
        style: ttk.Style-Instanz
        dark:  True = Dark-Theme, False = Light-Theme

    Returns:
        Das aktive Farbdict (LIGHT oder DARK).
    """
    T = DARK if dark else LIGHT

    style.theme_use("clam")

    root.configure(bg=T["root"])

    style.configure("TFrame", background=T["panel"])
    style.configure("TLabel", background=T["panel"], foreground=T["fg"])
    style.configure(
        "TButton", background=T["btn"], foreground=T["fg"],
        borderwidth=1, focusthickness=0, padding=6
    )
    style.map(
        "TButton",
        background=[("active", T["btn_hover"]), ("disabled", T["panel"])],
        foreground=[("disabled", T["fg_dim"])],
    )
    style.configure(
        "Accent.TButton", background=T["accent"], foreground=T["hdr_fg"], padding=8
    )
    style.map("Accent.TButton", background=[("active", T["accent"]), ("disabled", T["btn"])])

    style.configure("TRadiobutton", background=T["panel"], foreground=T["fg"])
    style.map("TRadiobutton", background=[("active", T["panel"])])

    style.configure("TCheckbutton", background=T["panel"], foreground=T["fg"])
    style.map("TCheckbutton", background=[("active", T["panel"])])

    style.configure(
        "TEntry", fieldbackground=T["input"], foreground=T["fg"],
        insertcolor=T["fg"], bordercolor=T["sep"]
    )
    style.configure(
        "Invalid.TEntry", fieldbackground=T["input"], foreground=T["fg"],
        bordercolor=T["hint"]
    )

    style.configure(
        "TCombobox", fieldbackground=T["input"], foreground=T["fg"],
        background=T["btn"], arrowcolor=T["fg"]
    )
    root.option_add("*TCombobox*Listbox.background", T["input"])
    root.option_add("*TCombobox*Listbox.foreground", T["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", T["accent"])

    style.configure("TSeparator", background=T["sep"])
    style.configure(
        "TProgressbar", background=T["accent"], troughcolor=T["panel"]
    )
    style.configure(
        "TLabelframe", background=T["panel"], foreground=T["fg"], bordercolor=T["sep"]
    )
    style.configure(
        "TLabelframe.Label", background=T["panel"], foreground=T["fg_dim"]
    )

    return T


def set_titlebar_dark(window: tk.Misc, dark: bool) -> None:
    """
    Windows-only: färbt die Fenster-Titelleiste dunkel/hell via DWM-API.
    No-op (silently) auf anderen Plattformen oder bei älteren Windows-Builds.

    DWM übernimmt die neue Attribut-Farbe oft erst nach einem Neuzeichnen
    der Nicht-Client-Fläche (Titelleiste) — SWP_FRAMECHANGED erzwingt das,
    sonst bleibt die Titelleiste bis zum nächsten manuellen Resize weiss.
    """
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # Win11/neueres Win10, dann Fallback für ältere Builds
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if res == 0:
                break
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x2, 0x1, 0x4, 0x20
        ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
        )
    except Exception:
        pass
