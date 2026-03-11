"""
Serial Terminal GUI
Run with: python main.py
"""
import sys
import tkinter as tk

# DPI awareness for Windows high-DPI displays
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

from app.config import AppConfig
from app.gui.main_window import MainWindow


def main() -> None:
    config = AppConfig.load()
    root = tk.Tk()
    MainWindow(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
