"""Standalone settings window (run by the tray app in a separate process)."""

from config import load_config
from settings import open_settings_dialog

if __name__ == "__main__":
    open_settings_dialog(load_config())
