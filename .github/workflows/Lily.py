#!/usr/bin/env python3
"""
Lily - player de música local para Linux e Windows. Arquivo único.

Motores de áudio, em ordem de preferência:
    1. libVLC       (se o VLC estiver instalado)
    2. miniaudio    (se você rodar: pip install miniaudio)
    3. QtMultimedia (já vem com o PySide6, sempre funciona)

Uso:
    python3 lily.py             # abre o player
    python3 lily.py --install   # cria atalho no menu / Start Menu
    python3 lily.py --uninstall # remove o atalho
    python3 lily.py --build     # gera o .spec e empacota o executável
    python3 lily.py --ci        # gera o workflow do GitHub Actions
    python3 lily.py --version   # mostra a versão

O app nunca trava por falta de motor: se um falhar, ele passa para o próximo.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import random
import sqlite3
import struct
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

VERSION = "2.1.3"
APP_ID = "lily"
APP_NAME = "Lily"
LEGACY_ID = "venice-player"

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


def _config_root() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _data_root() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _migrate_legacy() -> None:
    """Traz config, temas, biblioteca e playlists do nome antigo."""
    for root in (_config_root(), _data_root()):
        old = root / LEGACY_ID
        new = root / APP_ID
        if old.is_dir() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                pass


_migrate_legacy()

CONFIG_DIR = _config_root() / APP_ID
CONFIG_FILE = CONFIG_DIR / "config.json"
THEME_DIR = CONFIG_DIR / "themes"
ICON_FILE = CONFIG_DIR / "icon.png"

DATA_DIR = _data_root() / APP_ID
DB_PATH = DATA_DIR / "library.db"

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f472b6"/>
      <stop offset="1" stop-color="#8b5cf6"/>
    </linearGradient>
  </defs>
  <rect width="128" height="128" rx="28" fill="url(#g)"/>
  <g transform="translate(64,66)">
    <ellipse cx="0" cy="-22" rx="11" ry="25" fill="#ffffff" opacity="0.96"/>
    <ellipse cx="0" cy="-22" rx="11" ry="25" fill="#ffffff" opacity="0.84" transform="rotate(120)"/>
    <ellipse cx="0" cy="-22" rx="11" ry="25" fill="#ffffff" opacity="0.84" transform="rotate(240)"/>
    <circle cx="0" cy="0" r="7" fill="#fde68a"/>
    <circle cx="0" cy="0" r="3" fill="#f59e0b"/>
  </g>
</svg>
"""

THEMES = {
    "midnight": """
QWidget { background: #10121a; color: #d7dae5; font-size: 13px; }
QMainWindow, QDialog { background: #0b0d13; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #181b26; border: 1px solid #262b3b; border-radius: 6px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #4f7cff; }
QPushButton { background: #1d2130; border: 1px solid #2a3044; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #262c3f; }
QPushButton[active="true"] { background: #4f7cff; color: #ffffff; border-color: #4f7cff; font-weight: 700; }
QPushButton:pressed { background: #4f7cff; color: #ffffff; }
QTabWidget::pane { border: 1px solid #222736; border-radius: 8px; }
QTabBar::tab {
    background: #181b26; color: #9aa2b8; padding: 6px 14px;
    border: 1px solid #222736; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #2b3a6b; color: #ffffff; }
QTreeWidget, QListWidget, QTableWidget {
    background: #12141d; border: 1px solid #222736; border-radius: 8px;
    alternate-background-color: #151824; outline: none;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #2b3a6b; color: #ffffff;
}
QHeaderView::section {
    background: #181b26; color: #9aa2b8; padding: 6px; border: none; border-bottom: 1px solid #262b3b;
}
QSlider::groove:horizontal { height: 5px; background: #232838; border-radius: 3px; }
QSlider::handle:horizontal { background: #4f7cff; width: 13px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #4f7cff; border-radius: 3px; }
QMenu { background: #181b26; border: 1px solid #2a3044; }
QMenu::item:selected { background: #2b3a6b; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #2e3448; border-radius: 5px; min-height: 24px; }
QSplitter::handle { background: #1a1e2b; }
QStatusBar { background: #0b0d13; color: #7d8598; }
QToolTip { background: #181b26; color: #d7dae5; border: 1px solid #2a3044; }
""",
    "nord": """
QWidget { background: #2e3440; color: #d8dee9; font-size: 13px; }
QMainWindow, QDialog { background: #272c36; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #3b4252; border: 1px solid #4c566a; border-radius: 6px; padding: 6px 8px;
}
QPushButton { background: #434c5e; border: 1px solid #4c566a; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #4c566a; }
QPushButton[active="true"] { background: #88c0d0; color: #2e3440; border-color: #88c0d0; font-weight: 700; }
QPushButton:pressed { background: #88c0d0; color: #2e3440; }
QTabWidget::pane { border: 1px solid #434c5e; border-radius: 8px; }
QTabBar::tab {
    background: #3b4252; color: #d8dee9; padding: 6px 14px;
    border: 1px solid #434c5e; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #5e81ac; color: #eceff4; }
QTreeWidget, QListWidget, QTableWidget {
    background: #2e3440; border: 1px solid #434c5e; border-radius: 8px; alternate-background-color: #333a48;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #5e81ac; color: #eceff4;
}
QHeaderView::section { background: #3b4252; color: #d8dee9; padding: 6px; border: none; }
QSlider::groove:horizontal { height: 5px; background: #434c5e; border-radius: 3px; }
QSlider::handle:horizontal { background: #88c0d0; width: 13px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #88c0d0; }
QMenu { background: #3b4252; border: 1px solid #4c566a; }
QMenu::item:selected { background: #5e81ac; }
QStatusBar { background: #272c36; color: #9aa5b5; }
""",
    "light": """
QWidget { background: #f5f6f8; color: #1e2230; font-size: 13px; }
QMainWindow, QDialog { background: #ffffff; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #ffffff; border: 1px solid #ccd2de; border-radius: 6px; padding: 6px 8px;
}
QLineEdit:focus { border: 1px solid #2f6bff; }
QPushButton { background: #eaeef6; border: 1px solid #ccd2de; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #dfe5f0; }
QPushButton[active="true"] { background: #2f6bff; color: #ffffff; border-color: #2f6bff; font-weight: 700; }
QPushButton:pressed { background: #2f6bff; color: #ffffff; }
QTabWidget::pane { border: 1px solid #dde2ea; border-radius: 8px; }
QTabBar::tab {
    background: #eef1f7; color: #4a5266; padding: 6px 14px;
    border: 1px solid #dde2ea; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #d6e2ff; color: #101426; }
QTreeWidget, QListWidget, QTableWidget {
    background: #ffffff; border: 1px solid #dde2ea; border-radius: 8px; alternate-background-color: #f7f9fc;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #d6e2ff; color: #101426;
}
QHeaderView::section {
    background: #eef1f7; color: #4a5266; padding: 6px; border: none; border-bottom: 1px solid #dde2ea;
}
QSlider::groove:horizontal { height: 5px; background: #dde2ea; border-radius: 3px; }
QSlider::handle:horizontal { background: #2f6bff; width: 13px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #2f6bff; }
QMenu { background: #ffffff; border: 1px solid #ccd2de; }
QMenu::item:selected { background: #d6e2ff; }
QStatusBar { background: #ffffff; color: #6b7280; }
""",
    "lily": """
QWidget { background: #17111d; color: #f0e6f5; font-size: 13px; }
QMainWindow, QDialog { background: #0f0a14; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #241830; border: 1px solid #43264f; border-radius: 6px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #f472b6; }
QPushButton { background: #291b38; border: 1px solid #4a2a58; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #37224a; }
QPushButton[active="true"] { background: #f472b6; color: #1a0d18; border-color: #f9a8d4; font-weight: 700; }
QPushButton:pressed { background: #f472b6; color: #1a0d18; }
QTabWidget::pane { border: 1px solid #3a2247; border-radius: 8px; }
QTabBar::tab {
    background: #241830; color: #c9a8d8; padding: 6px 14px;
    border: 1px solid #3a2247; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #7c3a86; color: #ffffff; }
QTreeWidget, QListWidget, QTableWidget {
    background: #1a1122; border: 1px solid #3a2247; border-radius: 8px;
    alternate-background-color: #1f1428; outline: none;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #7c3a86; color: #ffffff;
}
QHeaderView::section {
    background: #241830; color: #c9a8d8; padding: 6px; border: none; border-bottom: 1px solid #3a2247;
}
QSlider::groove:horizontal { height: 5px; background: #331d3f; border-radius: 3px; }
QSlider::handle:horizontal { background: #f472b6; width: 13px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #f472b6; }
QMenu { background: #241830; border: 1px solid #4a2a58; }
QMenu::item:selected { background: #7c3a86; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #4a2a58; border-radius: 5px; min-height: 24px; }
QStatusBar { background: #0f0a14; color: #9b7dab; }
QToolTip { background: #241830; color: #f0e6f5; border: 1px solid #4a2a58; }
""",
    "roxo": """
QWidget { background: #150f26; color: #e4dcf7; font-size: 13px; }
QMainWindow, QDialog { background: #0e0a1a; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #211741; border: 1px solid #3a2a63; border-radius: 6px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #a855f7; }
QPushButton { background: #261a4a; border: 1px solid #3d2b6b; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #33235f; }
QPushButton[active="true"] { background: #a855f7; color: #12071f; border-color: #c084fc; font-weight: 700; }
QPushButton:pressed { background: #a855f7; color: #12071f; }
QTabWidget::pane { border: 1px solid #33245c; border-radius: 8px; }
QTabBar::tab {
    background: #211741; color: #b9a8e0; padding: 6px 14px;
    border: 1px solid #33245c; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #5b2ea6; color: #ffffff; }
QTreeWidget, QListWidget, QTableWidget {
    background: #180f2c; border: 1px solid #33245c; border-radius: 8px;
    alternate-background-color: #1d1334; outline: none;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #5b2ea6; color: #ffffff;
}
QHeaderView::section {
    background: #211741; color: #b9a8e0; padding: 6px; border: none; border-bottom: 1px solid #33245c;
}
QSlider::groove:horizontal { height: 5px; background: #2e2050; border-radius: 3px; }
QSlider::handle:horizontal { background: #a855f7; width: 13px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #a855f7; }
QMenu { background: #211741; border: 1px solid #3d2b6b; }
QMenu::item:selected { background: #5b2ea6; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #3d2b6b; border-radius: 5px; min-height: 24px; }
QStatusBar { background: #0e0a1a; color: #8f7fbb; }
QToolTip { background: #211741; color: #e4dcf7; border: 1px solid #3d2b6b; }
""",
    "vermelho": """
QWidget { background: #170d0f; color: #f5dcdc; font-size: 13px; }
QMainWindow, QDialog { background: #100709; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #261316; border: 1px solid #43201f; border-radius: 6px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #ef4444; }
QPushButton { background: #2c1618; border: 1px solid #4a2222; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #3b1d1e; }
QPushButton[active="true"] { background: #ef4444; color: #1a0808; border-color: #f87171; font-weight: 700; }
QPushButton:pressed { background: #ef4444; color: #1a0808; }
QTabWidget::pane { border: 1px solid #3d1d1c; border-radius: 8px; }
QTabBar::tab {
    background: #261316; color: #d3a3a3; padding: 6px 14px;
    border: 1px solid #3d1d1c; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #a32222; color: #ffffff; }
QTreeWidget, QListWidget, QTableWidget {
    background: #1a0d0f; border: 1px solid #3d1d1c; border-radius: 8px;
    alternate-background-color: #201113; outline: none;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #a32222; color: #ffffff;
}
QHeaderView::section {
    background: #261316; color: #d3a3a3; padding: 6px; border: none; border-bottom: 1px solid #3d1d1c;
}
QSlider::groove:horizontal { height: 5px; background: #33191a; border-radius: 3px; }
QSlider::handle:horizontal { background: #ef4444; width: 13px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #ef4444; }
QMenu { background: #261316; border: 1px solid #4a2222; }
QMenu::item:selected { background: #a32222; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #4a2222; border-radius: 5px; min-height: 24px; }
QStatusBar { background: #100709; color: #a06d6d; }
QToolTip { background: #261316; color: #f5dcdc; border: 1px solid #4a2222; }
""",
    "amarelo": """
QWidget { background: #16130a; color: #f7ecc4; font-size: 13px; }
QMainWindow, QDialog { background: #0f0d06; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #241e0e; border: 1px solid #423714; border-radius: 6px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #facc15; }
QPushButton { background: #2a2310; border: 1px solid #4a3d14; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #382e14; }
QPushButton[active="true"] { background: #facc15; color: #1a1404; border-color: #fde047; font-weight: 700; }
QPushButton:pressed { background: #facc15; color: #1a1404; }
QTabWidget::pane { border: 1px solid #3d3312; border-radius: 8px; }
QTabBar::tab {
    background: #241e0e; color: #cfc08a; padding: 6px 14px;
    border: 1px solid #3d3312; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #8a6d0c; color: #fffbe8; }
QTreeWidget, QListWidget, QTableWidget {
    background: #191408; border: 1px solid #3d3312; border-radius: 8px;
    alternate-background-color: #1e180a; outline: none;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #8a6d0c; color: #fffbe8;
}
QHeaderView::section {
    background: #241e0e; color: #cfc08a; padding: 6px; border: none; border-bottom: 1px solid #3d3312;
}
QSlider::groove:horizontal { height: 5px; background: #332a10; border-radius: 3px; }
QSlider::handle:horizontal { background: #facc15; width: 13px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #facc15; }
QMenu { background: #241e0e; border: 1px solid #4a3d14; }
QMenu::item:selected { background: #8a6d0c; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #4a3d14; border-radius: 5px; min-height: 24px; }
QStatusBar { background: #0f0d06; color: #a89a63; }
QToolTip { background: #241e0e; color: #f7ecc4; border: 1px solid #4a3d14; }
""",
    "cyberpunk": """
QWidget {
    background: #04070a; color: #39ff14;
    font-family: "DejaVu Sans Mono", "Consolas", "Courier New", monospace; font-size: 13px;
}
QMainWindow, QDialog { background: #000000; }
QLabel { color: #39ff14; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {
    background: #060b0d; color: #39ff14;
    border: 1px solid #0f7a2e; border-radius: 0px; padding: 6px 8px;
    selection-background-color: #39ff14; selection-color: #04070a;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #39ff14; }
QComboBox QAbstractItemView {
    background: #04070a; color: #39ff14; border: 1px solid #39ff14;
    selection-background-color: #39ff14; selection-color: #04070a;
}
QPushButton {
    background: #060b0d; color: #39ff14;
    border: 1px solid #0f7a2e; border-radius: 0px; padding: 6px 12px;
}
QPushButton:hover { border: 1px solid #39ff14; background: #0a1410; }
QPushButton[active="true"] {
    background: #39ff14; color: #04070a; border: 1px solid #39ff14; font-weight: 700;
}
QPushButton:pressed { background: #39ff14; color: #04070a; }
QTabWidget::pane { border: 1px solid #0f7a2e; border-radius: 0px; }
QTabBar::tab {
    background: #060b0d; color: #1f9e3a; padding: 6px 14px;
    border: 1px solid #0f7a2e; border-bottom: none; border-radius: 0px; margin-right: 2px;
}
QTabBar::tab:selected { background: #0d2b16; color: #39ff14; border-color: #39ff14; }
QTreeWidget, QListWidget, QTableWidget {
    background: #04070a; color: #39ff14;
    border: 1px solid #0f7a2e; border-radius: 0px;
    alternate-background-color: #060d0a; outline: none;
    selection-background-color: #0d2b16; selection-color: #7dffb0;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background: #0d2b16; color: #7dffb0;
}
QHeaderView::section {
    background: #060b0d; color: #1f9e3a; padding: 6px;
    border: none; border-right: 1px solid #0f7a2e; border-bottom: 1px solid #0f7a2e;
    font-weight: 700;
}
QSlider::groove:horizontal { height: 4px; background: #0a1a10; border-radius: 0px; }
QSlider::handle:horizontal { background: #39ff14; width: 12px; margin: -5px 0; border-radius: 0px; }
QSlider::sub-page:horizontal { background: #39ff14; }
QMenu { background: #04070a; color: #39ff14; border: 1px solid #39ff14; }
QMenu::item:selected { background: #0d2b16; color: #7dffb0; }
QScrollBar:vertical { background: #04070a; width: 10px; }
QScrollBar::handle:vertical { background: #0f7a2e; border-radius: 0px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #39ff14; }
QSplitter::handle { background: #0a1a10; }
QStatusBar { background: #000000; color: #1f9e3a; }
QToolTip { background: #04070a; color: #39ff14; border: 1px solid #39ff14; }
""",
}

DEFAULTS = {
    "music_dirs": [],
    "theme": "lily",
    "volume": 0.75,
    "shuffle": False,
    "repeat": "off",
    "crossfade_ms": 0,
    "fade_ms": 200,
    "window": {"w": 1080, "h": 660},
    "shortcuts": {
        "play_pause": "Space",
        "next": "Ctrl+Right",
        "previous": "Ctrl+Left",
        "volume_up": "Ctrl+Up",
        "volume_down": "Ctrl+Down",
        "search": "Ctrl+F",
        "toggle_shuffle": "Ctrl+S",
        "toggle_repeat": "Ctrl+R",
        "clear_queue": "Ctrl+Shift+C",
    },
}

SHORTCUT_LABELS = {
    "play_pause": "Tocar / pausar",
    "next": "Próxima faixa",
    "previous": "Faixa anterior",
    "volume_up": "Aumentar volume",
    "volume_down": "Diminuir volume",
    "search": "Ir para a busca",
    "toggle_shuffle": "Alternar aleatório",
    "toggle_repeat": "Alternar repetição",
    "clear_queue": "Limpar fila",
}

AUDIO_EXTS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4",
    ".wav", ".aiff", ".aac", ".wma", ".mka", ".ape", ".wv",
}

SIDECAR_COVERS = (
    "cover.jpg", "cover.png", "cover.jpeg", "folder.jpg", "folder.png",
    "front.jpg", "front.png", "album.jpg", "albumart.jpg", "Cover.jpg",
)


# ==========================================================================
# MODELO DO BUILD (usado por --build) E DO WORKFLOW (usado por --ci)
# ==========================================================================

SPEC_TEMPLATE = '''# -*- mode: python ; coding: utf-8 -*-
"""Gerado automaticamente por lily.py --build. Pode apagar sem medo."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP_NAME = "__APP_NAME__"
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

datas, binaries, hiddenimports = [], [], []


def collect(*pkgs):
    for pkg in pkgs:
        d, b, h = collect_all(pkg)
        datas.extend(d)
        binaries.extend(b)
        hiddenimports.extend(h)


collect(
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSvg",
    "PySide6.QtNetwork",
    "mutagen",
)
hiddenimports.append("vlc")
hiddenimports.append("miniaudio")


def _vlc_roots():
    roots = []
    if IS_WINDOWS:
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env)
            if base:
                roots.append(Path(base) / "VideoLAN" / "VLC")
    elif IS_LINUX:
        roots += [
            Path("/usr/lib/x86_64-linux-gnu"),
            Path("/usr/lib"),
            Path("/usr/lib/vlc"),
        ]
    return roots


def _bundle_vlc():
    for root in _vlc_roots():
        if not root.is_dir():
            continue
        libs = [
            p for p in root.iterdir()
            if p.name.startswith("libvlc")
            and (p.suffix in {".dll", ".so"} or ".so." in p.name or p.suffix == ".dylib")
        ]
        if not libs:
            continue
        for lib in libs:
            binaries.append((str(lib), "."))
        plugins = root / "plugins"
        if plugins.is_dir():
            for dirpath, _dirs, files in os.walk(plugins):
                for name in files:
                    src = Path(dirpath) / name
                    rel = src.relative_to(plugins)
                    binaries.append((str(src), str(Path("plugins") / rel.parent)))
        return True
    return False


print("[spec] libVLC:", "incluida" if _bundle_vlc() else "ausente (fallback miniaudio/Qt)")

excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtBluetooth",
    "tkinter", "unittest", "pydoc_data", "test",
]

a = Analysis(
    ["__ENTRY__"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe_kwargs = {}
_icon = Path("assets") / ("lily.ico" if IS_WINDOWS else "lily.png")
if _icon.is_file():
    exe_kwargs["icon"] = str(_icon)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **exe_kwargs,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
'''

WORKFLOW_TEMPLATE = '''name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            artifact: Lily-windows
          - os: ubuntu-22.04
            artifact: Lily-linux
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Dependencias
        run: |
          python -m pip install -U pip
          pip install PySide6 mutagen miniaudio pyinstaller

      - name: Build
        run: python lily.py --build

      - name: Zipar (Windows)
        if: runner.os == 'Windows'
        shell: pwsh
        run: Compress-Archive -Path dist/Lily/* -DestinationPath dist/${{ matrix.artifact }}.zip

      - name: Tar (Linux)
        if: runner.os == 'Linux'
        run: tar -czf dist/${{ matrix.artifact }}.tar.gz -C dist Lily

      - name: Publicar no Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            dist/*.zip
            dist/*.tar.gz
'''


def build_app() -> int:
    """Gera o .spec e empacota o app com PyInstaller."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller não encontrado. Instale com:")
        print("    pip install pyinstaller")
        return 1

    entry = Path(__file__).resolve()
    spec_path = entry.with_suffix(".spec")
    spec_path.write_text(
        SPEC_TEMPLATE.replace("__APP_NAME__", APP_NAME).replace("__ENTRY__", entry.name),
        "utf-8",
    )
    print(f"Spec gerado em: {spec_path}")
    print("Empacotando... isso pode demorar alguns minutos.\n")

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec_path)]
    result = subprocess.run(cmd, cwd=str(entry.parent))

    if result.returncode == 0:
        print(f"\nPronto! Executável em: {entry.parent / 'dist' / APP_NAME}")
    return result.returncode


def write_ci() -> int:
    """Cria o workflow do GitHub Actions em .github/workflows/release.yml."""
    target = Path(__file__).resolve().parent / ".github" / "workflows" / "release.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(WORKFLOW_TEMPLATE, "utf-8")
    print(f"Workflow criado em: {target}")
    print("Agora commite, e ao empurrar uma tag 'vX.Y.Z' o GitHub compila e publica sozinho.")
    return 0


# --------------------------------------------------------------------------
# configuração
# --------------------------------------------------------------------------

def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def ensure_themes() -> None:
    THEME_DIR.mkdir(parents=True, exist_ok=True)
    for name, qss in THEMES.items():
        path = THEME_DIR / f"{name}.qss"
        if not path.exists():
            path.write_text(qss.strip() + "\n", "utf-8")


def load_config() -> dict:
    ensure_themes()
    if CONFIG_FILE.exists():
        try:
            return _merge(DEFAULTS, json.loads(CONFIG_FILE.read_text("utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return copy.deepcopy(DEFAULTS)


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")


def available_themes() -> list[str]:
    ensure_themes()
    names = sorted(p.stem for p in THEME_DIR.glob("*.qss"))
    return names or ["midnight"]


def theme_qss(name: str) -> str:
    path = THEME_DIR / f"{name}.qss"
    return path.read_text("utf-8") if path.exists() else THEMES.get(name, "")


# --------------------------------------------------------------------------
# Qt
# --------------------------------------------------------------------------

from PySide6.QtCore import QBuffer, QObject, Qt, QThread, QTimer, QUrl, Signal   # noqa: E402
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut               # noqa: E402
from PySide6.QtWidgets import (                                                 # noqa: E402
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSlider,
    QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


# --------------------------------------------------------------------------
# ícone do aplicativo
# --------------------------------------------------------------------------

def _svg_pixmap(size: int = 256) -> QPixmap:
    try:
        from PySide6.QtGui import QPainter
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(ICON_SVG.encode("utf-8"))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap
    except Exception:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        return pixmap


def pixmap_png_bytes(pixmap: QPixmap) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(png_bytes: bytes, path: Path) -> None:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_bytes), 22)
    path.write_bytes(header + entry + png_bytes)


def app_icon(cfg: dict | None = None) -> QIcon:
    if cfg:
        custom = cfg.get("icon_path")
        if custom and Path(custom).is_file():
            icon = QIcon(str(custom))
            if not icon.isNull():
                return icon
    return QIcon(_svg_pixmap(256))


def install_custom_icon(source: str, cfg: dict) -> bool:
    src = Path(source)
    if not src.is_file():
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = src.read_bytes()
    except OSError:
        return False

    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        if src.suffix.lower() == ".svg":
            pixmap = _svg_pixmap(256)
        else:
            return False

    pixmap = pixmap.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pixmap.save(str(ICON_FILE), "PNG")
    cfg["icon_path"] = str(ICON_FILE)
    save_config(cfg)
    return True


def icon_as_ico() -> Path | None:
    pixmap = _svg_pixmap(256)
    if ICON_FILE.is_file():
        loaded = QPixmap(str(ICON_FILE))
        if not loaded.isNull():
            pixmap = loaded.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    try:
        target = CONFIG_DIR / "icon.ico"
        write_ico(pixmap_png_bytes(pixmap), target)
        return target
    except OSError:
        return None


# --------------------------------------------------------------------------
# atalho no sistema
# --------------------------------------------------------------------------

def launch_command() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ""
    return str(Path(sys.executable).resolve()), str(Path(__file__).resolve())


def install_shortcut(cfg: dict) -> tuple[bool, str]:
    target, script = launch_command()
    try:
        if IS_WINDOWS:
            return _install_windows(target, script, cfg)
        return _install_linux(target, script, cfg)
    except Exception as exc:
        return False, str(exc)


def _install_linux(target: str, script: str, cfg: dict) -> tuple[bool, str]:
    apps_dir = Path.home() / ".local" / "share" / "applications"
    icons_dir = Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    (apps_dir / f"{LEGACY_ID}.desktop").unlink(missing_ok=True)
    (icons_dir / f"{LEGACY_ID}.svg").unlink(missing_ok=True)

    icon_path = Path(cfg["icon_path"]) if cfg.get("icon_path") and Path(cfg["icon_path"]).is_file() else None
    if icon_path:
        (icons_dir / f"{APP_ID}.svg").unlink(missing_ok=True)
        icon_ref = str(icon_path)
    else:
        (icons_dir / f"{APP_ID}.svg").write_text(ICON_SVG, "utf-8")
        icon_ref = APP_ID

    exec_line = f'"{target}" "{script}"' if script else f'"{target}"'
    desktop = apps_dir / f"{APP_ID}.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={APP_NAME}\n"
        "GenericName=Player de música\n"
        f"Comment={APP_NAME} — player de música local com temas e playlists\n"
        f"Exec={exec_line}\n"
        f"Icon={icon_ref}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Audio;Player;Qt;\n"
        f"StartupWMClass={APP_ID}\n"
        "Keywords=musica;audio;player;mp3;flac;ogg;lily;\n",
        "utf-8",
    )
    desktop.chmod(0o755)

    for cmd in (
        ["update-desktop-database", str(apps_dir)],
        ["gtk-update-icon-cache", "-f", "-t", str(icons_dir.parent.parent.parent)],
    ):
        try:
            subprocess.run(cmd, capture_output=True, timeout=15)
        except Exception:
            pass
    return True, str(desktop)


def _install_windows(target: str, script: str, cfg: dict) -> tuple[bool, str]:
    start_menu = (
        Path(os.environ.get("APPDATA", Path.home())) /
        "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )
    start_menu.mkdir(parents=True, exist_ok=True)
    (start_menu / f"{LEGACY_ID}.lnk").unlink(missing_ok=True)
    lnk = start_menu / f"{APP_NAME}.lnk"

    ico = icon_as_ico()
    if ico is None:
        ico = Path(sys.executable)

    arguments = f'"{script}"' if script else ""
    workdir = str(Path(script).parent) if script else str(Path(target).parent)

    ps = (
        f'$ws = New-Object -ComObject WScript.Shell;'
        f'$sc = $ws.CreateShortcut("{lnk}");'
        f'$sc.TargetPath = "{target}";'
        f'$sc.Arguments = \'{arguments}\';'
        f'$sc.WorkingDirectory = "{workdir}";'
        f'$sc.IconLocation = "{ico},0";'
        f'$sc.Description = "{APP_NAME} — player de música local";'
        f'$sc.Save()'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or "PowerShell falhou"
    return True, str(lnk)


def uninstall_shortcut() -> None:
    if IS_WINDOWS:
        start_menu = (
            Path(os.environ.get("APPDATA", Path.home())) /
            "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
        (start_menu / f"{APP_NAME}.lnk").unlink(missing_ok=True)
        (start_menu / f"{LEGACY_ID}.lnk").unlink(missing_ok=True)
        return
    for path in (
        Path.home() / ".local" / "share" / "applications" / f"{APP_ID}.desktop",
        Path.home() / ".local" / "share" / "applications" / f"{LEGACY_ID}.desktop",
        Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
        Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{LEGACY_ID}.svg",
    ):
        path.unlink(missing_ok=True)


def open_folder(path: str) -> None:
    folder = str(Path(path).parent)
    try:
        if IS_WINDOWS:
            os.startfile(folder)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass


# --------------------------------------------------------------------------
# biblioteca
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id       INTEGER PRIMARY KEY,
    path     TEXT UNIQUE NOT NULL,
    title    TEXT, artist TEXT, album TEXT, genre TEXT,
    track_no INTEGER, year INTEGER, duration INTEGER,
    mtime    REAL, added REAL
);
CREATE INDEX IF NOT EXISTS idx_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_album  ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_genre  ON tracks(genre);

CREATE TABLE IF NOT EXISTS playlists (
    id      INTEGER PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL,
    created REAL
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL,
    path        TEXT NOT NULL,
    position    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pt_playlist ON playlist_tracks(playlist_id, position);
"""


@dataclass
class Track:
    id: int
    path: str
    title: str
    artist: str
    album: str
    genre: str
    track_no: int
    year: int
    duration: int

    @property
    def display(self) -> str:
        return f"{self.title}  —  {self.artist}" if self.artist else self.title


def db_connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with closing(db_connect()) as con:
        con.executescript(SCHEMA)
        con.commit()


def iter_audio_files(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if Path(name).suffix.lower() in AUDIO_EXTS:
                yield str(Path(dirpath) / name)


def read_tags(path: str) -> dict:
    stem = Path(path).stem
    title, artist, album, genre = stem, "", "", ""
    track_no = year = duration = 0
    try:
        import mutagen
        audio = mutagen.File(path, easy=True)
        if audio is not None:
            def first(key):
                val = audio.get(key)
                return str(val[0]) if val else ""

            title = first("title") or title
            artist = first("artist") or first("albumartist")
            album = first("album")
            genre = first("genre")
            raw_no = first("tracknumber").split("/")[0]
            track_no = int(raw_no) if raw_no.isdigit() else 0
            raw_year = first("date")[:4]
            year = int(raw_year) if raw_year.isdigit() else 0
            if audio.info is not None:
                duration = int(getattr(audio.info, "length", 0) or 0)
    except Exception:
        pass

    return {
        "path": path, "title": title, "artist": artist, "album": album,
        "genre": genre, "track_no": track_no, "year": year, "duration": duration,
        "mtime": Path(path).stat().st_mtime, "added": time.time(),
    }


def upsert_tracks(rows: list[dict]) -> None:
    if not rows:
        return
    with closing(db_connect()) as con:
        con.executemany(
            """INSERT INTO tracks (path, title, artist, album, genre, track_no, year, duration, mtime, added)
               VALUES (:path, :title, :artist, :album, :genre, :track_no, :year, :duration, :mtime, :added)
               ON CONFLICT(path) DO UPDATE SET
                   title=excluded.title, artist=excluded.artist, album=excluded.album,
                   genre=excluded.genre, track_no=excluded.track_no, year=excluded.year,
                   duration=excluded.duration, mtime=excluded.mtime""",
            rows,
        )
        con.commit()


def _row_to_track(row: sqlite3.Row) -> Track:
    return Track(
        id=row["id"], path=row["path"], title=row["title"] or Path(row["path"]).stem,
        artist=row["artist"] or "", album=row["album"] or "", genre=row["genre"] or "",
        track_no=row["track_no"] or 0, year=row["year"] or 0, duration=row["duration"] or 0,
    )


def search_tracks(text: str = "", view: str = "all", value: str | None = None) -> list[Track]:
    clauses, params = [], []
    if text:
        like = f"%{text}%"
        clauses.append("(title LIKE ? OR artist LIKE ? OR album LIKE ? OR genre LIKE ?)")
        params += [like, like, like, like]
    if view == "artist" and value:
        clauses.append("artist = ?"); params.append(value)
    elif view == "album" and value:
        clauses.append("album = ?"); params.append(value)
    elif view == "genre" and value:
        clauses.append("genre = ?"); params.append(value)
    elif view == "folder" and value:
        clauses.append("path LIKE ?"); params.append(f"{value}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (f"SELECT * FROM tracks {where} ORDER BY artist COLLATE NOCASE, "
           "album COLLATE NOCASE, track_no, title COLLATE NOCASE")
    with closing(db_connect()) as con:
        return [_row_to_track(r) for r in con.execute(sql, params)]


def distinct(field: str) -> list[str]:
    with closing(db_connect()) as con:
        rows = con.execute(
            f"SELECT DISTINCT {field} AS v FROM tracks WHERE {field} != '' ORDER BY v COLLATE NOCASE"
        )
        return [r["v"] for r in rows]


def remove_tracks(paths: list[str]) -> None:
    with closing(db_connect()) as con:
        con.executemany("DELETE FROM tracks WHERE path = ?", [(p,) for p in paths])
        con.commit()


def prune_missing() -> int:
    with closing(db_connect()) as con:
        paths = [r["path"] for r in con.execute("SELECT path FROM tracks")]
        missing = [p for p in paths if not Path(p).exists()]
        con.executemany("DELETE FROM tracks WHERE path = ?", [(p,) for p in missing])
        con.commit()
    return len(missing)


# --- playlists ---

def list_playlists() -> list[tuple[int, str]]:
    with closing(db_connect()) as con:
        rows = con.execute("SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE")
        return [(r["id"], r["name"]) for r in rows]


def create_playlist(name: str) -> int:
    with closing(db_connect()) as con:
        cur = con.execute(
            "INSERT INTO playlists (name, created) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET name=name",
            (name, time.time()),
        )
        con.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = con.execute("SELECT id FROM playlists WHERE name = ?", (name,)).fetchone()
        return int(row["id"])


def rename_playlist(playlist_id: int, new_name: str) -> bool:
    try:
        with closing(db_connect()) as con:
            con.execute("UPDATE playlists SET name = ? WHERE id = ?", (new_name, playlist_id))
            con.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_playlist(playlist_id: int) -> None:
    with closing(db_connect()) as con:
        con.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        con.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        con.commit()


def add_to_playlist(playlist_id: int, paths: list[str]) -> None:
    if not paths:
        return
    with closing(db_connect()) as con:
        row = con.execute(
            "SELECT COALESCE(MAX(position), -1) AS m FROM playlist_tracks WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()
        start = int(row["m"]) + 1
        con.executemany(
            "INSERT INTO playlist_tracks (playlist_id, path, position) VALUES (?, ?, ?)",
            [(playlist_id, p, start + i) for i, p in enumerate(paths)],
        )
        con.commit()


def playlist_tracks(playlist_id: int) -> list[Track]:
    sql = """SELECT t.* FROM playlist_tracks p
             JOIN tracks t ON t.path = p.path
             WHERE p.playlist_id = ?
             ORDER BY p.position"""
    with closing(db_connect()) as con:
        return [_row_to_track(r) for r in con.execute(sql, (playlist_id,))]


def remove_from_playlist(playlist_id: int, path: str) -> None:
    with closing(db_connect()) as con:
        con.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ? AND path = ?",
            (playlist_id, path),
        )
        con.commit()


# --- metadados ---

def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def extract_cover(path: str) -> bytes | None:
    try:
        import mutagen
        audio = mutagen.File(path)
        if audio is not None:
            tags = getattr(audio, "tags", None)
            if tags is not None:
                apic = getattr(tags, "getall", lambda *_: [])("APIC")
                if apic:
                    return apic[0].data
                covr = tags.get("covr")
                if covr:
                    return bytes(covr[0])
            pictures = getattr(audio, "pictures", None)
            if pictures:
                return pictures[0].data
            block = audio.get("metadata_block_picture")
            if block:
                from mutagen.flac import Picture
                return Picture(base64.b64decode(block[0])).data
    except Exception:
        pass

    folder = Path(path).parent
    for name in SIDECAR_COVERS:
        candidate = folder / name
        try:
            if candidate.is_file():
                return candidate.read_bytes()
        except OSError:
            pass
    return None


def track_info(path: str) -> dict:
    info = {"format": "", "bitrate": "", "sample_rate": "", "channels": "", "size": ""}
    try:
        info["size"] = human_size(Path(path).stat().st_size)
    except OSError:
        pass

    info["format"] = Path(path).suffix.lstrip(".").upper() or "—"

    try:
        import mutagen
        audio = mutagen.File(path)
        if audio is not None and audio.info is not None:
            raw = audio.info
            bitrate = getattr(raw, "bitrate", 0) or 0
            if bitrate:
                info["bitrate"] = f"{bitrate // 1000} kbps"
            rate = getattr(raw, "sample_rate", 0) or 0
            if rate:
                info["sample_rate"] = f"{rate} Hz"
            channels = getattr(raw, "channels", 0) or 0
            if channels:
                info["channels"] = {1: "mono", 2: "estéreo"}.get(channels, f"{channels} canais")
    except Exception:
        pass
    return info


# --------------------------------------------------------------------------
# motor de áudio
# --------------------------------------------------------------------------

class BaseBackend(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    finished = Signal()
    errorRaised = Signal(str)

    name = "base"

    def load(self, path): ...
    def play(self): ...
    def pause(self): ...
    def stop(self): ...
    def set_position(self, ms): ...
    def set_volume(self, vol): ...

    def is_playing(self) -> bool:
        return False


class VlcBackend(BaseBackend):
    name = "libVLC"

    def __init__(self, parent=None):
        super().__init__(parent)
        import vlc

        self._vlc = vlc
        self._instance = vlc.Instance("--no-video", "--quiet")
        self._mp = self._instance.media_player_new()
        self._last_pos = -1
        self._last_len = -1
        self._mp.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached, lambda _e: self.finished.emit()
        )
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        pos = self._mp.get_time()
        length = self._mp.get_length()
        if pos != self._last_pos:
            self._last_pos = pos
            self.positionChanged.emit(max(pos, 0))
        if length != self._last_len:
            self._last_len = length
            self.durationChanged.emit(max(length, 0))

    def load(self, path):
        self._mp.set_media(self._instance.media_new_path(path))

    def play(self):
        self._mp.play()

    def pause(self):
        self._mp.pause()

    def stop(self):
        self._mp.stop()

    def set_position(self, ms):
        self._mp.set_time(int(ms))

    def set_volume(self, vol):
        self._mp.audio_set_volume(int(max(0.0, min(1.0, vol)) * 100))

    def is_playing(self):
        return bool(self._mp.is_playing())

    def raw_position(self):
        return max(self._mp.get_time(), 0)

    def raw_duration(self):
        return max(self._mp.get_length(), 0)


class QtBackend(BaseBackend):
    name = "QtMultimedia"

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        self._QMediaPlayer = QMediaPlayer
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        # QMediaPlayer emite qint64; passamos por slots que reemitem como int,
        # evitando o mismatch de assinatura que derrubava o app.
        self._player.positionChanged.connect(self._relay_position)
        self._player.durationChanged.connect(self._relay_duration)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(
            lambda *_: self.errorRaised.emit(self._player.errorString())
        )

    def _relay_position(self, pos: int):
        self.positionChanged.emit(int(pos))

    def _relay_duration(self, dur: int):
        self.durationChanged.emit(int(dur))

    def _on_status(self, status):
        if status == self._QMediaPlayer.EndOfMedia:
            self.finished.emit()

    def load(self, path):
        self._player.setSource(QUrl.fromLocalFile(path))

    def play(self):
        self._player.play()

    def pause(self):
        self._player.pause()

    def stop(self):
        self._player.stop()

    def set_position(self, ms):
        self._player.setPosition(int(ms))

    def set_volume(self, vol):
        self._audio.setVolume(max(0.0, min(1.0, vol)))

    def is_playing(self):
        from PySide6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def raw_position(self):
        return max(self._player.position(), 0)

    def raw_duration(self):
        return max(self._player.duration(), 0)


class MiniAudioBackend(BaseBackend):
    """Backend sem VLC: pip install miniaudio. Toca mp3, flac, wav e ogg."""

    name = "miniaudio"

    def __init__(self, parent=None):
        super().__init__(parent)
        import miniaudio

        self._ma = miniaudio
        self._device = None
        self._samples = None
        self._index = 0
        self._channels = 2
        self._rate = 44100
        self._volume = 0.75
        self._playing = False
        self._ended = False
        self._last_pos = -1

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # -- utilidades
    def _total_frames(self) -> int:
        if not self._samples:
            return 0
        return len(self._samples) // max(1, self._channels)

    def _close_device(self):
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        self._playing = False

    def _generator(self):
        total = len(self._samples) if self._samples else 0
        chunk = max(1, self._rate) * max(1, self._channels)
        while self._index < total:
            end = min(self._index + chunk, total)
            block = self._samples[self._index:end]
            self._index = end
            yield block
        self._ended = True

    def _start_device(self):
        self._close_device()
        if not self._samples:
            return
        self._device = self._ma.PlaybackDevice(
            output_format=self._ma.SampleFormat.SIGNED16,
            nchannels=self._channels,
            sample_rate=self._rate,
            volume=self._volume,
        )
        self._ended = False
        self._device.start(self._generator())
        self._playing = True

    def _tick(self):
        if self._ended and self._playing:
            self._playing = False
            self._ended = False
            self.finished.emit()
            return
        pos = self.raw_position()
        if pos != self._last_pos:
            self._last_pos = pos
            self.positionChanged.emit(pos)

    # -- API do backend
    def load(self, path):
        self._close_device()
        decoded = self._ma.decode_file(path)
        self._samples = decoded.samples
        self._channels = decoded.nchannels
        self._rate = decoded.sample_rate
        self._index = 0
        self._ended = False
        self._last_pos = -1
        self.durationChanged.emit(self.raw_duration())

    def play(self):
        if not self._playing:
            self._start_device()

    def pause(self):
        self._close_device()

    def stop(self):
        self._close_device()
        self._index = 0
        self._ended = False
        self.positionChanged.emit(0)

    def set_position(self, ms):
        if not self._samples:
            return
        frame = max(0, min(int(ms / 1000.0 * self._rate), self._total_frames()))
        self._index = frame * self._channels
        self._ended = False
        if self._playing:
            self._start_device()
        else:
            self.positionChanged.emit(ms)

    def set_volume(self, vol):
        self._volume = max(0.0, min(1.0, vol))
        if self._device is not None:
            try:
                self._device.volume = self._volume
            except Exception:
                pass

    def is_playing(self) -> bool:
        return self._playing

    def raw_position(self) -> int:
        if not self._samples:
            return 0
        return int(self._index / max(1, self._channels) / self._rate * 1000)

    def raw_duration(self) -> int:
        if not self._samples:
            return 0
        return int(self._total_frames() / self._rate * 1000)


def _prepare_vlc_env() -> None:
    """Ajuda o python-vlc a encontrar a libVLC no Windows e no Linux."""
    candidates: list[Path] = []

    if IS_WINDOWS:
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "VideoLAN" / "VLC")
    elif not IS_MAC:
        candidates += [
            Path("/usr/lib"),
            Path("/usr/lib/x86_64-linux-gnu"),
            Path("/usr/local/lib"),
        ]

    try:
        candidates.append(Path(__file__).resolve().parent)
    except NameError:
        pass
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)

    lib_names = ("libvlc.dll", "libvlc.so", "libvlc.so.5", "libvlc.dylib")

    for folder in candidates:
        if not folder.is_dir():
            continue
        for name in lib_names:
            dll = folder / name
            if dll.is_file():
                os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
                if not IS_MAC:
                    os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(dll))
                # plugins empacotados ao lado do executável (dist/Lily/plugins)
                plugins = folder / "plugins"
                if plugins.is_dir():
                    os.environ.setdefault("VLC_PLUGIN_PATH", str(plugins))
                return


def build_backend(parent=None) -> BaseBackend:
    """Escolhe o melhor motor disponível, sem nunca travar o app."""
    _prepare_vlc_env()
    for factory in (VlcBackend, MiniAudioBackend, QtBackend):
        try:
            backend = factory(parent)
            print(f"[{APP_NAME}] motor de áudio: {backend.name}")
            return backend
        except Exception:
            continue
    return QtBackend(parent)


class Player(QObject):
    trackChanged = Signal(object)
    stateChanged = Signal(str)
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    queueChanged = Signal()
    errorRaised = Signal(str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.queue: list[Track] = []
        self.index = -1
        self.shuffle = bool(cfg.get("shuffle", False))
        self.repeat = cfg.get("repeat", "off")
        self._pre_shuffle_order: list[Track] | None = None
        self._volume = float(cfg.get("volume", 0.75))
        self._fade = 1.0
        self._fade_target = 1.0
        self._fade_step_size = 0.0
        self._fading_out = False

        self.backend = build_backend(self)
        self.backend.positionChanged.connect(self._on_position)
        self.backend.durationChanged.connect(self.durationChanged)
        self.backend.finished.connect(self._on_finished)
        self.backend.errorRaised.connect(self.errorRaised)

        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(40)
        self._fade_timer.timeout.connect(self._fade_step)
        self._apply_volume()

        if self.shuffle:
            self._shuffle_queue()

    # -- fila
    def set_queue(self, tracks, start_index=0):
        self.queue = list(tracks)
        self.index = -1
        self._pre_shuffle_order = list(self.queue) if self.shuffle else None
        if self.shuffle:
            self._shuffle_queue()
        self.queueChanged.emit()
        if self.queue:
            self.play_index(max(0, min(start_index, len(self.queue) - 1)))

    def enqueue(self, tracks):
        self.queue.extend(tracks)
        if self.shuffle:
            tail = len(self.queue) - len(tracks)
            head = self.queue[:tail]
            new = self.queue[tail:]
            random.shuffle(new)
            self.queue = head + new
        self.queueChanged.emit()

    def clear_queue(self):
        self.stop()
        self.queue.clear()
        self.index = -1
        self.queueChanged.emit()

    # -- shuffle
    def _shuffle_queue(self):
        if len(self.queue) < 2:
            return
        if 0 <= self.index < len(self.queue):
            current = self.queue[self.index]
            rest = [t for i, t in enumerate(self.queue) if i != self.index]
            random.shuffle(rest)
            self.queue = rest[:self.index] + [current] + rest[self.index:]
        else:
            random.shuffle(self.queue)

    def set_shuffle(self, enabled: bool):
        """Liga/desliga o aleatório embaralhando a fila na hora, sem parar o som."""
        if enabled == self.shuffle:
            return
        current = self.queue[self.index] if 0 <= self.index < len(self.queue) else None

        if enabled:
            self._pre_shuffle_order = list(self.queue)
            self.shuffle = True
            self._shuffle_queue()
        else:
            self.shuffle = False
            if self._pre_shuffle_order:
                present = {t.path for t in self.queue}
                restored = [t for t in self._pre_shuffle_order if t.path in present]
                known = {t.path for t in restored}
                restored += [t for t in self.queue if t.path not in known]
                self.queue = restored
                self.index = next(
                    (i for i, t in enumerate(restored) if current and t.path == current.path), -1
                )
                self._pre_shuffle_order = None

        self.cfg["shuffle"] = self.shuffle
        self.queueChanged.emit()

    # -- reprodução
    def play_index(self, index, fade_in=True):
        if not (0 <= index < len(self.queue)):
            return
        self.index = index
        track = self.queue[index]
        self.backend.load(track.path)
        self._fading_out = False
        cross = self.cfg.get("crossfade_ms", 0)
        if fade_in and cross > 0:
            self._fade = 0.0
            self._start_fade(1.0, cross // 2)
        else:
            self._fade = 1.0
            self._apply_volume()
        self.backend.play()
        self.trackChanged.emit(track)
        self.stateChanged.emit("playing")

    def toggle_play(self):
        if self.index < 0 and self.queue:
            self.play_index(0)
        elif self._playing():
            self.backend.pause()
            self.stateChanged.emit("paused")
        else:
            self.backend.play()
            self.stateChanged.emit("playing")

    def stop(self):
        self.backend.stop()
        self._fade = 1.0
        self._apply_volume()
        self.stateChanged.emit("stopped")

    def _playing(self):
        return self.backend.is_playing()

    def next_track(self, auto=False):
        if not self.queue:
            return
        nxt = self.index + 1
        if nxt >= len(self.queue):
            if self.repeat == "all" or not auto:
                if self.shuffle:
                    self._shuffle_queue()
                    self.index = -1
                    nxt = 0
                else:
                    nxt = 0
            else:
                self.stop()
                return
        self.play_index(nxt)

    def prev_track(self):
        if not self.queue:
            return
        if self.current_position() > 3000:
            self.seek(0)
            return
        prev = self.index - 1
        if prev < 0:
            prev = len(self.queue) - 1 if self.repeat == "all" else 0
        self.play_index(prev)

    def seek(self, ms):
        self.backend.set_position(ms)
        self.positionChanged.emit(ms)

    def current_position(self):
        try:
            return self.backend.raw_position()
        except Exception:
            return 0

    def current_duration(self):
        try:
            return self.backend.raw_duration()
        except Exception:
            return 0

    # -- volume / fade
    def set_volume(self, vol):
        self._volume = max(0.0, min(1.0, vol))
        self.cfg["volume"] = self._volume
        self._apply_volume()

    def volume(self):
        return self._volume

    def _apply_volume(self):
        self.backend.set_volume(self._volume * self._fade)

    def _start_fade(self, target, duration_ms):
        self._fade_target = target
        steps = max(1, duration_ms // self._fade_timer.interval())
        self._fade_step_size = (target - self._fade) / steps
        self._fade_timer.start()

    def _fade_step(self):
        if abs(self._fade - self._fade_target) <= abs(self._fade_step_size):
            self._fade = self._fade_target
            self._fade_timer.stop()
        else:
            self._fade += self._fade_step_size
        self._apply_volume()

    def _on_position(self, pos):
        self.positionChanged.emit(pos)
        cross = self.cfg.get("crossfade_ms", 0)
        if cross <= 0 or self._fading_out:
            return
        dur = self.current_duration()
        if dur > 0 and dur - pos <= cross // 2:
            self._fading_out = True
            self._start_fade(0.0, cross // 2)

    def _on_finished(self):
        if self.repeat == "one" and self.index >= 0:
            self.play_index(self.index, fade_in=False)
        else:
            self.next_track(auto=True)


# --------------------------------------------------------------------------
# interface
# --------------------------------------------------------------------------

COLUMNS = [
    ("title", "Título"), ("artist", "Artista"), ("album", "Álbum"),
    ("genre", "Gênero"), ("year", "Ano"), ("duration", "Duração"),
]

INFO_FIELDS = (
    "Álbum", "Gênero", "Ano", "Faixa", "Duração",
    "Formato", "Bitrate", "Amostragem", "Canais", "Tamanho",
)


def fmt_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class NumericItem(QTableWidgetItem):
    def __lt__(self, other):
        a = self.data(Qt.UserRole + 1)
        b = other.data(Qt.UserRole + 1)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


class ScanWorker(QThread):
    progress = Signal(str)
    done = Signal(int)
    failed = Signal(str)

    def __init__(self, dirs, parent=None):
        super().__init__(parent)
        self.dirs = list(dirs)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total, buffer = 0, []
        try:
            for root in self.dirs:
                if not Path(root).is_dir():
                    continue
                for path in iter_audio_files(root):
                    if self._stop:
                        return
                    buffer.append(read_tags(path))
                    total += 1
                    if len(buffer) >= 100:
                        upsert_tracks(buffer)
                        buffer.clear()
                        self.progress.emit(f"Indexando... {total} arquivos")
            upsert_tracks(buffer)
            self.done.emit(total)
        except Exception as exc:
            self.failed.emit(str(exc))


class DetailsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cover_cache: dict[str, bytes | None] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.cover = QLabel("♪")
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setFixedHeight(210)
        self.cover.setStyleSheet(
            "border: 1px solid rgba(140,150,180,0.35); border-radius: 8px; font-size: 52px;"
        )
        layout.addWidget(self.cover)

        self.title = QLabel("Nada selecionado")
        self.title.setWordWrap(True)
        font = self.title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.title.setFont(font)
        layout.addWidget(self.title)

        self.artist = QLabel("")
        self.artist.setWordWrap(True)
        layout.addWidget(self.artist)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(3)
        self._values: dict[str, QLabel] = {}
        for row, name in enumerate(INFO_FIELDS):
            key = QLabel(name)
            key.setStyleSheet("opacity: 0.55;")
            value = QLabel("—")
            value.setWordWrap(True)
            grid.addWidget(key, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self._values[name] = value
        layout.addLayout(grid)
        layout.addStretch(1)

        self.path = QLabel("")
        self.path.setWordWrap(True)
        self.path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path.setStyleSheet("font-size: 11px; opacity: 0.6;")
        layout.addWidget(self.path)

    def _cover_bytes(self, path: str) -> bytes | None:
        if path not in self._cover_cache:
            if len(self._cover_cache) > 300:
                self._cover_cache.clear()
            self._cover_cache[path] = extract_cover(path)
        return self._cover_cache[path]

    def show_track(self, track: Track | None):
        if track is None:
            self.title.setText("Nada selecionado")
            self.artist.setText("")
            self.path.setText("")
            for label in self._values.values():
                label.setText("—")
            self._set_cover(None)
            return

        self.title.setText(track.title)
        self.artist.setText(track.artist or "Artista desconhecido")
        self.path.setText(track.path)

        info = track_info(track.path)
        values = {
            "Álbum": track.album or "—",
            "Gênero": track.genre or "—",
            "Ano": str(track.year) if track.year else "—",
            "Faixa": str(track.track_no) if track.track_no else "—",
            "Duração": fmt_time(track.duration) if track.duration else "—",
            "Formato": info["format"] or "—",
            "Bitrate": info["bitrate"] or "—",
            "Amostragem": info["sample_rate"] or "—",
            "Canais": info["channels"] or "—",
            "Tamanho": info["size"] or "—",
        }
        for name, label in self._values.items():
            label.setText(values.get(name, "—"))

        self._set_cover(self._cover_bytes(track.path))

    def _set_cover(self, data: bytes | None):
        if data:
            pixmap = QPixmap()
            if pixmap.loadFromData(data) and not pixmap.isNull():
                self.cover.setPixmap(
                    pixmap.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self.cover.setPixmap(QPixmap())
        self.cover.setText("♪")


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Configurações")
        self.resize(560, 620)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.dirs = QListWidget()
        self.dirs.setMaximumHeight(110)
        for d in cfg.get("music_dirs", []):
            self.dirs.addItem(d)
        btn_add = QPushButton("Adicionar pasta")
        btn_rem = QPushButton("Remover selecionada")
        btn_add.clicked.connect(self._add_dir)
        btn_rem.clicked.connect(self._remove_dir)
        row = QHBoxLayout(); row.addWidget(btn_add); row.addWidget(btn_rem)
        holder = QWidget(); holder.setLayout(row)
        form.addRow("Pastas de música", self.dirs)
        form.addRow("", holder)

        self.crossfade = QSpinBox(); self.crossfade.setRange(0, 12000)
        self.crossfade.setSingleStep(250); self.crossfade.setSuffix(" ms")
        self.crossfade.setValue(int(cfg.get("crossfade_ms", 0)))
        form.addRow("Crossfade entre faixas", self.crossfade)

        self.fade = QSpinBox(); self.fade.setRange(0, 3000)
        self.fade.setSingleStep(50); self.fade.setSuffix(" ms")
        self.fade.setValue(int(cfg.get("fade_ms", 200)))
        form.addRow("Duração do fade", self.fade)

        self.theme = QComboBox(); self.theme.addItems(available_themes())
        self.theme.setCurrentText(cfg.get("theme", "lily"))
        form.addRow("Tema", self.theme)

        self.shuffle = QCheckBox("Iniciar com aleatório ligado")
        self.shuffle.setChecked(bool(cfg.get("shuffle", False)))
        form.addRow("", self.shuffle)
        layout.addLayout(form)

        icon_row = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setPixmap(app_icon(cfg).pixmap(48, 48))
        icon_row.addWidget(self.icon_label)
        btn_icon = QPushButton("Escolher ícone do app")
        btn_icon.clicked.connect(self._pick_icon)
        icon_row.addWidget(btn_icon)
        btn_reset = QPushButton("Restaurar padrão")
        btn_reset.clicked.connect(self._reset_icon)
        icon_row.addWidget(btn_reset)
        icon_row.addStretch(1)
        icon_holder = QWidget(); icon_holder.setLayout(icon_row)
        layout.addWidget(icon_holder)

        layout.addWidget(QLabel("Atalhos — clique e pressione a combinação desejada"))
        sc_form = QFormLayout()
        self.shortcut_editors = {}
        for key, seq in cfg.get("shortcuts", {}).items():
            editor = QKeySequenceEdit(QKeySequence(seq))
            self.shortcut_editors[key] = editor
            sc_form.addRow(SHORTCUT_LABELS.get(key, key), editor)
        layout.addLayout(sc_form)

        self.prune = QCheckBox("Remover da biblioteca faixas que não existem mais")
        layout.addWidget(self.prune)

        btn_install = QPushButton("Criar / atualizar atalho no sistema")
        btn_install.clicked.connect(self._install)
        layout.addWidget(btn_install)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Escolher pasta de música")
        if d:
            self.dirs.addItem(d)

    def _remove_dir(self):
        for item in self.dirs.selectedItems():
            self.dirs.takeItem(self.dirs.row(item))

    def _pick_icon(self):
        filters = "Imagens (*.png *.jpg *.jpeg *.svg *.ico *.bmp *.webp)"
        path, _ = QFileDialog.getOpenFileName(self, "Escolher ícone", "", filters)
        if not path:
            return
        if install_custom_icon(path, self.cfg):
            self.icon_label.setPixmap(app_icon(self.cfg).pixmap(48, 48))
        else:
            QMessageBox.warning(self, "Ícone inválido", "Não consegui ler essa imagem.")

    def _reset_icon(self):
        self.cfg.pop("icon_path", None)
        save_config(self.cfg)
        self.icon_label.setPixmap(app_icon(self.cfg).pixmap(48, 48))

    def _install(self):
        ok, info = install_shortcut(self.cfg)
        if ok:
            destino = "Start Menu" if IS_WINDOWS else "menu do sistema"
            QMessageBox.information(
                self, "Atalho criado",
                f"Pronto. Procure por \"{APP_NAME}\" no {destino}.",
            )
        else:
            QMessageBox.warning(self, "Falha", info)

    def result_config(self) -> dict:
        self.cfg["music_dirs"] = [self.dirs.item(i).text() for i in range(self.dirs.count())]
        self.cfg["crossfade_ms"] = self.crossfade.value()
        self.cfg["fade_ms"] = self.fade.value()
        self.cfg["theme"] = self.theme.currentText()
        self.cfg["shuffle"] = self.shuffle.isChecked()
        for key, editor in self.shortcut_editors.items():
            self.cfg["shortcuts"][key] = editor.keySequence().toString()
        return self.cfg


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict):
        super().__init__()
        init_db()
        self.cfg = cfg
        self._shortcuts: dict[str, QShortcut] = {}
        self._view = ("all", None)
        self._rows: list[Track] = []
        self._seeking = False
        self._worker: ScanWorker | None = None

        self.player = Player(cfg, self)
        self._build_ui()
        self._wire_player()
        self._apply_theme(cfg.get("theme", "lily"))
        self._install_shortcuts()
        self._fit_window()
        self.setWindowIcon(app_icon(cfg))
        self.setWindowTitle(f"{APP_NAME} {VERSION}")

        self.reload_sidebar()
        self.reload_tracks()
        self._sync_queue_view()
        self._update_mode_buttons()

    def _fit_window(self):
        saved = self.cfg.get("window", {})
        w = int(saved.get("w", 1080))
        h = int(saved.get("h", 660))
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            w = min(w, int(screen.width() * 0.96))
            h = min(h, int(screen.height() * 0.94))
        self.resize(max(880, w), max(560, h))

    # -- montagem
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar título, artista, álbum ou gênero...")
        self.search.textChanged.connect(self._on_search)
        top.addWidget(self.search, 1)

        self.theme_box = QComboBox()
        self.theme_box.addItems(available_themes())
        self.theme_box.setCurrentText(self.cfg.get("theme", "lily"))
        self.theme_box.currentTextChanged.connect(self._apply_theme)
        top.addWidget(self.theme_box)

        btn_add = QPushButton("Adicionar pasta"); btn_add.clicked.connect(self.add_folder)
        top.addWidget(btn_add)
        btn_scan = QPushButton("Resscanear"); btn_scan.clicked.connect(self.rescan)
        top.addWidget(btn_scan)
        btn_cfg = QPushButton("Configurações"); btn_cfg.clicked.connect(self.open_settings)
        top.addWidget(btn_cfg)
        outer.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        side_box = QWidget()
        side_layout = QVBoxLayout(side_box)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(4)

        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setMinimumWidth(180)
        self.sidebar.itemSelectionChanged.connect(self._on_sidebar)
        self.sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self._sidebar_menu)
        self.sidebar.itemDoubleClicked.connect(self._rename_from_double_click)
        side_layout.addWidget(self.sidebar, 1)

        new_pl = QPushButton("+ Nova playlist")
        new_pl.clicked.connect(self.create_playlist_dialog)
        side_layout.addWidget(new_pl)
        splitter.addWidget(side_box)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._play_row)
        self.table.itemSelectionChanged.connect(self._on_table_selection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        splitter.addWidget(self.table)

        self.side = QTabWidget()
        self.side.setMinimumWidth(280)

        self.details = DetailsPanel()
        self.side.addTab(self.details, "Faixa")

        self.queue = QListWidget()
        self.queue.setDragDropMode(QAbstractItemView.InternalMove)
        self.queue.doubleClicked.connect(lambda i: self.player.play_index(i.row()))
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._queue_menu)
        self.queue.model().rowsMoved.connect(self._on_queue_reorder)
        self.side.addTab(self.queue, "Fila")

        splitter.addWidget(self.side)
        splitter.setSizes([190, 600, 290])
        outer.addWidget(splitter, 1)

        bar = QHBoxLayout()
        info = QVBoxLayout(); info.setSpacing(0)
        self.now_title = QLabel("Nada tocando"); self.now_title.setStyleSheet("font-weight: 600;")
        self.now_sub = QLabel(""); self.now_sub.setStyleSheet("font-size: 11px; opacity: 0.7;")
        info.addWidget(self.now_title); info.addWidget(self.now_sub)
        info_box = QWidget(); info_box.setLayout(info); info_box.setMinimumWidth(200)
        bar.addWidget(info_box)

        self.seek = QSlider(Qt.Horizontal); self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_released)
        bar.addWidget(self.seek, 1)

        self.time_label = QLabel("0:00 / 0:00")
        bar.addWidget(self.time_label)

        self.btn_prev = QPushButton("⏮"); self.btn_play = QPushButton("▶")
        self.btn_next = QPushButton("⏭"); self.btn_shuffle = QPushButton("🔀")
        self.btn_repeat = QPushButton("🔁")
        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_shuffle, self.btn_repeat):
            b.setFixedWidth(40)
            bar.addWidget(b)
        self.btn_prev.clicked.connect(self.player.prev_track)
        self.btn_play.clicked.connect(self.player.toggle_play)
        self.btn_next.clicked.connect(lambda: self.player.next_track())
        self.btn_shuffle.clicked.connect(self._toggle_shuffle)
        self.btn_repeat.clicked.connect(self._cycle_repeat)

        self.vol = QSlider(Qt.Horizontal); self.vol.setRange(0, 100)
        self.vol.setValue(int(self.cfg.get("volume", 0.75) * 100))
        self.vol.setFixedWidth(110)
        self.vol.valueChanged.connect(lambda v: self.player.set_volume(v / 100))
        bar.addWidget(self.vol)

        outer.addLayout(bar)

    def _wire_player(self):
        self.player.trackChanged.connect(self._on_track_changed)
        self.player.positionChanged.connect(self._on_position)
        self.player.stateChanged.connect(self._on_state)
        self.player.queueChanged.connect(self._sync_queue_view)
        self.player.errorRaised.connect(lambda m: self.statusBar().showMessage(m, 6000))

    # -- barra lateral
    def reload_sidebar(self):
        self.sidebar.clear()
        all_item = QTreeWidgetItem(["Todas as faixas"])
        all_item.setData(0, Qt.UserRole, ("all", None))
        self.sidebar.addTopLevelItem(all_item)

        for field, label in (("artist", "Artistas"), ("album", "Álbuns"), ("genre", "Gêneros")):
            parent = QTreeWidgetItem([label])
            for value in distinct(field):
                child = QTreeWidgetItem([value])
                child.setData(0, Qt.UserRole, (field, value))
                parent.addChild(child)
            self.sidebar.addTopLevelItem(parent)

        folders = QTreeWidgetItem(["Pastas"])
        for d in self.cfg.get("music_dirs", []):
            child = QTreeWidgetItem([d])
            child.setData(0, Qt.UserRole, ("folder", d))
            folders.addChild(child)
        self.sidebar.addTopLevelItem(folders)

        playlists = QTreeWidgetItem(["Playlists"])
        playlists.setData(0, Qt.UserRole, ("playlists_root", None))
        for pid, name in list_playlists():
            child = QTreeWidgetItem([name])
            child.setData(0, Qt.UserRole, ("playlist", str(pid)))
            playlists.addChild(child)
        self.sidebar.addTopLevelItem(playlists)

        all_item.setSelected(True)
        playlists.setExpanded(True)

    def _on_sidebar(self):
        items = self.sidebar.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.UserRole)
        if data and data[0] != "playlists_root":
            self._view = (data[0], data[1])
            self.reload_tracks()

    def _sidebar_menu(self, pos):
        item = self.sidebar.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        menu = QMenu(self)

        if data and data[0] == "playlist":
            pid = int(data[1])
            menu.addAction("Tocar playlist", lambda: self.play_playlist(pid))
            menu.addAction("Renomear", lambda: self.rename_playlist_dialog(pid, item))
            menu.addAction("Adicionar faixas selecionadas",
                           lambda: self.add_selection_to_playlist(pid))
            menu.addSeparator()
            menu.addAction("Excluir playlist", lambda: self.delete_playlist(pid))
        else:
            menu.addAction("Nova playlist", self.create_playlist_dialog)
            if data and data[0] == "playlists_root":
                menu.addAction("Salvar fila atual como playlist",
                               lambda: self.save_queue_as_playlist())

        menu.exec(self.sidebar.viewport().mapToGlobal(pos))

    def _rename_from_double_click(self, item, _column):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "playlist":
            self.rename_playlist_dialog(int(data[1]), item)

    # -- playlists
    def create_playlist_dialog(self):
        name, ok = QInputDialog.getText(self, "Nova playlist", "Nome da playlist:")
        if not ok or not name.strip():
            return
        create_playlist(name.strip())
        self.reload_sidebar()

    def rename_playlist_dialog(self, playlist_id: int, item: QTreeWidgetItem | None = None):
        atual = item.text(0) if item else ""
        name, ok = QInputDialog.getText(
            self, "Renomear playlist", "Novo nome:", QLineEdit.Normal, atual
        )
        if not ok or not name.strip():
            return
        if not rename_playlist(playlist_id, name.strip()):
            QMessageBox.warning(self, "Nome em uso", "Já existe uma playlist com esse nome.")
            return
        self.reload_sidebar()

    def delete_playlist(self, playlist_id: int):
        if QMessageBox.question(self, "Excluir", "Excluir esta playlist?") != QMessageBox.Yes:
            return
        delete_playlist(playlist_id)
        if self._view == ("playlist", str(playlist_id)):
            self._view = ("all", None)
        self.reload_sidebar()
        self.reload_tracks()

    def add_selection_to_playlist(self, playlist_id: int):
        tracks = self._selected_tracks()
        if not tracks:
            QMessageBox.information(self, "Nada selecionado", "Selecione faixas na tabela primeiro.")
            return
        add_to_playlist(playlist_id, [t.path for t in tracks])
        self.statusBar().showMessage(f"{len(tracks)} faixas adicionadas")

    def save_queue_as_playlist(self):
        if not self.player.queue:
            QMessageBox.information(self, "Fila vazia", "Não há nada na fila para salvar.")
            return
        name, ok = QInputDialog.getText(self, "Salvar fila", "Nome da playlist:")
        if not ok or not name.strip():
            return
        pid = create_playlist(name.strip())
        add_to_playlist(pid, [t.path for t in self.player.queue])
        self.reload_sidebar()
        self.statusBar().showMessage("Fila salva como playlist")

    def play_playlist(self, playlist_id: int):
        tracks = playlist_tracks(playlist_id)
        if tracks:
            self.player.set_queue(tracks, 0)

    # -- tabela
    def reload_tracks(self):
        text = self.search.text().strip()
        if self._view[0] == "playlist" and self._view[1]:
            tracks = playlist_tracks(int(self._view[1]))
            if text:
                needle = text.lower()
                tracks = [
                    t for t in tracks
                    if needle in f"{t.title} {t.artist} {t.album} {t.genre}".lower()
                ]
            self._rows = tracks
        else:
            self._rows = search_tracks(text, *self._view)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))
        for row, track in enumerate(self._rows):
            values = {
                "title": track.title, "artist": track.artist, "album": track.album,
                "genre": track.genre, "year": str(track.year or ""),
                "duration": fmt_time(track.duration),
            }
            for col, (key, _label) in enumerate(COLUMNS):
                item = NumericItem(values[key]) if key in {"year", "duration"} else QTableWidgetItem(values[key])
                if key == "year":
                    item.setData(Qt.UserRole + 1, track.year)
                elif key == "duration":
                    item.setData(Qt.UserRole + 1, track.duration)
                if col == 0:
                    item.setData(Qt.UserRole, track.path)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.statusBar().showMessage(f"{len(self._rows)} faixas")

    def _track_at_row(self, row: int) -> Track | None:
        item = self.table.item(row, 0)
        if item is None:
            return None
        path = item.data(Qt.UserRole)
        return next((t for t in self._rows if t.path == path), None)

    def _selected_tracks(self) -> list[Track]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [t for t in (self._track_at_row(r) for r in rows) if t]

    def _on_search(self):
        QTimer.singleShot(180, self.reload_tracks)

    def _on_table_selection(self):
        tracks = self._selected_tracks()
        if tracks:
            self.details.show_track(tracks[0])

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Escolher pasta de música")
        if not d:
            return
        if d not in self.cfg["music_dirs"]:
            self.cfg["music_dirs"].append(d)
            save_config(self.cfg)
        self.reload_sidebar()
        self.rescan()

    def rescan(self):
        if not self.cfg.get("music_dirs"):
            QMessageBox.information(self, "Sem pastas", "Adicione uma pasta de música primeiro.")
            return
        if self._worker and self._worker.isRunning():
            return
        self.statusBar().showMessage("Varrendo biblioteca...")
        self._worker = ScanWorker(self.cfg["music_dirs"], self)
        self._worker.progress.connect(lambda m: self.statusBar().showMessage(m))
        self._worker.done.connect(self._scan_done)
        self._worker.failed.connect(lambda e: QMessageBox.warning(self, "Erro na varredura", e))
        self._worker.start()

    def _scan_done(self, count: int):
        self.statusBar().showMessage(f"{count} arquivos indexados")
        self.reload_sidebar()
        self.reload_tracks()

    # -- reprodução
    def _play_row(self, index):
        track = self._track_at_row(index.row())
        if track is None:
            return
        self.player.set_queue(self._rows, self._rows.index(track))

    def _on_queue_reorder(self, *_):
        by_path = {t.path: t for t in self.player.queue}
        new_queue = []
        for i in range(self.queue.count()):
            path = self.queue.item(i).data(Qt.UserRole)
            if path in by_path:
                new_queue.append(by_path.pop(path))
        if not new_queue:
            return
        current = self.player.queue[self.player.index] if 0 <= self.player.index < len(self.player.queue) else None
        self.player.queue = new_queue
        self.player.index = next(
            (i for i, t in enumerate(new_queue) if current and t.path == current.path), -1
        )
        self.player._pre_shuffle_order = list(new_queue)

    def _sync_queue_view(self):
        self.queue.clear()
        for i, track in enumerate(self.player.queue, start=1):
            item = QListWidgetItem(f"{i}. {track.display}")
            item.setData(Qt.UserRole, track.path)
            self.queue.addItem(item)
        if 0 <= self.player.index < self.queue.count():
            self.queue.setCurrentRow(self.player.index)

    def _on_track_changed(self, track):
        if track is None:
            self.now_title.setText("Nada tocando"); self.now_sub.setText("")
            return
        self.now_title.setText(track.title)
        self.now_sub.setText(f"{track.artist} — {track.album}" if track.artist else track.album)
        self.details.show_track(track)
        self.side.setCurrentWidget(self.details)
        self._sync_queue_view()

    def _on_position(self, pos):
        dur = self.player.current_duration()
        if not self._seeking and dur > 0:
            self.seek.setValue(int(pos / dur * 1000))
        self.time_label.setText(f"{fmt_time(pos // 1000)} / {fmt_time(dur // 1000)}")

    def _on_state(self, state):
        self.btn_play.setText("⏸" if state == "playing" else "▶")

    def _seek_released(self):
        self._seeking = False
        dur = self.player.current_duration()
        if dur > 0:
            self.player.seek(int(self.seek.value() / 1000 * dur))

    def _nudge_volume(self, delta):
        new = max(0.0, min(1.0, self.player.volume() + delta))
        self.player.set_volume(new)
        self.vol.setValue(int(new * 100))

    def _toggle_shuffle(self):
        self.player.set_shuffle(not self.player.shuffle)
        self.cfg["shuffle"] = self.player.shuffle
        save_config(self.cfg)
        self._update_mode_buttons()
        if self.player.shuffle:
            self.statusBar().showMessage("Aleatório ligado — fila embaralhada", 3000)
        else:
            self.statusBar().showMessage("Aleatório desligado — ordem original restaurada", 3000)

    def _cycle_repeat(self):
        order = ["off", "all", "one"]
        self.player.repeat = order[(order.index(self.player.repeat) + 1) % 3]
        self.cfg["repeat"] = self.player.repeat
        self._update_mode_buttons()

    def _update_mode_buttons(self):
        self.btn_shuffle.setProperty("active", self.player.shuffle)
        repolish(self.btn_shuffle)
        self.btn_repeat.setText({"off": "🔁", "all": "🔁", "one": "🔂"}[self.player.repeat])
        self.btn_repeat.setProperty("active", self.player.repeat != "off")
        repolish(self.btn_repeat)

    def _clear_queue(self):
        self.player.clear_queue()

    def _focus_search(self):
        self.search.setFocus(); self.search.selectAll()

    # -- menus
    def _table_menu(self, pos):
        row = self.table.rowAt(pos.y())
        track = self._track_at_row(row) if row >= 0 else None
        if track is None:
            return
        start = self._rows.index(track)
        selection = self._selected_tracks()
        menu = QMenu(self)
        menu.addAction("Tocar agora", lambda: self.player.set_queue(self._rows, start))
        menu.addAction("Adicionar à fila", lambda: self.player.enqueue([track]))
        menu.addAction("Abrir pasta do arquivo", lambda: open_folder(track.path))

        playlists = menu.addMenu("Adicionar à playlist")
        entries = list_playlists()
        if entries:
            for pid, name in entries:
                playlists.addAction(name, lambda checked=False, p=pid: self._add_paths_to(p))
        else:
            playlists.addAction("(nenhuma)", lambda: None)
        playlists.addSeparator()
        playlists.addAction("Nova playlist...", self._create_and_add)

        menu.addSeparator()
        menu.addAction("Remover da biblioteca", lambda: self._remove_selected(selection))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _add_paths_to(self, playlist_id: int):
        tracks = self._selected_tracks()
        if not tracks:
            return
        add_to_playlist(playlist_id, [t.path for t in tracks])
        self.statusBar().showMessage(f"{len(tracks)} faixas adicionadas à playlist")

    def _create_and_add(self):
        tracks = self._selected_tracks()
        name, ok = QInputDialog.getText(self, "Nova playlist", "Nome da playlist:")
        if not ok or not name.strip():
            return
        pid = create_playlist(name.strip())
        add_to_playlist(pid, [t.path for t in tracks])
        self.reload_sidebar()

    def _queue_menu(self, pos):
        row = self.queue.rowAt(pos.y())
        menu = QMenu(self)
        if row >= 0:
            menu.addAction("Tocar", lambda: self.player.play_index(row))
            menu.addAction("Remover da fila", lambda: self._remove_from_queue(row))
            menu.addSeparator()
        menu.addAction("Salvar fila como playlist", self.save_queue_as_playlist)
        menu.addAction("Limpar fila", self._clear_queue)
        menu.exec(self.queue.viewport().mapToGlobal(pos))

    def _remove_from_queue(self, row: int):
        if not (0 <= row < len(self.player.queue)):
            return
        was_current = row == self.player.index
        self.player.queue.pop(row)
        if row < self.player.index:
            self.player.index -= 1
        if was_current:
            if self.player.queue:
                self.player.play_index(min(row, len(self.player.queue) - 1))
            else:
                self.player.stop()
        self.player.queueChanged.emit()

    def _remove_selected(self, tracks: list[Track]):
        if not tracks:
            return
        paths = [t.path for t in tracks]
        remove_tracks(paths)
        if self._view[0] == "playlist" and self._view[1]:
            for p in paths:
                remove_from_playlist(int(self._view[1]), p)
        self.reload_sidebar()
        self.reload_tracks()

    # -- personalização
    def _apply_theme(self, name: str):
        qss = theme_qss(name)
        if qss:
            self.setStyleSheet(qss)
        self.cfg["theme"] = name
        if hasattr(self, "theme_box") and self.theme_box.currentText() != name:
            self.theme_box.setCurrentText(name)
        if hasattr(self, "btn_shuffle"):
            self._update_mode_buttons()

    def _install_shortcuts(self):
        for sc in self._shortcuts.values():
            sc.setParent(None)
        self._shortcuts.clear()
        actions = {
            "play_pause": self.player.toggle_play,
            "next": lambda: self.player.next_track(),
            "previous": self.player.prev_track,
            "volume_up": lambda: self._nudge_volume(0.05),
            "volume_down": lambda: self._nudge_volume(-0.05),
            "search": self._focus_search,
            "toggle_shuffle": self._toggle_shuffle,
            "toggle_repeat": self._cycle_repeat,
            "clear_queue": self._clear_queue,
        }
        for key, seq in self.cfg.get("shortcuts", {}).items():
            cb = actions.get(key)
            if not cb or not seq:
                continue
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(cb)
            self._shortcuts[key] = sc

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.result_config()
            save_config(self.cfg)
            self.setWindowIcon(app_icon(self.cfg))
            self._apply_theme(self.cfg["theme"])
            self._install_shortcuts()
            self.player.set_shuffle(self.cfg["shuffle"])
            if dlg.prune.isChecked():
                removed = prune_missing()
                self.statusBar().showMessage(f"{removed} faixas inexistentes removidas")
            self.reload_sidebar()
            self.reload_tracks()
            self.rescan()

    def closeEvent(self, event):
        self.cfg["window"] = {"w": self.width(), "h": self.height()}
        self.cfg["volume"] = self.player.volume()
        save_config(self.cfg)
        self.player.stop()
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(1500)
        super().closeEvent(event)


# --------------------------------------------------------------------------
# entrada
# --------------------------------------------------------------------------

def main() -> int:
    if "--version" in sys.argv:
        print(f"{APP_NAME} {VERSION}")
        return 0

    if "--uninstall" in sys.argv:
        uninstall_shortcut()
        print("Atalho removido.")
        return 0

    if "--build" in sys.argv:
        return build_app()

    if "--ci" in sys.argv:
        return write_ci()

    cfg = load_config()

    if "--install" in sys.argv:
        ok, info = install_shortcut(cfg)
        if ok:
            print(f"Atalho criado em: {info}")
            return 0
        print(f"Falhou: {info}")
        return 1

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon(cfg))

    window = MainWindow(cfg)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())