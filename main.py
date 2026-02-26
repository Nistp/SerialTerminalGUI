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

from app.config import AppConfig, CONFIG_2_PATH
from app.gui.main_window import MainWindow


def main() -> None:
    config1 = AppConfig.load()
    config2 = AppConfig.load(path=CONFIG_2_PATH)
    root = tk.Tk()
    MainWindow(root, config1, config2)
    root.mainloop()


if __name__ == "__main__":
    main()
