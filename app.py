"""Set in Stone Character Board — post to Discord as a character via webhook."""

import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QByteArray, QEvent, QMimeData, QObject, QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, QThread, QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QColor, QDrag, QFont, QFontDatabase, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPalette,
    QActionGroup, QImage, QPen, QPixmap, QPolygonF, QShortcut, QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGraphicsOpacityEffect, QHBoxLayout, QInputDialog, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QToolButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

import catalog
import discord_client
import servers

ROOT = Path(__file__).resolve().parent
CHANNELS_FILE = ROOT / "channel_list.json"
SETTINGS_FILE = ROOT / "settings.json"
HISTORY_FILE = ROOT / "history.json"
SERVER_ICONS_DIR = ROOT / "server_icons"
ICON_FILE = ROOT / "app_icon.ico"
BANNER_FILE = ROOT / "Promised_One's_Army_banner.webp"
FONTS_DIR = ROOT / "fonts"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.webp)"
CHARACTER_MIME = "application/x-set-in-stone-character"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# ---- Grimoire theme ---------------------------------------------------

INK = "#15120e"        # main background
NAV = "#1a1611"        # faction rail
PANEL = "#1e1a14"      # compose panel
BAR = "#0f0d0a"        # header bar
RAISED = "#2b241a"     # selected / hovered rows
LINE = "#3a3226"
LINE_HI = "#5a4d38"
GOLD = "#c9a45c"
GOLD_HI = "#e3c27f"
TEXT = "#eadfc8"
MUTED = "#a8987a"
PARCHMENT = "#ece2cc"
PARCHMENT_TEXT = "#2a2116"
SEAL = "#8e2b22"
SEAL_HI = "#a8352a"

FACTION_COLORS = {
    "Fiery Mane": "#7a1f1f",
    "Gods of Dagda": "#24373a",  # Kalla's card colour, also the backdrop behind the gods' avatars
    "House Lamine": "#4b3466",
    "Kingdom of Arago": "#2f5d4f",
    "Linaria's Dewdrops": "#2e5e5a",
    "Megaira's Beacon": "#7d6a1e",
    "Ribeira Winds": "#2c4a8a",
    "Rose Tempest": "#7a2450",
    "Tale of the Moon": "#5d6b2a",
    "Temple Army": "#6b5a43",
    "Unaffiliated": "#22393b",
    "Bridal Party of the Pale Raven": "#b2b0ac",
}

VIEWS = {"classic": "Classic", "tarot": "Tarot Spread"}
LOG_LIMIT = 200  # messages remembered per channel for Edit Mode
FAVORITES = "__favorites__"
ALL = "__all__"
# Factions in this order first; any others (e.g. new folders) follow alphabetically.
FACTION_ORDER = [
    "Gods of Dagda", "Ribeira Winds", "House Lamine", "Megaira's Beacon", "Rose Tempest", "Linaria's Dewdrops",
    "Fiery Mane", "Tale of the Moon", "Bridal Party of the Pale Raven", "Kingdom of Arago", "Temple Army",
    "Unaffiliated",
]


FACTIONS_FILE = Path(__file__).resolve().parent / "factions.json"
FACTION_NAMES = {}  # folder name -> the name shown in the app, when renamed in the app
FACTION_MIME = "application/x-set-in-stone-faction"


DEFAULT_FACTION_ORDER = list(FACTION_ORDER)
FACTIONS_DATA = {"campaign_order": [], "campaigns": {}}
CURRENT_CAMPAIGN = [""]  # the campaign whose order and names FACTION_ORDER / FACTION_NAMES hold


def load_factions(campaign):
    """Apply a campaign's faction order and renames saved from the app (factions.json), if any."""
    data = load_json(FACTIONS_FILE, {})
    if "campaigns" not in data:  # older file: one order for what is now the default campaign
        legacy = {k: data[k] for k in ("order", "names") if k in data}
        data = {"campaign_order": [], "campaigns": {catalog.DEFAULT_CAMPAIGN: legacy} if legacy else {}}
    FACTIONS_DATA.clear()
    FACTIONS_DATA.update(data)
    CURRENT_CAMPAIGN[0] = campaign
    entry = data["campaigns"].get(campaign, {})
    default = DEFAULT_FACTION_ORDER if campaign == catalog.DEFAULT_CAMPAIGN else []
    FACTION_ORDER[:] = entry.get("order") or default
    FACTION_NAMES.clear()
    FACTION_NAMES.update(entry.get("names", {}))


def save_factions():
    FACTIONS_DATA["campaigns"][CURRENT_CAMPAIGN[0]] = {"order": list(FACTION_ORDER), "names": dict(FACTION_NAMES)}
    save_json(FACTIONS_FILE, {"campaign_order": FACTIONS_DATA.get("campaign_order", []),
                              "campaigns": FACTIONS_DATA["campaigns"]})


def faction_label(faction):
    return FACTION_NAMES.get(faction, faction)


def faction_key(faction):
    rank = FACTION_ORDER.index(faction) if faction in FACTION_ORDER else len(FACTION_ORDER)
    return rank, faction.lower()


SORT_KEYS = {
    # Within a faction, the order set by drag and drop; characters never placed go last, A–Z.
    "Faction": lambda c: (faction_key(c["faction"]), c.get("order", 1_000_000), c["name"].lower()),
    "Name": lambda c: c["name"].lower(),
}

DISPLAY_FAMILY = "Georgia"   # replaced by Cinzel / EB Garamond once fonts load
BODY_FAMILY = "Georgia"


def load_fonts():
    global DISPLAY_FAMILY, BODY_FAMILY
    for path in FONTS_DIR.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(path))
    families = set(QFontDatabase.families())
    if "Cinzel" in families:
        DISPLAY_FAMILY = "Cinzel"
    if "EB Garamond" in families:
        BODY_FAMILY = "EB Garamond"


def display_font(px, weight=QFont.Weight.DemiBold, spacing=108):
    f = QFont(DISPLAY_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
    return f


def body_font(px, italic=False, weight=QFont.Weight.Normal):
    f = QFont(BODY_FAMILY)
    f.setPixelSize(px)
    f.setItalic(italic)
    f.setWeight(weight)
    return f


def stylesheet():
    return f"""
    QWidget {{ color: {TEXT}; font-family: "{BODY_FAMILY}"; font-size: 16px; }}
    QMainWindow, QDialog, QMessageBox {{ background: {INK}; }}
    QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {GOLD}; padding: 4px 6px; }}

    #header {{ background: {BAR}; border-bottom: 1px solid {LINE}; }}
    #nav {{ background: {NAV}; border-right: 1px solid {LINE}; }}
    #center {{ background: {INK}; }}
    #panel {{ background: {PANEL}; border-left: 1px solid {LINE}; }}
    #composer {{ background: {NAV}; border-top: 1px solid {LINE}; }}
    QPushButton#campaignCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2e2519, stop:1 {NAV});
                                border: 1px solid {GOLD}; border-radius: 3px; padding: 0; }}
    QPushButton#campaignCard:hover, QPushButton#campaignCard:focus {{ border-color: {GOLD_HI}; }}
    #rail {{ background: {BAR}; border-right: 1px solid {LINE}; }}
    #previewCard {{ background: {INK}; border: 1px solid {LINE}; border-radius: 3px; }}
    #goldRule {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {GOLD}, stop:1 transparent);
                 max-height: 1px; min-height: 1px; border: 0; }}
    #sectionRule {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {LINE_HI}, stop:1 transparent);
                    max-height: 1px; min-height: 1px; border: 0; }}
    #muted {{ color: {MUTED}; }}
    #appTag {{ background: {GOLD}; color: {INK}; border-radius: 3px; padding: 1px 5px;
               font-family: "{DISPLAY_FAMILY}"; font-size: 10px; font-weight: 700; }}

    QScrollArea {{ background: transparent; border: 0; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {LINE_HI}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

    QLineEdit, QComboBox {{ background: {INK}; border: 1px solid {LINE}; border-radius: 2px; padding: 7px 10px;
                            selection-background-color: {GOLD}; selection-color: {INK}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {GOLD}; }}
    QComboBox::drop-down {{ border: 0; width: 22px; }}
    QComboBox#channelPicker {{ font-family: "{BODY_FAMILY}"; font-size: 16px; padding-right: 30px; }}
    QComboBox#channelPicker QAbstractItemView::item {{ padding: 7px 12px; border: 0; }}
    QComboBox#channelPicker QAbstractItemView::item:selected {{ background: {RAISED}; color: {GOLD_HI}; }}
    QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {LINE}; selection-background-color: {RAISED};
                                   selection-color: {GOLD_HI}; outline: 0; }}

    QPlainTextEdit#message {{ background: {PARCHMENT}; color: {PARCHMENT_TEXT}; border: 1px solid {GOLD};
                              border-radius: 2px; padding: 8px 10px; font-size: 18px;
                              selection-background-color: {GOLD}; selection-color: {INK}; }}

    QPushButton {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 2px; padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {GOLD}; }}
    QPushButton:focus {{ border-color: {GOLD_HI}; }}
    QPushButton#ghost {{ background: transparent; color: {GOLD}; font-size: 14px; padding: 6px 10px; }}
    QPushButton#navButton {{ background: transparent; border: 0; text-align: left; padding: 8px 10px; color: #d6c9ae; }}
    QPushButton#navButton:hover {{ background: #221d16; }}
    QPushButton#navButton:checked {{ background: {RAISED}; color: {GOLD_HI}; }}
    QPushButton#pill {{ background: transparent; border: 1px solid {LINE}; border-radius: 14px; padding: 5px 14px;
                        color: {MUTED}; font-size: 15px; }}
    QPushButton#pill:checked {{ background: {RAISED}; border-color: {GOLD}; color: {GOLD_HI}; }}
    QPushButton#pill:hover {{ border-color: {GOLD}; }}
    QPushButton#pill[compact="true"] {{ padding: 4px 11px; font-size: 14px; }}
    QPushButton#pill:disabled {{ color: #6d6252; border-color: {LINE}; }}
    QPushButton#attach {{ background: transparent; border: 2px dashed {GOLD}; color: {GOLD};
                          padding: 0; }}
    QPushButton#attach:hover {{ border-color: {GOLD_HI}; color: {GOLD_HI}; }}
    QPushButton#send {{ background: {SEAL}; color: #f6ecd6; border: 1px solid {GOLD};
                        font-family: "{DISPLAY_FAMILY}"; font-size: 15px; font-weight: 700; padding: 0 18px; }}
    QPushButton#send:hover {{ background: {SEAL_HI}; }}
    QPushButton#send:disabled {{ background: {RAISED}; color: {MUTED}; border-color: {LINE}; }}
    QCheckBox {{ color: {MUTED}; font-size: 15px; spacing: 8px; }}
    QCheckBox:checked {{ color: {GOLD_HI}; }}
    QCheckBox:disabled {{ color: #6d6252; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {LINE_HI}; background: {INK};
                            border-radius: 2px; }}
    QCheckBox::indicator:hover {{ border-color: {GOLD}; }}
    QCheckBox::indicator:checked {{ background: {GOLD}; border-color: {GOLD_HI}; }}
    QCheckBox::indicator:disabled {{ border-color: {LINE}; background: transparent; }}
    QSlider::groove:horizontal {{ height: 4px; background: {LINE}; border-radius: 2px; }}
    QSlider::sub-page:horizontal, QSlider::add-page:horizontal {{ background: {LINE}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {GOLD}; border: 1px solid {GOLD_HI}; width: 14px;
                                 margin: -6px 0; border-radius: 7px; }}
    QToolButton#remove {{ background: {INK}; border: 1px solid {GOLD}; border-radius: 9px; color: {GOLD_HI};
                          font-size: 12px; }}
    QToolButton#fileMenu {{ background: transparent; border: 0; color: {MUTED}; font-size: 15px; padding: 4px 8px; }}
    QToolButton#fileMenu:hover {{ color: {GOLD_HI}; }}
    QToolButton#fileMenu::menu-indicator {{ image: none; }}
    QToolButton#winButton, QToolButton#winClose {{ background: transparent; border: 0; color: {MUTED};
        font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets"; font-size: 10px; }}
    QToolButton#winButton:hover {{ background: {RAISED}; color: {GOLD_HI}; }}
    QToolButton#winButton:pressed {{ background: {LINE}; }}
    QToolButton#winClose:hover {{ background: #c42b1c; color: #ffffff; }}
    QToolButton#winClose:pressed {{ background: #a3261a; color: #ffffff; }}
    QToolButton#fileMenu:checked {{ background: {RAISED}; color: {GOLD_HI}; border: 1px solid {GOLD}; border-radius: 2px; }}
    #editHeading {{ color: {MUTED}; }}
    QListWidget#editList {{ background: {INK}; border: 1px solid {LINE}; border-radius: 2px; outline: 0; font-size: 15px; }}
    QListWidget#editList::item {{ padding: 5px 8px; border-bottom: 1px solid {LINE}; }}
    QListWidget#editList::item:hover {{ background: #221d16; }}
    QListWidget#editList::item:selected {{ background: {RAISED}; color: {GOLD_HI}; }}
    QListWidget#editList::item:disabled {{ color: {MUTED}; }}
    QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px; }}
    QMenu::item:selected {{ background: {RAISED}; color: {GOLD_HI}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}

    QSplitter::handle {{ background: {LINE}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 3px; min-width: 30px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    #tarot {{ background: qradialgradient(cx:0.45, cy:0.3, radius:0.85, fx:0.45, fy:0.3,
                                          stop:0 #23244a, stop:0.75 #0d0d1f, stop:1 #0b0b19); }}
    #tarot #nav {{ background: transparent; border-right: 1px solid {TAROT_LINE}; }}
    #tarot QPushButton#navButton:hover {{ background: rgba(255, 255, 255, 14); }}
    #tarot QPushButton#navButton:checked {{ background: rgba(232, 200, 114, 38); color: {TAROT_GOLD}; }}
    #tarot QPushButton#campaignCard {{ background: rgba(232, 200, 114, 22); border-color: {TAROT_BRASS}; }}
    #tarot QPushButton#campaignCard:hover {{ border-color: {TAROT_GOLD}; }}
    #tarot #rail {{ background: transparent; border: 0; }}
    #tarot #reading {{ background: rgba(11, 11, 25, 150); border-right: 1px solid {TAROT_LINE}; }}
    #tarot #deck {{ background: rgba(9, 9, 22, 170); border-top: 1px solid {TAROT_LINE}; }}
    #tarot #previewCard {{ background: rgba(20, 20, 44, 210); border-color: {TAROT_LINE}; border-radius: 6px; }}
    #tarot QLineEdit, #tarot QComboBox {{ background: {TAROT_NIGHT}; border-color: {TAROT_LINE}; }}
    #tarot QLineEdit:focus, #tarot QComboBox:focus {{ border-color: {TAROT_GOLD}; }}
    #tarot QPlainTextEdit#message {{ background: {TAROT_NIGHT}; color: {TEXT}; border: 1px solid {TAROT_BRASS};
                                     border-radius: 6px; }}
    #tarot QPushButton#pill {{ border-color: {TAROT_LINE}; color: {TAROT_LAVENDER}; }}
    #tarot QPushButton#pill:hover {{ border-color: {TAROT_GOLD}; }}
    #tarot QPushButton#pill:checked {{ background: rgba(232, 200, 114, 38); border-color: {TAROT_GOLD}; color: {TAROT_GOLD}; }}
    #tarot QPushButton#pill:disabled {{ color: #565486; border-color: #2a2950; }}
    #tarot QScrollBar::handle {{ background: {TAROT_LINE}; }}
    #tarot #editHeading {{ color: #8d87c4; }}
    #tarot QListWidget#editList {{ background: {TAROT_NIGHT}; border-color: {TAROT_LINE}; border-radius: 6px; }}
    #tarot QListWidget#editList::item {{ border-bottom-color: {TAROT_LINE}; }}
    #tarot QListWidget#editList::item:hover {{ background: rgba(255, 255, 255, 14); }}
    #tarot QListWidget#editList::item:selected {{ background: rgba(232, 200, 114, 38); color: {TAROT_GOLD}; }}
    #tarot QListWidget#editList::item:disabled {{ color: {TAROT_LAVENDER}; }}
    QPushButton#post {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {TAROT_GOLD}, stop:1 #b8923e);
                        color: {TAROT_NIGHT}; border: 0; border-radius: 4px; font-family: "{DISPLAY_FAMILY}";
                        font-size: 16px; font-weight: 700; letter-spacing: 3px; }}
    QPushButton#post:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f4d98e, stop:1 #c9a24c); }}
    QPushButton#post:focus {{ border: 1px solid #fff3cf; }}
    QPushButton#post:disabled {{ background: {TAROT_LINE}; color: #8d87c4; }}
    QStatusBar {{ background: {BAR}; color: {MUTED}; border-top: 1px solid {LINE}; font-size: 14px; }}
    QProgressDialog QLabel {{ color: {TEXT}; }}
    """


# ---- drawing helpers --------------------------------------------------

def star_polygon(center: QPointF, outer: float, inner: float) -> QPolygonF:
    points = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = -math.pi / 2 + i * math.pi / 5
        points.append(QPointF(center.x() + r * math.cos(a), center.y() + r * math.sin(a)))
    return QPolygonF(points)


def _icon(size, draw) -> QIcon:
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p, size)
    p.end()
    return QIcon(pix)


def dot_icon(color) -> QIcon:
    def draw(p, s):
        p.setPen(QPen(QColor(GOLD), 1))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(2.5, 2.5, s - 5, s - 5))
    return _icon(14, draw)


def star_icon(filled=True) -> QIcon:
    def draw(p, s):
        p.setPen(QPen(QColor(GOLD_HI), 1))
        p.setBrush(QColor(GOLD_HI) if filled else Qt.BrushStyle.NoBrush)
        p.drawPolygon(star_polygon(QPointF(s / 2, s / 2 + 0.5), s / 2 - 0.5, s / 4.5))
    return _icon(14, draw)


def plus_icon() -> QIcon:
    def draw(p, s):
        p.setPen(QPen(QColor(GOLD), 2, cap=Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s / 2, 2), QPointF(s / 2, s - 2))
        p.drawLine(QPointF(2, s / 2), QPointF(s - 2, s / 2))
    return _icon(18, draw)


def search_icon() -> QIcon:
    def draw(p, s):
        p.setPen(QPen(QColor(MUTED), 1.6))
        p.drawEllipse(QRectF(2, 2, s * 0.58, s * 0.58))
        p.drawLine(QPointF(s * 0.62, s * 0.62), QPointF(s - 2, s - 2))
    return _icon(16, draw)


def circular_pixmap(src: QPixmap, size: int, ring=None, dpr=2.0) -> QPixmap:
    out = QPixmap(int(size * dpr), int(size * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    inset = 3 if ring else 0
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    path = QPainterPath()
    path.addEllipse(rect)
    p.setClipPath(path)
    if not src.isNull():
        p.drawPixmap(rect, src, QRectF(src.rect()))
    p.setClipping(False)
    if ring:
        p.setPen(QPen(QColor(ring), 1.5))
        p.drawEllipse(QRectF(0.75, 0.75, size - 1.5, size - 1.5))
    p.end()
    return out


def cover_pixmap(path: str, w: int, h: int, dpr=2.0) -> QPixmap:
    src = QPixmap(path)
    if src.isNull():
        return src
    scaled = src.scaled(int(w * dpr), int(h * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    x, y = (scaled.width() - int(w * dpr)) // 2, (scaled.height() - int(h * dpr)) // 2
    out = scaled.copy(x, y, int(w * dpr), int(h * dpr))
    out.setDevicePixelRatio(dpr)
    return out


def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def label(text, obj=None, font=None):
    w = QLabel(text)
    if obj:
        w.setObjectName(obj)
    if font:
        w.setFont(font)
    return w


# ---- layout ------------------------------------------------------------

class FlowLayout(QLayout):
    """Lays children out left-to-right, wrapping to new rows (Qt's flow layout example)."""

    def __init__(self, parent=None, hspacing=12, vspacing=16):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def reorder(self, widgets):
        """Put the items in the order of `widgets` (which must be this layout's widgets)."""
        rank = {w: i for i, w in enumerate(widgets)}
        self._items.sort(key=lambda item: rank.get(item.widget(), len(rank)))
        self.invalidate()

    def _do_layout(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = r.x(), r.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x + hint.width() > r.right() + 1 and line > 0:
                x, y, line = r.x(), y + line + self._v, 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()


# ---- roster -------------------------------------------------------------

class PortraitTile(QWidget):
    """Round, gold-ringed portrait with a name and a favorite star."""

    clicked = pyqtSignal(str)
    favoriteToggled = pyqtSignal(str)
    menuRequested = pyqtSignal(str, QPoint)
    moveRequested = pyqtSignal(str, int)
    W, H, D = 118, 138, 96

    def __init__(self, cid, character, source: QPixmap):
        super().__init__()
        self.cid = cid
        self.name = character["name"]
        self.favorite = bool(character.get("favorite"))
        self.selected = False
        self.hover = False
        self.draggable = False
        self._press_pos = None
        self._src = source
        self._cache = None
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(f'{self.name} — {faction_label(character["faction"])}\n'
                        'Click the star to favorite (or press F) · right-click to rename')
        self.setAccessibleName(self.name)

    def set_selected(self, on):
        self.selected = on
        self.update()

    def set_favorite(self, on):
        self.favorite = on
        self.update()

    def set_name(self, name):
        self.name = name
        self.setAccessibleName(name)
        self.update()

    def set_source(self, source: QPixmap):
        self._src = source
        self._cache = None
        self.update()

    def _circle(self):
        return QRectF((self.W - self.D) / 2, 6, self.D, self.D)

    def _star_rect(self):
        c = self._circle()
        return QRectF(c.right() - 22, c.top() - 4, 26, 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        c = self._circle()
        if self.selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(201, 164, 92, 46))
            p.drawEllipse(c.adjusted(-5, -5, 5, 5))
            ring = QPen(QColor(GOLD_HI), 2)
        elif self.hover or self.hasFocus():
            ring = QPen(QColor(GOLD), 1.5)
        else:
            ring = QPen(QColor(LINE), 1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(ring)
        p.drawEllipse(c.adjusted(1, 1, -1, -1))

        inner = c.adjusted(5, 5, -5, -5)
        if self._cache is None:
            self._cache = circular_pixmap(self._src, int(inner.width()), dpr=self.devicePixelRatioF())
        p.drawPixmap(inner.topLeft(), self._cache)

        p.setFont(display_font(13, QFont.Weight.DemiBold, 104))
        p.setPen(QColor(GOLD_HI if self.selected else TEXT))
        name = p.fontMetrics().elidedText(self.name, Qt.TextElideMode.ElideRight, self.W - 4)
        p.drawText(QRectF(0, c.bottom() + 9, self.W, 24), Qt.AlignmentFlag.AlignHCenter, name)

        if self.favorite or self.hover or self.hasFocus():
            r = self._star_rect()
            p.setPen(QPen(QColor(GOLD if self.favorite else LINE_HI), 1))
            p.setBrush(QColor(INK))
            p.drawEllipse(r)
            if self.favorite:
                p.setBrush(QColor(GOLD_HI))
                p.setPen(QPen(QColor(GOLD_HI), 1))
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(MUTED), 1.3))
            p.drawPolygon(star_polygon(r.center() + QPointF(0, 0.5), 8, 3.6))

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if (self.favorite or self.hover) and self._star_rect().contains(e.position()):
            self._press_pos = None
            self.favoriteToggled.emit(self.cid)
        else:
            self._press_pos = e.position().toPoint()
            self.clicked.emit(self.cid)

    def mouseMoveEvent(self, e):
        if (not self.draggable or self._press_pos is None or not e.buttons() & Qt.MouseButton.LeftButton
                or (e.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance()):
            return
        mime = QMimeData()
        mime.setData(CHARACTER_MIME, QByteArray(self.cid.encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self._press_pos)
        self._press_pos = None
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        self._press_pos = None

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit(self.cid)
        elif e.key() == Qt.Key.Key_F:
            self.favoriteToggled.emit(self.cid)
        elif (self.draggable and e.modifiers() & Qt.KeyboardModifier.ControlModifier
              and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right)):
            self.moveRequested.emit(self.cid, -1 if e.key() == Qt.Key.Key_Left else 1)
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        self.menuRequested.emit(self.cid, e.globalPos())

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)


class DropGrid(QWidget):
    """A section's portrait grid; accepts portraits of its own faction dropped to reorder them."""

    def __init__(self, section):
        super().__init__()
        self.section = section
        self.setAcceptDrops(True)
        self.marker = QFrame(self)
        self.marker.setStyleSheet(f"background: {GOLD_HI}; border-radius: 1px;")
        self.marker.hide()

    def _dragged(self, e):
        if not e.mimeData().hasFormat(CHARACTER_MIME):
            return None
        cid = bytes(e.mimeData().data(CHARACTER_MIME)).decode()
        return cid if any(t.cid == cid for t in self.section.tiles) else None

    def _drop_index(self, pos):
        visible = [t for t in self.section.tiles if t.isVisibleTo(self)]
        for i, t in enumerate(visible):
            r = t.geometry()
            if pos.y() < r.top() or (pos.y() <= r.bottom() and pos.x() < r.center().x()):
                return i, visible
        return len(visible), visible

    def dragEnterEvent(self, e):
        if self._dragged(e):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not self._dragged(e):
            return e.ignore()
        e.acceptProposedAction()
        i, visible = self._drop_index(e.position().toPoint())
        r = visible[i].geometry() if i < len(visible) else visible[-1].geometry()
        x = r.left() - 6 if i < len(visible) else r.right() + 4
        self.marker.setGeometry(x, r.top() + 4, 3, r.height() - 8)
        self.marker.show()
        self.marker.raise_()

    def dragLeaveEvent(self, _):
        self.marker.hide()

    def dropEvent(self, e):
        self.marker.hide()
        cid = self._dragged(e)
        if not cid:
            return
        i, visible = self._drop_index(e.position().toPoint())
        if i < len(visible):
            self.section.move_before(cid, before=visible[i].cid)
        else:
            self.section.move_before(cid, after=visible[-1].cid)
        e.acceptProposedAction()


class RosterSection(QWidget):
    reordered = pyqtSignal(list)

    def __init__(self, title):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.header = QWidget()
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        title_label = label(title.upper() if title else "", font=display_font(14, QFont.Weight.DemiBold, 114))
        title_label.setStyleSheet(f"color: {GOLD};")
        rule = QFrame()
        rule.setObjectName("sectionRule")
        hl.addWidget(title_label)
        hl.addWidget(rule, 1)
        self.header.setVisible(bool(title))
        layout.addWidget(self.header)
        grid = DropGrid(self)
        self.flow = FlowLayout(grid, hspacing=10, vspacing=18)
        layout.addWidget(grid)
        self.tiles = []

    def add(self, tile):
        self.flow.addWidget(tile)
        self.tiles.append(tile)

    def move_before(self, cid, before=None, after=None):
        """Move `cid` in front of `before`, or behind `after` when dropped past the last portrait."""
        if cid in (before, after):
            return
        tile = next(t for t in self.tiles if t.cid == cid)
        self.tiles.remove(tile)
        if before:
            index = next(i for i, t in enumerate(self.tiles) if t.cid == before)
        else:
            index = next(i for i, t in enumerate(self.tiles) if t.cid == after) + 1
        self.tiles.insert(index, tile)
        self.flow.reorder(self.tiles)
        self.reordered.emit([t.cid for t in self.tiles])

    def step(self, cid, delta):
        """Move `cid` one place among the currently visible portraits (keyboard reordering)."""
        visible = [t for t in self.tiles if not t.isHidden()]
        j = next(i for i, t in enumerate(visible) if t.cid == cid) + delta
        if 0 <= j < len(visible):
            if delta < 0:
                self.move_before(cid, before=visible[j].cid)
            else:
                self.move_before(cid, after=visible[j].cid)


# ---- profile banner ------------------------------------------------------

class NavButton(QPushButton):
    """An entry in the faction rail. Faction entries can be dragged (or Ctrl+Up/Down) to reorder them."""

    moveRequested = pyqtSignal(str, int)

    def __init__(self, icon, text, mode, draggable=False):
        super().__init__(icon, text)
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setProperty("mode", mode)
        self.draggable = draggable
        self._press_pos = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self.draggable and self._press_pos is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press_pos = None
            self.setDown(False)
            mime = QMimeData()
            mime.setData(FACTION_MIME, QByteArray(self.property("mode").encode()))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(e.position().toPoint())
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(e)

    def keyPressEvent(self, e):
        if (self.draggable and e.modifiers() & Qt.KeyboardModifier.ControlModifier
                and e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)):
            self.moveRequested.emit(self.property("mode"), -1 if e.key() == Qt.Key.Key_Up else 1)
        else:
            super().keyPressEvent(e)


class NavList(QWidget):
    """Holds the rail's entries and takes faction drops, showing a gold line where one will land."""

    dropped = pyqtSignal(str, int)  # faction, insertion index among the faction entries

    def __init__(self):
        super().__init__()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(2)
        self.setAcceptDrops(True)
        self._marker = None

    def faction_buttons(self):
        items = (self.box.itemAt(i).widget() for i in range(self.box.count()))
        return [b for b in items if isinstance(b, NavButton) and b.draggable]

    def _index_at(self, y):
        buttons = self.faction_buttons()
        index = sum(1 for b in buttons if b.geometry().center().y() < y)
        if not buttons:
            return 0, None
        line = buttons[index - 1].geometry().bottom() + 1 if index else buttons[0].geometry().top() - 1
        return index, line

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(FACTION_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(FACTION_MIME):
            e.acceptProposedAction()
            self._marker = self._index_at(e.position().y())[1]
            self.update()

    def dragLeaveEvent(self, _):
        self._marker = None
        self.update()

    def dropEvent(self, e):
        self._marker = None
        self.update()
        if e.mimeData().hasFormat(FACTION_MIME):
            faction = bytes(e.mimeData().data(FACTION_MIME)).decode()
            self.dropped.emit(faction, self._index_at(e.position().y())[0])
            e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._marker is not None:
            p = QPainter(self)
            p.setPen(QPen(QColor(GOLD_HI), 2))
            p.drawLine(6, self._marker, self.width() - 6, self._marker)


class CampaignCard(QPushButton):
    """The campaign at the top of the faction menu. Click to switch; right-click for more."""

    def __init__(self):
        super().__init__()
        self.setObjectName("campaignCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 8, 12, 9)
        box.setSpacing(1)
        cap = label("CAMPAIGN", font=display_font(9, QFont.Weight.DemiBold, 150))
        cap.setStyleSheet(f"color: {MUTED}; background: transparent;")
        row = QHBoxLayout()
        row.setSpacing(6)
        self.name = label("", font=display_font(15, QFont.Weight.Bold, 104))
        self.name.setStyleSheet(f"color: {GOLD_HI}; background: transparent;")
        self.name.setWordWrap(True)
        arrow = label("▾")
        arrow.setStyleSheet(f"color: {GOLD}; background: transparent;")
        row.addWidget(self.name, 1)
        row.addWidget(arrow, 0, Qt.AlignmentFlag.AlignTop)
        box.addWidget(cap)
        box.addLayout(row)
        for w in (cap, self.name, arrow):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_campaign(self, name):
        self.name.setText(name or "No campaign")
        self.setToolTip(f"{name}\nClick to switch campaign · right-click to rename or reorder")
        self.setAccessibleName(f"Campaign: {name}")
        self.updateGeometry()

    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize()


class ProfileBanner(QWidget):
    """Faction-colored header with the selected character's portrait bleeding off the bottom right."""

    HEIGHT = 200
    PORTRAIT = 250

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.HEIGHT)
        self.character = None
        self.portrait = QPixmap()

    def set_character(self, character, portrait: QPixmap):
        self.character = character
        self.portrait = portrait
        self.setAccessibleName(f'{character["name"]}, {faction_label(character["faction"])}' if character
                               else "No character chosen")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        if not self.character:
            p.fillRect(self.rect(), QColor(INK))
            p.setPen(QColor(MUTED))
            p.setFont(body_font(18, italic=True))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No character chosen")
        else:
            base = QColor(FACTION_COLORS.get(self.character["faction"], GOLD))
            p.fillRect(self.rect(), base)
            size = self.PORTRAIT
            left = w - size + 10
            p.drawPixmap(QRectF(left, h - size + 40, size, size), self.portrait, QRectF(self.portrait.rect()))
            # Fade the portrait's own card background into the band, starting at its left edge,
            # so there's no seam and long names stay readable.
            fade = QLinearGradient(left, 0, left + 110, 0)
            solid, clear = QColor(base), QColor(base)
            clear.setAlpha(0)
            fade.setColorAt(0.0, solid)
            fade.setColorAt(1.0, clear)
            p.fillRect(self.rect(), fade)

            light = base.lightnessF() > 0.6
            ink = QColor(INK if light else "#ffffff")
            p.setPen(ink)
            p.setFont(display_font(12, QFont.Weight.Bold, 124))
            p.drawText(QRectF(22, 0, w - 44, h - 64), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       faction_label(self.character["faction"]).upper())
            p.setFont(display_font(32, QFont.Weight.Bold, 104))
            name = p.fontMetrics().elidedText(self.character["name"], Qt.TextElideMode.ElideRight, int(w * 0.6))
            p.drawText(QRectF(22, 0, w - 44, h - 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, name)
        p.setPen(QPen(QColor(GOLD), 1))
        p.drawLine(QPointF(0, h - 0.5), QPointF(w, h - 0.5))


# ---- tarot view ----------------------------------------------------------

TAROT_GOLD = "#e8c872"
TAROT_LAVENDER = "#b7b0e0"
TAROT_NIGHT = "#14142c"
TAROT_LINE = "#3b3a6a"
TAROT_BRASS = "#6a5a2a"


def draw_cover(p, target: QRectF, art: QPixmap):
    """Fill target with art, cropping the sides or bottom and keeping the top (where faces are)."""
    if art.isNull():
        return
    aw, ah = art.width(), art.height()
    scale = max(target.width() / aw, target.height() / ah)
    sw, sh = target.width() / scale, target.height() / scale
    p.drawPixmap(target, art, QRectF((aw - sw) / 2, 0, sw, sh))


class TarotStage(QWidget):
    """Tarot view: the chosen character drawn as a large card, its neighbours in the deck tilted behind it."""

    stepRequested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.card = None  # (character, portrait)
        self.prev = self.next = None
        self.prev_rect = self.next_rect = QRectF()
        self.setMinimumSize(320, 280)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Click a side card, scroll, or press Left/Right to deal the next card")

    def set_cards(self, card, prev=None, nxt=None):
        self.card, self.prev, self.next = card, prev, nxt
        self.setAccessibleName(f'{card[0]["name"]}, {faction_label(card[0]["faction"])}' if card
                               else "No character chosen")
        self.update()

    @staticmethod
    def draw_card(p, rect: QRectF, character, art: QPixmap, plate_px=17):
        radius = rect.width() * 0.055
        outline = QPainterPath()
        outline.addRoundedRect(rect, radius, radius)
        p.save()
        p.setClipPath(outline)
        p.fillRect(rect, QColor(FACTION_COLORS.get(character["faction"], GOLD)))
        plate_h = plate_px * 3.3
        draw_cover(p, QRectF(rect.left(), rect.top(), rect.width(), rect.height() - plate_h), art)
        plate = QRectF(rect.left(), rect.bottom() - plate_h, rect.width(), plate_h)
        p.fillRect(plate, QColor(TAROT_NIGHT))
        p.setPen(QPen(QColor(TAROT_GOLD), 1))
        p.drawLine(plate.topLeft(), plate.topRight())
        p.setFont(display_font(plate_px, QFont.Weight.Bold, 106))
        name = p.fontMetrics().elidedText(character["name"], Qt.TextElideMode.ElideRight, int(rect.width() - 16))
        p.drawText(plate.adjusted(8, 4, -8, -plate_h * 0.42), Qt.AlignmentFlag.AlignCenter, name)
        p.setPen(QColor(TAROT_LAVENDER))
        p.setFont(body_font(max(11, int(plate_px * 0.82)), italic=True))
        faction = p.fontMetrics().elidedText(faction_label(character["faction"]), Qt.TextElideMode.ElideRight,
                                             int(rect.width() - 16))
        p.drawText(plate.adjusted(8, plate_h * 0.5, -8, -4), Qt.AlignmentFlag.AlignCenter, faction)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(TAROT_BRASS), 1))
        p.drawRoundedRect(rect.adjusted(-7, -7, 7, 7), radius + 6, radius + 6)
        p.setPen(QPen(QColor(TAROT_NIGHT), 5))
        p.drawRoundedRect(rect.adjusted(-3.5, -3.5, 3.5, 3.5), radius + 3, radius + 3)
        p.setPen(QPen(QColor(TAROT_GOLD), 2))
        p.drawRoundedRect(rect, radius, radius)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.card:
            p.setPen(QColor(TAROT_LAVENDER))
            p.setFont(body_font(20, italic=True))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Choose a card from the deck.")
            return
        h = min(self.height() - 36, 470)
        w = h * 0.64
        c = QPointF(self.width() / 2, self.height() / 2)
        gh, gw = h * 0.66, w * 0.66
        offset = min(w * 0.95, (self.width() - gw) / 2 - 8)
        self.prev_rect = QRectF(c.x() - offset - gw / 2, c.y() - gh / 2, gw, gh)
        self.next_rect = QRectF(c.x() + offset - gw / 2, c.y() - gh / 2, gw, gh)
        for card, rect, angle in ((self.prev, self.prev_rect, -10), (self.next, self.next_rect, 9)):
            if card:
                p.save()
                p.setOpacity(0.45)
                p.translate(rect.center())
                p.rotate(angle)
                self.draw_card(p, QRectF(-gw / 2, -gh / 2, gw, gh), card[0], card[1], plate_px=12)
                p.restore()
        p.translate(c)
        p.rotate(-2)
        self.draw_card(p, QRectF(-w / 2, -h / 2, w, h), self.card[0], self.card[1], plate_px=max(14, int(h / 24)))

    def mousePressEvent(self, e):
        self.setFocus()
        if self.prev and self.prev_rect.contains(e.position()):
            self.stepRequested.emit(-1)
        elif self.next and self.next_rect.contains(e.position()):
            self.stepRequested.emit(1)

    def wheelEvent(self, e):
        dy = e.angleDelta().y() or e.angleDelta().x()
        if dy:
            self.stepRequested.emit(-1 if dy > 0 else 1)

    def keyPressEvent(self, e):
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(e.key())
        if step:
            self.stepRequested.emit(step)
        else:
            super().keyPressEvent(e)


class DeckCard(QWidget):
    """A small card in the tarot deck; the chosen one rises out of the row."""

    clicked = pyqtSignal(str)
    menuRequested = pyqtSignal(str, QPoint)
    stepRequested = pyqtSignal(int)
    W, H, LIFT = 88, 136, 12

    def __init__(self, cid, character, avatar: QPixmap):
        super().__init__()
        self.cid = cid
        self.character = character
        self.avatar = avatar
        self.selected = self.hover = False
        self.setFixedSize(self.W + 2, self.H + self.LIFT + 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.refresh_text()

    def refresh_text(self):
        c = self.character
        self.setToolTip(f'{c["name"]} — {faction_label(c["faction"])}\nRight-click to rename or favorite')
        self.setAccessibleName(c["name"])
        self.update()

    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.update()

    def set_avatar(self, avatar):
        self.avatar = avatar
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        lift = 0 if self.selected else (self.LIFT / 2 if self.hover or self.hasFocus() else self.LIFT)
        rect = QRectF(1, 1 + lift, self.W, self.H)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.fillRect(rect, QColor(TAROT_NIGHT))
        draw_cover(p, QRectF(rect.left(), rect.top(), rect.width(), rect.height() - 22), self.avatar)
        p.setPen(QColor(TEXT))
        p.setFont(display_font(10, QFont.Weight.DemiBold, 100))
        name = p.fontMetrics().elidedText(self.character["name"], Qt.TextElideMode.ElideRight, int(rect.width() - 8))
        p.drawText(QRectF(rect.left() + 4, rect.bottom() - 22, rect.width() - 8, 22), Qt.AlignmentFlag.AlignCenter, name)
        p.restore()
        if self.character.get("favorite"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TAROT_GOLD))
            p.drawPolygon(star_polygon(QPointF(rect.right() - 11, rect.top() + 11), 7, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(TAROT_GOLD if self.selected else (GOLD if self.hover else TAROT_BRASS)),
                      2 if self.selected else 1))
        p.drawRoundedRect(rect, 8, 8)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.cid)

    def contextMenuEvent(self, e):
        self.menuRequested.emit(self.cid, e.globalPos())

    def keyPressEvent(self, e):
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(e.key())
        if step:
            self.stepRequested.emit(step)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.cid)
        else:
            super().keyPressEvent(e)

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()


class DeckScroll(QScrollArea):
    """Sideways-scrolling deck: the mouse wheel moves it left and right."""

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - (e.angleDelta().y() or e.angleDelta().x()))


# ---- message preview ---------------------------------------------------

class MessageEdit(QPlainTextEdit):
    """Enter sends; Ctrl+Enter (or Shift+Enter) starts a new line."""

    submitted = pyqtSignal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                self.insertPlainText("\n")
            elif mods == Qt.KeyboardModifier.NoModifier:
                self.submitted.emit()
            return
        super().keyPressEvent(e)


class AttachmentThumb(QWidget):
    removed = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.setFixedSize(132, 92)
        img = QLabel(self)
        img.setGeometry(0, 6, 124, 86)
        img.setPixmap(cover_pixmap(path, 124, 86))
        img.setStyleSheet(f"border: 1px solid {LINE};")
        img.setToolTip(Path(path).name)
        x = QToolButton(self)
        x.setObjectName("remove")
        x.setText("✕")
        x.setToolTip("Remove image")
        x.setAccessibleName(f"Remove {Path(path).name}")
        x.setGeometry(112, 0, 20, 20)
        x.clicked.connect(lambda: self.removed.emit(self.path))


class MessageRow(QWidget):
    """One message as it will look in the channel: avatar, name, APP tag, text, images."""

    attachmentRemoved = pyqtSignal(str)

    def __init__(self, faded=False):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.avatar = QLabel()
        self.avatar.setFixedSize(48, 48)
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.name = label("", font=body_font(18, weight=QFont.Weight.DemiBold))
        self.tag = label("APP", "appTag")
        self.meta = label("", "muted", body_font(14, italic=True))
        head.addWidget(self.name)
        head.addWidget(self.tag)
        head.addWidget(self.meta)
        head.addStretch()
        col.addLayout(head)
        self.text = QLabel()
        self.text.setFont(body_font(17))
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        col.addWidget(self.text)
        self.images = QWidget()
        self.images_flow = FlowLayout(self.images, hspacing=8, vspacing=8)
        col.addWidget(self.images)
        col.addStretch(1)  # keep the name row compact when there's no text yet
        layout.addLayout(col, 1)
        if faded:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.55)
            self.setGraphicsEffect(effect)

    def set_message(self, avatar: QPixmap, name, meta, text, images=(), removable=False):
        self.avatar.setPixmap(circular_pixmap(avatar, 48, ring=GOLD, dpr=self.devicePixelRatioF()))
        self.name.setText(name or "—")
        self.meta.setText(meta)
        self.text.setText(text)
        self.text.setVisible(bool(text))
        while self.images_flow.count():
            self.images_flow.takeAt(0).widget().deleteLater()
        for path in images:
            if removable:
                thumb = AttachmentThumb(path)
                thumb.removed.connect(self.attachmentRemoved)
            else:
                thumb = QLabel()
                thumb.setPixmap(cover_pixmap(path, 124, 86))
            self.images_flow.addWidget(thumb)
        self.images.setVisible(bool(images))


class ChannelPicker(QComboBox):
    """The channel to post to, as a drop-down. Its last entry adds a channel; right-click removes the current one."""

    selected = pyqtSignal(str)
    addRequested = pyqtSignal()
    removeRequested = pyqtSignal(str)
    ADD = "__add__"

    def __init__(self):
        super().__init__()
        self.last = ""
        self.setObjectName("channelPicker")
        self.setAccessibleName("Channel")
        self.setPlaceholderText("No channels yet")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("The channel to post to · right-click to remove it")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.activated.connect(self._activated)

    def set_channels(self, names, current):
        self.blockSignals(True)
        self.clear()
        for name in names:
            self.addItem(f"# {name}", name)
        self.addItem("+ Add channel…", self.ADD)
        self.setCurrentIndex(self.findData(current) if current in names else -1)
        self.blockSignals(False)
        self.last = self.current()

    def current(self):
        data = self.currentData()
        return data if data and data != self.ADD else ""

    def _activated(self, index):
        data = self.itemData(index)
        if data == self.ADD:
            # Show the previous channel again; adding one selects it once it exists.
            self.setCurrentIndex(self.findData(self.last) if self.last else -1)
            self.addRequested.emit()
        elif data != self.last:
            self.last = data
            self.selected.emit(data)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(GOLD), 1.6))
        x, y = self.width() - 18, self.height() / 2
        p.drawPolyline(QPolygonF([QPointF(x - 4.5, y - 2.5), QPointF(x, y + 2), QPointF(x + 4.5, y - 2.5)]))

    def _menu(self, pos):
        name = self.current()
        if name:
            menu = QMenu(self)
            menu.addAction(f'Remove "# {name}"…', lambda: self.removeRequested.emit(name))
            menu.exec(self.mapToGlobal(pos))


class ServerBadge(QAbstractButton):
    """A server in the rail: a round badge with its image (or initials); the selected one squares off and gets a bar."""

    W, D = 58, 38

    def __init__(self, text, tooltip, dashed=False, image=None, horizontal=False):
        super().__init__()
        self.text_ = text
        self.image = image if image and not image.isNull() else None
        self.dashed = dashed
        self.hover = False
        self.horizontal = horizontal  # in a row: the selected bar sits underneath instead of to the left
        self.setFixedSize(*((self.D + 8, self.D + 8) if horizontal else (self.W, self.D + 4)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        r = QRectF((self.width() - self.D) / 2, 2, self.D, self.D)
        if self.dashed:
            pen = QPen(QColor(GOLD_HI if self.hover else GOLD), 1.2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
        else:
            radius = 11 if on else self.D / 2
            shape = r.adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a2f20" if on else RAISED))
            p.drawRoundedRect(shape, radius, radius)
            if self.image:
                clip = QPainterPath()
                clip.addRoundedRect(shape, radius, radius)
                p.save()
                p.setClipPath(clip)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawPixmap(shape, self.image, QRectF(self.image.rect()))
                p.restore()
            p.setPen(QPen(QColor(GOLD if on or self.hover or self.hasFocus() else LINE_HI), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(shape, radius, radius)
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(GOLD_HI))
            if self.horizontal:
                p.drawRoundedRect(QRectF(r.left() + 7, self.height() - 3, r.width() - 14, 6), 3, 3)
            else:
                p.drawRoundedRect(QRectF(-3, r.top() + 7, 6, r.height() - 14), 3, 3)
        if self.image:
            return
        p.setPen(QColor(GOLD_HI if on else (GOLD if self.dashed else MUTED)))
        p.setFont(body_font(20) if self.dashed else display_font(12, QFont.Weight.Bold, 100))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text_)


class ServerRail(QWidget):
    """The strip of server badges down the left of the composer."""

    selected = pyqtSignal(str)
    addRequested = pyqtSignal()
    renameRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)
    imageRequested = pyqtSignal(str)
    imageCleared = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.icons = {}
        self.horizontal = False
        self.shown = None
        self.setObjectName("rail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(ServerBadge.W)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 14, 0, 14)
        self.box.setSpacing(8)
        self.box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.buttonClicked.connect(lambda b: self.selected.emit(b.property("server")))

    def set_horizontal(self, on):
        """Lay the badges out in a row (tarot view) or a column (classic view)."""
        if on == self.horizontal:
            return
        self.horizontal = on
        if on:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setFixedHeight(ServerBadge.D + 8)
            self.box.setDirection(QVBoxLayout.Direction.LeftToRight)
            self.box.setContentsMargins(0, 0, 0, 0)
            self.box.setAlignment(Qt.AlignmentFlag.AlignLeft)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setFixedWidth(ServerBadge.W)
            self.box.setDirection(QVBoxLayout.Direction.TopToBottom)
            self.box.setContentsMargins(0, 14, 0, 14)
            self.box.setAlignment(Qt.AlignmentFlag.AlignTop)
        if self.shown is not None:
            self.set_servers(*self.shown)

    def set_servers(self, names, current, icons=None):
        self.shown = (names, current, icons)
        self.icons = icons or {}
        for b in self.group.buttons():
            self.group.removeButton(b)
        while self.box.count():
            self.box.takeAt(0).widget().deleteLater()
        for name in names:
            b = ServerBadge(servers.initials(name), f"{name}\nRight-click to rename, set its image or remove",
                            image=self.icons.get(name), horizontal=self.horizontal)
            b.setCheckable(True)
            b.setChecked(name == current)
            b.setProperty("server", name)
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _, n=name, btn=b: self._menu(n, btn))
            self.group.addButton(b)
            self.box.addWidget(b)
        add = ServerBadge("+", "Add a server (paste a webhook from one of its channels)", dashed=True,
                          horizontal=self.horizontal)
        add.clicked.connect(self.addRequested)
        self.box.addWidget(add)

    def _menu(self, name, button):
        menu = QMenu(self)
        menu.addAction("Rename server…", lambda: self.renameRequested.emit(name))
        menu.addAction("Set server image…", lambda: self.imageRequested.emit(name))
        if self.icons.get(name):
            menu.addAction("Remove server image", lambda: self.imageCleared.emit(name))
        menu.addSeparator()
        menu.addAction(f'Remove "{name}"…', lambda: self.removeRequested.emit(name))
        menu.exec(button.mapToGlobal(QPoint(button.width() - 8, button.height() // 2)))


# ---- dialogs -------------------------------------------------------------

class AddChannelDialog(QDialog):
    """Asks for a channel name and webhook, and checks the webhook with Discord (which says which server it's in)."""

    def __init__(self, parent, new_server=False):
        super().__init__(parent)
        self.setWindowTitle("Add server" if new_server else "Add channel")
        self.info = {}
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://discord.com/api/webhooks/…")
        self.url.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout(self)
        form.addRow("Channel name:", self.name)
        form.addRow("Webhook URL:", self.url)
        hint = ("Paste a webhook from any channel in the new server; you'll name the server next."
                if new_server else
                "The webhook is checked with Discord before it's saved, and filed under its server.")
        form.addRow(label(hint, "muted"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.try_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(560, 0)

    def try_accept(self):
        if not self.name.text().strip():
            return QMessageBox.warning(self, self.windowTitle(), "Give the channel a name.")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.info = discord_client.fetch_webhook_info(self.url.text().strip())
        except discord_client.WebhookError as e:
            return QMessageBox.warning(self, self.windowTitle(), str(e))
        finally:
            QApplication.restoreOverrideCursor()
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, parent, settings, sample_avatar):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.sample_avatar = sample_avatar
        self.base = QLineEdit(settings.get("avatar_base_url", ""))
        self.base.setPlaceholderText("https://raw.githubusercontent.com/<user>/<repo>/main/avatars/")
        test = QPushButton("Test")
        test.clicked.connect(self.test)
        row = QHBoxLayout()
        row.addWidget(self.base)
        row.addWidget(test)
        form = QFormLayout(self)
        form.addRow("Avatar base URL:", row)
        form.addRow(label("Public URL of the avatars/ folder. Each character's avatar URL is\n"
                          "this plus its path, e.g. …/avatars/fiery-mane/dante.png", "muted"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(680, 0)

    def value(self) -> str:
        return self.base.text().strip()

    def test(self):
        import requests
        if not self.value() or not self.sample_avatar:
            return
        url = self.value().rstrip("/") + "/" + self.sample_avatar
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
            msg = f"{'OK' if ok else 'Not reachable'} ({r.status_code})\n{url}"
        except requests.RequestException as e:
            ok, msg = False, f"{e}\n{url}"
        finally:
            QApplication.restoreOverrideCursor()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Avatar URL test", msg)


class CropCanvas(QWidget):
    """The whole source portrait with a square frame: drag to move it, scroll to resize it."""

    changed = pyqtSignal()
    MIN_SIZE = 0.05

    def __init__(self, source: QPixmap):
        super().__init__()
        self.iw, self.ih = max(1, source.width()), max(1, source.height())
        # Big portraits are scaled once up front so dragging stays smooth.
        self.view = source.scaled(1400, 1400, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation) if not source.isNull() else source
        self.crop = [0.0, 0.0, 1.0]
        self._drag = None  # (press position, crop at press)
        self.setMinimumSize(500, 500)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def max_size(self):
        return max(1.0, self.ih / self.iw)

    def set_crop(self, crop):
        self.crop = list(crop)
        self.update()

    def _image_rect(self):
        avail = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        scale = min(avail.width() / self.iw, avail.height() / self.ih)
        w, h = self.iw * scale, self.ih * scale
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    def _frame_rect(self):
        img = self._image_rect()
        left, top, size = self.crop
        side = size * img.width()
        return QRectF(img.left() + left * img.width(), img.top() + top * img.height(), side, side)

    def _apply(self, left, top, size):
        size = min(max(size, self.MIN_SIZE), self.max_size())
        side_h = size * self.iw / self.ih  # frame height as a fraction of the image height
        # The frame may hang off the edge (transparent there), but its centre stays on the image.
        left = min(max(left, -size / 2), 1 - size / 2)
        top = min(max(top, -side_h / 2), 1 - side_h / 2)
        self.crop = [round(left, 4), round(top, 4), round(size, 4)]
        self.update()
        self.changed.emit()

    def _centre(self):
        left, top, size = self.crop
        return left + size / 2, top + size * self.iw / self.ih / 2

    def resize_frame(self, size):
        cx, cy = self._centre()
        size = min(max(size, self.MIN_SIZE), self.max_size())
        self._apply(cx - size / 2, cy - size * self.iw / self.ih / 2, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        img = self._image_rect()
        p.fillRect(img, QColor("#2a2520"))  # shows through transparent art
        p.drawPixmap(img, self.view, QRectF(self.view.rect()))
        frame = self._frame_rect()
        shade = QPainterPath()
        shade.setFillRule(Qt.FillRule.OddEvenFill)
        shade.addRect(QRectF(self.rect()))
        shade.addRect(frame)
        p.fillPath(shade, QColor(10, 8, 6, 175))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(GOLD_HI), 2))
        p.drawRect(frame)
        p.setPen(QPen(QColor(GOLD), 1, Qt.PenStyle.DashLine))
        p.drawEllipse(frame)  # what Discord's round avatar shows

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        if not self._frame_rect().contains(pos):  # clicking elsewhere centres the frame there first
            img = self._image_rect()
            size = self.crop[2]
            cx, cy = (pos.x() - img.left()) / img.width(), (pos.y() - img.top()) / img.height()
            self._apply(cx - size / 2, cy - size * self.iw / self.ih / 2, size)
        self._drag = (pos, list(self.crop))
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        start, (left, top, size) = self._drag
        img = self._image_rect()
        d = e.position() - start
        self._apply(left + d.x() / img.width(), top + d.y() / img.height(), size)

    def mouseReleaseEvent(self, _):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, e):
        self.resize_frame(self.crop[2] * 0.95 ** (e.angleDelta().y() / 120))  # scroll up = zoom in

    def keyPressEvent(self, e):
        step = 0.02 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.004
        left, top, size = self.crop
        r = self.iw / self.ih
        moves = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                 Qt.Key.Key_Up: (0, -step * r), Qt.Key.Key_Down: (0, step * r)}
        if e.key() in moves:
            dx, dy = moves[e.key()]
            self._apply(left + dx, top + dy, size)
        elif e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.resize_frame(size * 0.97)
        elif e.key() == Qt.Key.Key_Minus:
            self.resize_frame(size / 0.97)
        else:
            super().keyPressEvent(e)


class FramingDialog(QDialog):
    """Adjust a character's normal and zoomed avatar frames; Save writes them as the new defaults."""

    KINDS = (("crop", "Normal"), ("zoom", "Zoomed"))

    def __init__(self, parent, character, kind="crop"):
        super().__init__(parent)
        self.setWindowTitle(f"Edit framing — {character['name']}")
        self.src = QPixmap(str(catalog.ROOT / character["source"]))
        self.saved = {"crop": list(character["crop"]), "zoom": list(character.get("zoom") or character["crop"])}
        self.work = {k: list(v) for k, v in self.saved.items()}
        self.kind = kind
        self.backdrop = QPixmap()
        if character.get("background"):
            from io import BytesIO
            buf = BytesIO()
            catalog.backdrop(character["background"], 256).save(buf, "PNG")
            self.backdrop.loadFromData(buf.getvalue())

        self.canvas = CropCanvas(self.src)
        self.canvas.changed.connect(self._on_canvas)

        side = QVBoxLayout()
        side.setSpacing(12)
        side.addWidget(label(character["name"], font=display_font(22)))
        side.addWidget(label(faction_label(character["faction"]), "muted", body_font(15, italic=True)))
        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.tab_group = QButtonGroup(self)
        for k, text in self.KINDS:
            b = QPushButton(text)
            b.setObjectName("pill")
            b.setCheckable(True)
            b.setChecked(k == kind)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("kind", k)
            self.tab_group.addButton(b)
            tabs.addWidget(b)
        tabs.addStretch()
        self.tab_group.buttonClicked.connect(lambda b: self.set_kind(b.property("kind")))
        side.addLayout(tabs)

        previews = QHBoxLayout()
        previews.setSpacing(14)
        self.big, self.small = QLabel(), QLabel()
        previews.addWidget(self.big)
        previews.addWidget(self.small, 0, Qt.AlignmentFlag.AlignBottom)
        previews.addStretch()
        side.addSpacing(6)
        side.addLayout(previews)

        side.addSpacing(6)
        side.addWidget(label("FRAME SIZE", "muted", display_font(11, spacing=130)))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(CropCanvas.MIN_SIZE * 1000), round(self.canvas.max_size() * 1000))
        self.slider.setInvertedAppearance(True)  # right = closer
        self.slider.valueChanged.connect(lambda v: self.canvas.resize_frame(v / 1000))
        side.addWidget(self.slider)
        hint = label("Drag the frame to move it · scroll or +/− to zoom\n"
                     "Arrow keys nudge (hold Shift for bigger steps)", "muted", body_font(14, italic=True))
        side.addWidget(hint)
        side.addStretch()

        revert = QPushButton("Revert")
        revert.setObjectName("ghost")
        revert.setToolTip("Back to the saved framing")
        revert.clicked.connect(self.revert)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("SAVE AS DEFAULT")
        save.setObjectName("send")
        save.setMinimumHeight(38)
        save.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(revert)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        side.addLayout(buttons)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 20, 16)
        layout.setSpacing(20)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(side)
        self.resize(1000, 680)
        self.set_kind(kind)
        self.canvas.setFocus()

    def set_kind(self, kind):
        self.kind = kind
        self.canvas.set_crop(self.work[kind])
        self._sync_controls()

    def revert(self):
        self.work[self.kind] = list(self.saved[self.kind])
        self.set_kind(self.kind)

    def changes(self):
        """{kind: crop} for each frame that differs from what's saved."""
        return {k: v for k, v in self.work.items() if v != self.saved[k]}

    def _on_canvas(self):
        self.work[self.kind] = list(self.canvas.crop)
        self._sync_controls()

    def _sync_controls(self):
        self.slider.blockSignals(True)
        self.slider.setValue(round(self.canvas.crop[2] * 1000))
        self.slider.blockSignals(False)
        avatar = self._render(self.canvas.crop)
        self.big.setPixmap(circular_pixmap(avatar, 168, ring=GOLD, dpr=self.devicePixelRatioF()))
        self.small.setPixmap(circular_pixmap(avatar, 44, dpr=self.devicePixelRatioF()))

    def _render(self, crop, px=256):
        """Quick in-app version of catalog.render_avatar, for the live preview."""
        out = QPixmap(px, px)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.backdrop.isNull():
            p.drawPixmap(QRectF(0, 0, px, px), self.backdrop, QRectF(self.backdrop.rect()))
        left, top, size = crop
        w, h = self.src.width(), self.src.height()
        # Draw the whole image, positioned so the crop square fills the output.
        k = px / (size * w)
        p.drawPixmap(QRectF(-left * w * k, -top * h * k, w * k, h * k), self.src, QRectF(self.src.rect()))
        p.end()
        return out


class DiscordWorker(QThread):
    """Runs one Discord call off the UI thread; done carries (ok, Discord's reply or the error text)."""

    done = pyqtSignal(bool, object)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(True, self.fn(*self.args))
        except discord_client.WebhookError as e:
            self.done.emit(False, str(e))


def when_text(iso):
    """'3:14 PM' today, 'Oct 27, 3:14 PM' otherwise."""
    sent = datetime.fromisoformat(iso)
    when = sent.strftime("%I:%M %p").lstrip("0")
    return when if sent.date() == datetime.now().date() else sent.strftime("%b %d, ") + when


def local_time(discord_timestamp):
    try:
        return datetime.fromisoformat(discord_timestamp).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return datetime.now().isoformat(timespec="seconds")


# ---- main window ---------------------------------------------------------

class EdgeResizer(QObject):
    """Lets the frameless window be resized from its edges and corners, like a normal window."""

    MARGIN = 5
    CURSORS = {
        Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
        Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.cursor = None

    def edges(self, global_pos):
        w = self.window
        if w.isMaximized() or w.isFullScreen():
            return None
        pos, m = w.mapFromGlobal(global_pos), self.MARGIN
        edges = Qt.Edge(0)
        if pos.x() < m:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= w.width() - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() < m:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= w.height() - m:
            edges |= Qt.Edge.BottomEdge
        return edges or None

    def set_cursor(self, shape):
        if shape == self.cursor:
            return
        if self.cursor is not None:
            QApplication.restoreOverrideCursor()
        if shape is not None:
            QApplication.setOverrideCursor(shape)
        self.cursor = shape

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Type.MouseMove and not e.buttons():
            edges = self.edges(e.globalPosition().toPoint())
            self.set_cursor(self.CURSORS.get(edges) if edges else None)
        elif t == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
            edges = self.edges(e.globalPosition().toPoint())
            if edges:
                self.set_cursor(None)
                self.window.windowHandle().startSystemResize(edges)
                return True
        elif t == QEvent.Type.Leave:
            self.set_cursor(None)
        return False


class MainWindow(QMainWindow):
    def __init__(self, characters):
        super().__init__()
        self.setWindowTitle("Set in Stone Character Board")
        # No Windows title bar: the header is the title bar, with its own minimize/maximize/close buttons.
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setContentsMargins(1, 1, 1, 1)  # room for the thin border drawn in paintEvent
        self.characters = characters
        self.settings = load_json(SETTINGS_FILE, {"avatar_base_url": ""})
        self.history = load_json(HISTORY_FILE, {})
        self.ui_state = QSettings("SetInStone", "CharacterBoard")
        load_factions("")
        self.campaign = self.ui_state.value("campaign") or catalog.DEFAULT_CAMPAIGN
        if self.campaign not in self.campaign_list():
            self.campaign = next(iter(self.campaign_list()), catalog.DEFAULT_CAMPAIGN)
        load_factions(self.campaign)
        self.selected_by_campaign = json.loads(self.ui_state.value("character_by_campaign", "{}") or "{}")
        self.last_channel = json.loads(self.ui_state.value("last_channels", "{}") or "{}")
        self.servers = self._load_servers()
        self.current_server = self.ui_state.value("server") or ""
        self.worker = None
        self.edit_worker = None
        self.edit_mode = False
        self.edit_target = None  # the posted message being edited
        self.draft = None  # what was in the composer before Edit Mode, put back after
        self.warned_no_avatar = False
        self.selected_cid = None
        self.attachments = []
        self.tiles = {}
        self.sections = []
        self.pixmaps = {}
        self.portraits = {}
        self.deck_cards = {}
        self.slots, self.shared = {}, {}
        self.view = "classic"
        self.mode = ALL
        self.setAcceptDrops(True)

        self._build_ui()
        self.populate_nav()
        self.populate_roster()
        self.populate_servers(self.current_server)
        self._restore_state()
        self.set_view(self.ui_state.value("view") or "classic")
        self.refresh_preview()
        self.winId()  # create the native window now, so its edges can be watched
        self.windowHandle().installEventFilter(EdgeResizer(self))

    # ---- construction -------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._build_header())

        self.splitter = QSplitter()
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.slot("nav", "classic", self._build_nav()))
        self.splitter.addWidget(self._build_center())
        self.splitter.addWidget(self._build_panel())
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 710, 510])
        self.stack = QStackedWidget()
        self.stack.addWidget(self.splitter)
        self.stack.addWidget(self._build_tarot())
        rl.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.statusBar()
        self.resize(1500, 900)
        self.setMinimumSize(1400, 760)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search.setFocus())

    def _build_header(self):
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(46)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 0, 0)
        hl.setSpacing(10)
        header.installEventFilter(self)  # drag to move, double-click to maximize
        self.header = header
        banner = QLabel()
        pix = QPixmap(str(BANNER_FILE))
        if not pix.isNull():
            pix = pix.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(2)
            banner.setPixmap(pix)
        title = label("SET IN STONE · CHARACTER BOARD", font=display_font(13, QFont.Weight.DemiBold, 118))
        title.setStyleSheet(f"color: {GOLD};")
        hl.addWidget(banner)
        hl.addWidget(title)
        hl.addStretch()
        self.edit_button = QToolButton()
        self.edit_button.setObjectName("fileMenu")
        self.edit_button.setText("Edit Mode")
        self.edit_button.setCheckable(True)
        self.edit_button.setShortcut(QKeySequence("Ctrl+E"))
        self.edit_button.setToolTip("Edit or delete messages already posted to a channel (Ctrl+E)")
        self.edit_button.toggled.connect(self.set_edit_mode)
        hl.addWidget(self.edit_button)
        view_button = QToolButton()
        view_button.setObjectName("fileMenu")
        view_button.setText("View  ▾")
        view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        view_menu = QMenu(view_button)
        group = QActionGroup(self)
        self.view_actions = {}
        for i, (key, text) in enumerate(VIEWS.items()):
            action = view_menu.addAction(text)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            action.triggered.connect(lambda _=False, k=key: self.set_view(k))
            group.addAction(action)
            self.addAction(action)
            self.view_actions[key] = action
        view_button.setMenu(view_menu)
        hl.addWidget(view_button)
        menu_button = QToolButton()
        menu_button.setObjectName("fileMenu")
        menu_button.setText("File  ▾")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        menu.addAction("Rescan portraits", lambda: self.resync(force=False))
        menu.addAction("Rebuild all avatars", lambda: self.resync(force=True))
        menu.addAction("Edit Framing…", self.edit_framing)
        menu.addSeparator()
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        menu_button.setMenu(menu)
        hl.addWidget(menu_button)
        hl.addSpacing(6)
        window_row = QHBoxLayout()
        window_row.setSpacing(0)
        self.window_buttons = {}
        for key, glyph, tip, slot in (("min", "\uE921", "Minimize", self.showMinimized),
                                      ("max", "\uE922", "Maximize", self.toggle_maximized),
                                      ("close", "\uE8BB", "Close", self.close)):
            b = QToolButton()
            b.setObjectName("winClose" if key == "close" else "winButton")
            b.setText(glyph)
            b.setFixedSize(46, 46)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            window_row.addWidget(b)
            self.window_buttons[key] = b
        hl.addLayout(window_row)
        return header

    # ---- window frame -------------------------------------------------

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def eventFilter(self, obj, e):
        if obj is getattr(self, "header", None) and e.type() in (QEvent.Type.MouseButtonPress,
                                                                 QEvent.Type.MouseButtonDblClick):
            if e.button() == Qt.MouseButton.LeftButton:
                if e.type() == QEvent.Type.MouseButtonDblClick:
                    self.toggle_maximized()
                else:
                    self.windowHandle().startSystemMove()
                return True
        return super().eventFilter(obj, e)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange and hasattr(self, "window_buttons"):
            maxed = self.isMaximized()
            self.window_buttons["max"].setText("\uE923" if maxed else "\uE922")
            self.window_buttons["max"].setToolTip("Restore" if maxed else "Maximize")
            self.setContentsMargins(*([0] * 4 if maxed else [1] * 4))

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.isMaximized():
            p = QPainter(self)
            p.setPen(QColor(LINE_HI))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _build_nav(self):
        nav = QWidget()
        nav.setObjectName("nav")
        nav.setMinimumWidth(200)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(14, 22, 14, 14)
        layout.setSpacing(2)
        self.campaign_card = CampaignCard()
        self.campaign_card.set_campaign(self.campaign)
        self.campaign_card.clicked.connect(self.campaign_menu)
        self.campaign_card.customContextMenuRequested.connect(lambda _: self.campaign_context_menu())
        layout.addWidget(self.campaign_card)
        layout.addSpacing(14)
        heading = label("FACTIONS", font=display_font(12, QFont.Weight.DemiBold, 124))
        heading.setStyleSheet(f"color: {MUTED}; padding: 0 10px 10px;")
        layout.addWidget(heading)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.buttonClicked.connect(lambda b: self.set_mode(b.property("mode")))
        self.nav_list = NavList()
        self.nav_list.dropped.connect(self.move_faction)
        self.nav_layout = self.nav_list.box
        layout.addWidget(self.nav_list)
        hint = label("Drag factions to reorder · right-click to rename", "muted", body_font(13, italic=True))
        hint.setStyleSheet("padding: 10px 10px 0;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(nav)
        self.nav_scroll = scroll
        return scroll

    def _build_center(self):
        center = QWidget()
        center.setObjectName("center")
        # Room for five portraits per row: tiles + gaps + layout margins + scrollbar.
        center.setMinimumWidth(5 * PortraitTile.W + 4 * 10 + 28 + 16 + 12 + 14)
        layout = QVBoxLayout(center)
        layout.setContentsMargins(28, 22, 16, 0)
        layout.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.title = label("The Roster", font=display_font(26, QFont.Weight.Bold, 106))
        self.count = label("", "muted", body_font(17, italic=True))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Seek a name…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedWidth(220)
        self.search.setAccessibleName("Search characters")
        self.search.textChanged.connect(lambda _: self.apply_filter())
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(SORT_KEYS.keys())
        self.sort_combo.setCurrentText(self.ui_state.value("sort", "Faction"))
        self.sort_combo.setAccessibleName("Sort by")
        self.sort_combo.currentTextChanged.connect(lambda _: self.populate_roster())
        top.addWidget(self.title)
        top.addWidget(self.count, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch()
        top.addWidget(self.slot("search", "classic", self.search))
        top.addWidget(label("Sort by", "muted", body_font(15)))
        top.addWidget(self.slot("sort", "classic", self.sort_combo))
        layout.addLayout(top)
        rule = QFrame()
        rule.setObjectName("goldRule")
        layout.addWidget(rule)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)
        self.empty = label("", "muted", body_font(18, italic=True))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty, 1)
        return center

    def _build_panel(self):
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setMinimumWidth(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.profile = ProfileBanner()
        layout.addWidget(self.profile)

        # Preview
        preview = QWidget()
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(24, 22, 24, 18)
        pl.setSpacing(12)
        where = QHBoxLayout()
        where.setSpacing(10)
        where.addWidget(label("PREVIEW IN", font=display_font(12, QFont.Weight.DemiBold, 124)))
        self.preview_channel = label("", font=display_font(15, QFont.Weight.Bold, 104))
        where.addWidget(self.preview_channel)
        where.addStretch()
        where.itemAt(0).widget().setStyleSheet(f"color: {MUTED};")
        pl.addLayout(where)
        pl.addWidget(self.slot("edits", "classic", self._build_edit_panel()))

        card = QFrame()
        card.setObjectName("previewCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(20)
        self.context_row = MessageRow(faded=True)
        self.message_row = MessageRow()
        self.message_row.attachmentRemoved.connect(self.remove_attachment)
        self.placeholder = label("Choose a character from the roster.", "muted", body_font(17, italic=True))
        cl.addWidget(self.context_row)
        cl.addWidget(self.message_row)
        cl.addWidget(self.placeholder)
        card_scroll = QScrollArea()
        card_scroll.setWidgetResizable(True)
        card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(card)
        hl.addStretch()
        card_scroll.setWidget(holder)
        pl.addWidget(self.slot("preview", "classic", card_scroll), 1)
        # The preview takes whatever height is left (its card scrolls), so the composer is never squeezed.
        preview.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        layout.addWidget(preview, 1)

        # Composer (bottom)
        composer = self.composer = QWidget()
        composer.setObjectName("composer")
        composer_row = QHBoxLayout(composer)
        composer_row.setContentsMargins(0, 0, 0, 0)
        composer_row.setSpacing(0)
        self.rail = ServerRail()
        self.rail.selected.connect(self.select_server)
        self.rail.addRequested.connect(lambda: self.add_channel(new_server=True))
        self.rail.renameRequested.connect(self.rename_server)
        self.rail.removeRequested.connect(self.remove_server)
        self.rail.imageRequested.connect(self.set_server_image)
        self.rail.imageCleared.connect(self.clear_server_image)
        composer_row.addWidget(self.slot("rail", "classic", self.rail))
        body = QWidget()
        composer_row.addWidget(body, 1)
        col = QVBoxLayout(body)
        col.setContentsMargins(20, 14, 20, 16)
        col.setSpacing(12)
        self.server_label = label("", font=display_font(13, QFont.Weight.DemiBold, 118))
        self.server_label.setStyleSheet(f"color: {GOLD};")
        col.addWidget(self.server_label)

        as_box = QWidget()
        as_row = QHBoxLayout(as_box)
        as_row.setContentsMargins(0, 0, 0, 0)
        as_row.setSpacing(8)
        as_row.addWidget(label("As", "muted", body_font(16, italic=True)))
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(discord_client.MAX_USERNAME)
        self.name_edit.setAccessibleName("Display name")
        self.name_edit.textChanged.connect(lambda _: self.refresh_preview())
        reset = QPushButton("Reset")
        reset.setObjectName("ghost")
        reset.setToolTip("Go back to the character's default name")
        reset.clicked.connect(self.reset_name)
        as_row.addWidget(self.name_edit, 1)
        as_row.addWidget(reset)
        col.addWidget(self.slot("as", "classic", as_box))

        to_row = QHBoxLayout()
        to_row.setSpacing(8)
        to_label = label("to", "muted", body_font(16, italic=True))
        to_row.addWidget(to_label)
        self.channel_box = ChannelPicker()
        self.channel_box.selected.connect(self.select_channel)
        self.channel_box.addRequested.connect(self.add_channel)
        self.channel_box.removeRequested.connect(self.remove_channel)
        to_row.addWidget(self.slot("channel", "classic", self.channel_box), 1)
        col.addLayout(to_row)

        write_row = QHBoxLayout()
        write_row.setSpacing(10)
        attach = QPushButton()
        attach.setObjectName("attach")
        attach.setFixedSize(48, 48)
        attach.setIcon(plus_icon())
        attach.setIconSize(QSize(18, 18))
        attach.setToolTip("Attach images (or drop them anywhere on the window)")
        attach.setAccessibleName("Attach images")
        attach.clicked.connect(self.add_images)
        self.message = MessageEdit()
        self.message.setObjectName("message")
        self.message.setFont(body_font(18))
        self.message.setPlaceholderText("Write your words…")
        self.message.setFixedHeight(88)
        self.message.setToolTip("Enter to send · Ctrl+Enter for a new line")
        self.message.submitted.connect(self.send)
        self.message.setAccessibleName("Message")
        placeholder_palette = self.message.palette()
        placeholder_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7a6a50"))
        self.message.setPalette(placeholder_palette)
        self.message.textChanged.connect(self.refresh_preview)
        self.send_btn = QPushButton("SEAL && SEND")
        self.send_btn.setObjectName("send")
        self.send_btn.setFixedHeight(48)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self.send)
        write_row.addWidget(attach, 0, Qt.AlignmentFlag.AlignTop)
        write_row.addWidget(self.slot("message", "classic", self.message), 1)
        send_col = QVBoxLayout()
        send_col.setSpacing(6)
        send_col.addWidget(self.send_btn)
        self.counter = label("", "muted", body_font(14))
        send_col.addWidget(self.slot("counter", "classic", self.counter, Qt.AlignmentFlag.AlignRight))
        send_col.addStretch()
        write_row.addLayout(send_col)
        col.addLayout(write_row)

        col.addSpacing(10)
        foot = QHBoxLayout()
        foot_buttons = QWidget()
        foot_flow = FlowLayout(foot_buttons, hspacing=6, vspacing=6)
        self.zoom_toggle = QPushButton("Zoomed Avatar")
        self.zoom_toggle.setObjectName("pill")
        self.zoom_toggle.setCheckable(True)
        self.zoom_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_toggle.setChecked(self.ui_state.value("zoom", False, type=bool))
        self.zoom_toggle.toggled.connect(lambda _: self.refresh_preview())
        foot_flow.addWidget(self.zoom_toggle)
        self.framing_btn = QPushButton("Edit Framing")
        self.framing_btn.setObjectName("pill")
        self.framing_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.framing_btn.setToolTip("Move or zoom this character's avatar and save it as the default")
        self.framing_btn.clicked.connect(self.edit_framing)
        foot_flow.addWidget(self.framing_btn)
        save = QPushButton("Save as Default")
        save.setObjectName("pill")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setToolTip("Make the \"As\" name this character's default display name")
        save.clicked.connect(self.save_default_name)
        foot_flow.addWidget(save)
        for b in (self.zoom_toggle, self.framing_btn, save):
            b.setProperty("compact", True)
        foot.addWidget(foot_buttons, 1)
        col.addLayout(foot)
        layout.addWidget(composer)
        return panel

    # ---- views --------------------------------------------------------

    def slot(self, key, view, widget=None, align=None):
        """An empty holder for a widget that both views share; set_view moves the widget between holders."""
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        if align is not None:
            box.setAlignment(align)
        self.slots.setdefault(key, {})[view] = holder
        if widget is not None:
            self.shared[key] = widget
            box.addWidget(widget)
        return holder

    def set_view(self, view):
        if view not in VIEWS:
            view = "classic"
        self.view = view
        for key, widget in self.shared.items():
            self.slots[key][view].layout().addWidget(widget)
        self.rail.set_horizontal(view == "tarot")
        self.fit_edit_layout()
        self.stack.setCurrentIndex(list(VIEWS).index(view))
        self.view_actions[view].setChecked(True)
        if view == "classic":
            self.fit_composer()
        else:
            self.update_stage()
            card = self.deck_cards.get(self.selected_cid)
            if card:
                QTimer.singleShot(0, lambda: self.deck_scroll.ensureWidgetVisible(card, 60, 0))

    def _build_tarot(self):
        tarot = QWidget()
        tarot.setObjectName("tarot")
        tarot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # The faction menu runs the full height; the message panel, stage and deck share the rest.
        root = QHBoxLayout(tarot)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.slot("nav", "tarot"))
        right = QVBoxLayout()
        right.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(0)

        stage_col = QVBoxLayout()
        stage_col.setContentsMargins(24, 18, 24, 6)
        stage_col.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.tarot_title = label("", font=display_font(24, QFont.Weight.Bold, 106))
        self.tarot_title.setStyleSheet(f"color: {TAROT_GOLD};")
        self.tarot_count = label("", font=body_font(17, italic=True))
        self.tarot_count.setStyleSheet(f"color: {TAROT_LAVENDER};")
        head.addWidget(self.tarot_title)
        head.addWidget(self.tarot_count, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch()
        head.addWidget(self.slot("search", "tarot"))
        sort_label = label("Sort by", font=body_font(15))
        sort_label.setStyleSheet(f"color: {TAROT_LAVENDER};")
        head.addWidget(sort_label)
        head.addWidget(self.slot("sort", "tarot"))
        stage_col.addLayout(head)
        self.stage = TarotStage()
        self.stage.stepRequested.connect(self.step_card)
        stage_col.addWidget(self.stage, 1)
        # In Edit Mode the message list takes the stage's place.
        stage_col.addWidget(self.slot("edits", "tarot"), 1)

        reading = QWidget()
        reading.setObjectName("reading")
        reading.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        reading.setFixedWidth(410)
        rl = QVBoxLayout(reading)
        rl.setContentsMargins(20, 16, 20, 16)
        rl.setSpacing(10)
        rhead = QHBoxLayout()
        rhead.setSpacing(10)
        heading = label("MESSAGE", font=display_font(12, QFont.Weight.DemiBold, 124))
        heading.setStyleSheet("color: #8d87c4;")
        self.tarot_where = label("", font=body_font(15, italic=True))
        self.tarot_where.setStyleSheet(f"color: {TAROT_LAVENDER};")
        self.tarot_where.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rhead.addWidget(heading)
        rhead.addWidget(self.tarot_where, 1)
        rhead.addWidget(self.slot("counter", "tarot"))
        rl.addLayout(rhead)
        rl.addWidget(self.slot("rail", "tarot"))
        rl.addWidget(self.slot("channel", "tarot"))
        rl.addWidget(self.slot("as", "tarot"))
        preview = self.slot("preview", "tarot")
        preview.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        rl.addWidget(preview, 1)
        rl.addWidget(self.slot("message", "tarot"))

        options = QHBoxLayout()
        options.setSpacing(6)
        image = QPushButton("Image")
        image.setToolTip("Attach images (or drop them anywhere on the window)")
        image.clicked.connect(self.add_images)
        save = QPushButton("Save Name")
        save.setToolTip("Make the \"As\" name this character's default display name")
        save.clicked.connect(self.save_default_name)
        self.tarot_zoom = QPushButton("Zoom")
        self.tarot_zoom.setCheckable(True)
        self.tarot_zoom.setChecked(self.zoom_toggle.isChecked())
        self.tarot_zoom.toggled.connect(self.zoom_toggle.setChecked)
        self.zoom_toggle.toggled.connect(self.tarot_zoom.setChecked)
        self.tarot_framing = QPushButton("Framing")
        self.tarot_framing.setToolTip("Move or zoom this character's avatar and save it as the default")
        self.tarot_framing.clicked.connect(self.edit_framing)
        for b in (image, save, self.tarot_zoom, self.tarot_framing):
            b.setObjectName("pill")
            b.setProperty("compact", True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            options.addWidget(b, 1)
        rl.addLayout(options)
        self.post_btn = QPushButton("POST")
        self.post_btn.setObjectName("post")
        self.post_btn.setFixedHeight(44)
        self.post_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.post_btn.setToolTip("Post to Discord (or press Enter in the message box)")
        self.post_btn.clicked.connect(self.send)
        rl.addWidget(self.post_btn)
        top.addWidget(reading)
        top.addLayout(stage_col, 1)
        right.addLayout(top, 1)

        deck = QWidget()
        deck.setObjectName("deck")
        deck.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dl = QVBoxLayout(deck)
        dl.setContentsMargins(18, 10, 18, 4)
        self.deck_scroll = DeckScroll()
        self.deck_scroll.setWidgetResizable(True)
        self.deck_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.deck_scroll.setFixedHeight(DeckCard.H + DeckCard.LIFT + 2 + 16)
        dl.addWidget(self.deck_scroll)
        right.addWidget(deck)
        root.addLayout(right, 1)
        return tarot

    def populate_deck(self):
        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.deck_cards = {}
        ordered = sorted(self.campaign_characters().items(),
                         key=lambda kv: SORT_KEYS[self.sort_combo.currentText()](kv[1]))
        for cid, c in ordered:
            card = DeckCard(cid, c, self.pixmap(cid))
            card.set_selected(cid == self.selected_cid)
            card.clicked.connect(self.select_character)
            card.menuRequested.connect(self.tile_menu)
            card.stepRequested.connect(self.step_card)
            row.addWidget(card)
            self.deck_cards[cid] = card
        self.deck_scroll.setWidget(content)

    def deck_order(self):
        return [cid for cid, card in self.deck_cards.items() if not card.isHidden()]

    def step_card(self, delta):
        order = self.deck_order()
        if not order:
            return
        i = order.index(self.selected_cid) + delta if self.selected_cid in order else 0
        cid = order[max(0, min(len(order) - 1, i))]
        if cid != self.selected_cid:
            self.select_character(cid)
        card = self.deck_cards[cid]
        self.deck_scroll.ensureWidgetVisible(card, 60, 0)
        if self.focusWidget() in self.deck_cards.values():
            card.setFocus()

    def portrait(self, cid):
        """The character's full portrait art (not the round avatar crop), sized for the tarot card."""
        if cid not in self.portraits:
            from PIL import Image
            pix = QPixmap()
            try:
                with Image.open(ROOT / self.characters[cid]["source"]) as im:
                    im = im.convert("RGBA")
                    im.thumbnail((760, 1100), Image.LANCZOS)
                    data = im.tobytes("raw", "RGBA")
                    pix = QPixmap.fromImage(QImage(data, im.width, im.height, im.width * 4,
                                                   QImage.Format.Format_RGBA8888).copy())
            except OSError:
                pix = self.pixmap(cid)
            self.portraits[cid] = pix
        return self.portraits[cid]

    def update_stage(self):
        if not hasattr(self, "stage"):
            return
        for cid, card in self.deck_cards.items():
            card.set_selected(cid == self.selected_cid)
        if self.view != "tarot":
            return
        cid = self.selected_cid
        if not cid:
            return self.stage.set_cards(None)
        order = self.deck_order()
        prev = nxt = None
        if cid in order:
            i = order.index(cid)
            if i > 0:
                prev = (self.characters[order[i - 1]], self.portrait(order[i - 1]))
            if i < len(order) - 1:
                nxt = (self.characters[order[i + 1]], self.portrait(order[i + 1]))
        self.stage.set_cards((self.characters[cid], self.portrait(cid)), prev, nxt)

    def _set_sending(self, on):
        editing = self.edit_mode
        labels = ((self.send_btn, "SAVE EDIT" if editing else "SEAL && SEND"),
                  (self.post_btn, "SAVE EDIT" if editing else "POST"))
        for button, text in labels:
            button.setEnabled(not on and (not editing or bool(self.edit_target)))
            button.setText(("SAVING…" if editing else "SENDING…") if on else text)

    # ---- roster -------------------------------------------------------

    def populate_nav(self):
        for b in self.nav_group.buttons():
            self.nav_group.removeButton(b)
            self.nav_layout.removeWidget(b)  # right away, so drops never see the old entries
            b.hide()
            b.deleteLater()
        entries = [(FAVORITES, f"Favorites  ({self.favorite_count()})", star_icon()),
                   (ALL, "All Factions", dot_icon(GOLD))]
        for faction in self.faction_order():
            entries.append((faction, faction_label(faction), dot_icon(FACTION_COLORS.get(faction, GOLD))))
        if self.mode not in [e[0] for e in entries]:
            self.mode = ALL
        for mode, text, icon in entries:
            is_faction = mode not in (ALL, FAVORITES)
            b = NavButton(icon, "  " + text, mode, draggable=is_faction)
            b.setChecked(mode == self.mode)
            if is_faction:
                b.setToolTip("Drag (or Ctrl+Up/Down) to reorder · right-click to rename")
                b.customContextMenuRequested.connect(lambda _, btn=b: self.nav_menu(btn))
                b.moveRequested.connect(self.step_faction)
            self.nav_group.addButton(b)
            self.nav_layout.addWidget(b)
        # Widen the rail so the longest faction name is never cut off.
        rail = self.nav_list.parentWidget()
        rail.setMinimumWidth(max(200, max(b.sizeHint().width() for b in self.nav_group.buttons()) + 28))
        # ...plus room for its scrollbar when a short window makes it scroll.
        width = max(260, rail.minimumWidth() + 12)
        self.nav_scroll.setMinimumWidth(width)
        self.slots["nav"]["tarot"].setFixedWidth(width)

    def favorite_count(self):
        return sum(1 for c in self.campaign_characters().values() if c.get("favorite"))

    def update_favorites_label(self):
        for b in self.nav_group.buttons():
            if b.property("mode") == FAVORITES:
                b.setText(f"  Favorites  ({self.favorite_count()})")

    def pixmap(self, cid, zoomed=False):
        key = (cid, zoomed)
        if key not in self.pixmaps:
            self.pixmaps[key] = QPixmap(str(catalog.AVATARS_DIR / self.avatar_path(cid, zoomed)))
        return self.pixmaps[key]

    def avatar_path(self, cid, zoomed):
        """The avatar file to use: the close-up when asked for and the character has one."""
        c = self.characters[cid]
        return catalog.zoom_avatar(c) if zoomed and c.get("zoom") else c["avatar"]

    def use_zoom(self, cid):
        return bool(cid) and bool(self.characters[cid].get("zoom")) and self.zoom_toggle.isChecked()

    def populate_roster(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 18, 12, 24)
        layout.setSpacing(28)
        self.tiles, self.sections = {}, []
        by_faction = self.sort_combo.currentText() == "Faction"
        ordered = sorted(self.campaign_characters().items(),
                         key=lambda kv: SORT_KEYS[self.sort_combo.currentText()](kv[1]))
        section = None
        for cid, c in ordered:
            title = c["faction"] if by_faction else None
            if section is None or (by_faction and section.property("faction") != title):
                section = RosterSection(faction_label(title) if title else None)
                section.setProperty("faction", title)
                section.reordered.connect(self.save_order)
                self.sections.append(section)
                layout.addWidget(section)
            tile = PortraitTile(cid, c, self.pixmap(cid))
            tile.set_selected(cid == self.selected_cid)
            tile.clicked.connect(self.select_character)
            tile.favoriteToggled.connect(self.toggle_favorite)
            tile.menuRequested.connect(self.tile_menu)
            tile.draggable = by_faction
            if by_faction:
                tile.setToolTip(tile.toolTip() + "\nDrag (or Ctrl+Left/Right) to reorder within the faction")
                tile.moveRequested.connect(self.step_character)
            section.add(tile)
            self.tiles[cid] = tile
        layout.addStretch()
        self.scroll.setWidget(content)
        self.populate_deck()
        self.apply_filter()

    def save_order(self, cids):
        for i, cid in enumerate(cids):
            self.characters[cid]["order"] = i
        catalog.save_characters(self.characters)
        self.populate_deck()
        self.apply_filter()
        self.statusBar().showMessage(f'Saved the order of {faction_label(self.characters[cids[0]]["faction"])}', 3000)

    def step_character(self, cid, delta):
        section = next(sec for sec in self.sections if any(t.cid == cid for t in sec.tiles))
        section.step(cid, delta)
        self.tiles[cid].setFocus()

    def set_mode(self, mode):
        self.mode = mode
        self.apply_filter()
        self.scroll.verticalScrollBar().setValue(0)

    def apply_filter(self):
        needle = self.search.text().strip().lower()
        shown = 0
        for cid, tile in self.tiles.items():
            c = self.characters[cid]
            visible = needle in c["name"].lower() and (
                self.mode == ALL
                or (self.mode == FAVORITES and c.get("favorite"))
                or c["faction"] == self.mode)
            tile.setVisible(bool(visible))
            if cid in self.deck_cards:
                self.deck_cards[cid].setVisible(bool(visible))
            shown += bool(visible)
        single_faction = self.mode not in (ALL, FAVORITES)
        for section in self.sections:
            section.setVisible(any(t.isVisibleTo(section) for t in section.tiles))
            section.header.setVisible(bool(section.property("faction")) and not single_faction)

        self.title.setText({ALL: self.campaign, FAVORITES: "Favorites"}.get(self.mode, faction_label(self.mode)))
        self.count.setText(f"{shown} soul" if shown == 1 else f"{shown} souls")
        self.tarot_title.setText(self.title.text())
        self.tarot_count.setText(self.count.text())
        self.update_stage()
        if shown:
            self.empty.hide()
            self.scroll.show()
        else:
            self.scroll.hide()
            self.empty.show()
            if not self.tiles:
                self.empty.setText(f"No characters in {self.campaign} yet.\nAdd faction folders to "
                                   f"Portraits/{self.campaign}/, then choose File → Rescan portraits.")
            elif self.mode == FAVORITES and not needle:
                self.empty.setText("No favorites yet.\nHover a portrait and click its star, or press F.")
            else:
                self.empty.setText("No one answers to that name.")

    def select_character(self, cid, reset_name=True):
        if cid not in self.characters:
            return
        if self.selected_cid in self.tiles:
            self.tiles[self.selected_cid].set_selected(False)
        self.selected_cid = cid
        if cid in self.tiles:
            self.tiles[cid].set_selected(True)
        if reset_name and not self.edit_target:
            self.name_edit.setText(self.characters[cid]["name"])
        self.refresh_preview()

    def toggle_favorite(self, cid):
        c = self.characters[cid]
        if c.get("favorite"):
            c.pop("favorite")
        else:
            c["favorite"] = True
        catalog.save_characters(self.characters)
        self.tiles[cid].set_favorite(bool(c.get("favorite")))
        if cid in self.deck_cards:
            self.deck_cards[cid].update()
        self.update_favorites_label()
        if self.mode == FAVORITES:
            self.apply_filter()

    def reset_name(self):
        if self.selected_cid and not self.edit_target:
            self.name_edit.setText(self.characters[self.selected_cid]["name"])

    def save_default_name(self):
        cid, name = self.selected_cid, self.name_edit.text().strip()
        if not cid or not name:
            return
        self.set_default_name(cid, name)

    def edit_framing(self):
        cid = self.selected_cid
        if not cid:
            return QMessageBox.information(self, "Edit framing", "Pick a character first.")
        c = self.characters[cid]
        dialog = FramingDialog(self, c, "zoom" if self.use_zoom(cid) else "crop")
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.changes():
            return
        for kind, crop in dialog.changes().items():
            c[kind] = crop
            avatar = catalog.zoom_avatar(c) if kind == "zoom" else c["avatar"]
            catalog.render_avatar(catalog.ROOT / c["source"], catalog.AVATARS_DIR / avatar, crop, c.get("background"))
            self.pixmaps.pop((cid, kind == "zoom"), None)
        catalog.save_characters(self.characters)
        if cid in self.tiles:
            self.tiles[cid].set_source(self.pixmap(cid))
        if cid in self.deck_cards:
            self.deck_cards[cid].set_avatar(self.pixmap(cid))
        self.refresh_preview()
        self.statusBar().showMessage(
            f"Framing saved for {c['name']}. Push avatars/ to GitHub so Discord shows it.", 8000)

    # ---- renaming & faction order -----------------------------------------

    def tile_menu(self, cid, pos):
        c = self.characters[cid]
        menu = QMenu(self)
        menu.addAction("Rename…", lambda: self.rename_character(cid))
        menu.addAction("Remove from Favorites" if c.get("favorite") else "Add to Favorites",
                       lambda: self.toggle_favorite(cid))
        menu.addAction("Edit Framing…", lambda: (self.select_character(cid), self.edit_framing()))
        menu.exec(pos)

    def rename_character(self, cid):
        c = self.characters[cid]
        name, ok = QInputDialog.getText(self, "Rename character",
                                        f"Default display name for {c['name']}:", text=c["name"])
        name = name.strip()
        if not ok or not name or name == c["name"]:
            return
        problems = [p for p in discord_client.validate_message("x", name, []) if p]
        if problems:
            return QMessageBox.warning(self, "Rename character", "\n".join(problems))
        self.set_default_name(cid, name)

    def set_default_name(self, cid, name):
        c = self.characters[cid]
        old = c["name"]
        c["name"] = name
        catalog.save_characters(self.characters)
        self.tiles[cid].set_name(name)
        if cid in self.deck_cards:
            self.deck_cards[cid].refresh_text()
        if cid == self.selected_cid and self.name_edit.text().strip() in (old, ""):
            self.name_edit.setText(name)
        if self.sort_combo.currentText() == "Name":
            self.populate_roster()
        self.profile.update()
        self.refresh_preview()
        self.statusBar().showMessage(f"Default name saved: {name}", 4000)

    def nav_menu(self, button):
        faction = button.property("mode")
        if faction in (ALL, FAVORITES):
            return
        order = self.faction_order()
        i = order.index(faction)
        menu = QMenu(self)
        menu.addAction("Rename faction…", lambda: self.rename_faction(faction))
        if faction in FACTION_NAMES:
            menu.addAction(f'Reset name to "{faction}"', lambda: self.rename_faction(faction, faction))
        menu.addSeparator()
        up = menu.addAction("Move up", lambda: self.move_faction(faction, i - 1))
        down = menu.addAction("Move down", lambda: self.move_faction(faction, i + 2))
        up.setEnabled(i > 0)
        down.setEnabled(i < len(order) - 1)
        menu.addSeparator()
        menu.addAction("Move to top", lambda: self.move_faction(faction, 0)).setEnabled(i > 0)
        menu.addAction("Move to bottom", lambda: self.move_faction(faction, len(order))).setEnabled(i < len(order) - 1)
        menu.exec(button.mapToGlobal(QPoint(24, button.height())))

    def faction_order(self):
        return sorted({c["faction"] for c in self.campaign_characters().values()}, key=faction_key)

    def rename_faction(self, faction, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Rename faction",
                                            f'Name shown for the "{faction}" folder:', text=faction_label(faction))
            if not ok:
                return
        name = name.strip()
        if not name or name == faction:
            FACTION_NAMES.pop(faction, None)
        else:
            FACTION_NAMES[faction] = name
        save_factions()
        self.populate_nav()
        self.populate_roster()
        self.refresh_preview()

    def step_faction(self, faction, delta):
        i = self.faction_order().index(faction)
        self.move_faction(faction, i + (2 if delta > 0 else -1))
        for b in self.nav_group.buttons():
            if b.property("mode") == faction:
                b.setFocus()

    def move_faction(self, faction, index):
        """Move `faction` so it sits before the entry currently at `index` (len = the end)."""
        order = self.faction_order()
        old = order.index(faction)
        index = max(0, min(index, len(order)))
        if index > old:
            index -= 1
        order.remove(faction)
        order.insert(index, faction)
        if order == self.faction_order():
            return
        FACTION_ORDER[:] = order + [f for f in FACTION_ORDER if f not in order]
        save_factions()
        self.populate_nav()
        self.populate_roster()
        self.statusBar().showMessage(f"Moved {faction_label(faction)}", 3000)

    # ---- campaigns ------------------------------------------------------

    def campaign_list(self):
        names = set(catalog.campaigns()) | {c.get("campaign", catalog.DEFAULT_CAMPAIGN) for c in self.characters.values()}
        order = [n for n in FACTIONS_DATA.get("campaign_order", []) if n in names]
        return order + sorted(names - set(order))

    def campaign_characters(self):
        return {cid: c for cid, c in self.characters.items()
                if c.get("campaign", catalog.DEFAULT_CAMPAIGN) == self.campaign}

    def campaign_menu(self):
        menu = QMenu(self)
        for name in self.campaign_list():
            n = sum(1 for c in self.characters.values() if c.get("campaign") == name)
            action = menu.addAction(f"{name}   ({n})", lambda _=False, nm=name: self.switch_campaign(nm))
            action.setCheckable(True)
            action.setChecked(name == self.campaign)
        menu.addSeparator()
        menu.addAction("New campaign…", self.new_campaign)
        card = self.campaign_card
        menu.exec(card.mapToGlobal(QPoint(0, card.height() + 2)))

    def campaign_context_menu(self):
        order = self.campaign_list()
        i = order.index(self.campaign) if self.campaign in order else 0
        menu = QMenu(self)
        menu.addAction("Rename campaign…", self.rename_campaign)
        menu.addAction("Open campaign folder", self.open_campaign_folder)
        menu.addSeparator()
        menu.addAction("Move up in list", lambda: self.move_campaign(-1)).setEnabled(i > 0)
        menu.addAction("Move down in list", lambda: self.move_campaign(1)).setEnabled(i < len(order) - 1)
        menu.addSeparator()
        menu.addAction("New campaign…", self.new_campaign)
        card = self.campaign_card
        menu.exec(card.mapToGlobal(QPoint(0, card.height() + 2)))

    def switch_campaign(self, name, force=False):
        if name == self.campaign and not force:
            return
        if self.selected_cid:
            self.selected_by_campaign[self.campaign] = self.selected_cid
        self.campaign = name
        load_factions(name)
        self.mode = ALL
        self.selected_cid = None
        self.campaign_card.set_campaign(name)
        self.populate_nav()
        self.populate_roster()
        cid = self.selected_by_campaign.get(name)
        if cid in self.campaign_characters():
            self.select_character(cid)
        else:
            self.name_edit.clear()
            self.refresh_preview()

    def _campaign_name(self, title, current=""):
        while True:
            name, ok = QInputDialog.getText(self, title, "Campaign name:", text=current)
            name = name.strip()
            if not ok or not name or name == current:
                return None
            if re.search(r'[<>:"/\\|?*]', name) or name.endswith("."):
                QMessageBox.warning(self, title, 'A campaign name can\'t contain < > : " / \\ | ? * or end in a dot.')
            elif name in self.campaign_list():
                QMessageBox.warning(self, title, f'There\'s already a campaign called "{name}".')
            else:
                return name

    def new_campaign(self):
        name = self._campaign_name("New campaign")
        if not name:
            return
        folder = catalog.PORTRAITS_DIR / name
        folder.mkdir(parents=True, exist_ok=True)
        FACTIONS_DATA["campaign_order"] = self.campaign_list()
        self.switch_campaign(name)
        save_factions()
        answer = QMessageBox.question(
            self, "New campaign",
            f"Created {name}.\n\nAdd a folder for each faction inside Portraits/{name}/ with its portraits, "
            "then choose File → Rescan portraits.\n\nOpen the folder now?")
        if answer == QMessageBox.StandardButton.Yes:
            self.open_campaign_folder()

    def rename_campaign(self):
        old = self.campaign
        new = self._campaign_name("Rename campaign", old)
        if not new:
            return
        try:
            catalog.rename_campaign(self.characters, old, new)
        except OSError as e:
            return QMessageBox.warning(self, "Rename campaign",
                                       f"Couldn't rename the folder (is a file in it open elsewhere?).\n{e}")
        FACTIONS_DATA["campaigns"][new] = FACTIONS_DATA["campaigns"].pop(old, {})
        FACTIONS_DATA["campaign_order"] = [new if n == old else n for n in FACTIONS_DATA.get("campaign_order", [])]
        if old in self.selected_by_campaign:
            self.selected_by_campaign[new] = self.selected_by_campaign.pop(old)
        self.campaign = new
        CURRENT_CAMPAIGN[0] = new
        save_factions()
        self.campaign_card.set_campaign(new)
        self.apply_filter()
        self.statusBar().showMessage(f"Renamed campaign to {new}", 4000)

    def move_campaign(self, delta):
        order = self.campaign_list()
        i = order.index(self.campaign)
        j = max(0, min(len(order) - 1, i + delta))
        order[i], order[j] = order[j], order[i]
        FACTIONS_DATA["campaign_order"] = order
        save_factions()

    def open_campaign_folder(self):
        folder = catalog.PORTRAITS_DIR / self.campaign
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def resync(self, force):
        self.characters = run_sync(self, force)
        self.pixmaps.clear()
        self.portraits.clear()
        if self.campaign not in self.campaign_list():
            self.campaign = next(iter(self.campaign_list()), catalog.DEFAULT_CAMPAIGN)
            self.campaign_card.set_campaign(self.campaign)
        load_factions(self.campaign)
        self.populate_nav()
        self.populate_roster()
        if self.selected_cid not in self.campaign_characters():
            self.selected_cid = None
        self.refresh_preview()
        self.statusBar().showMessage(
            f"{len(self.characters)} characters loaded. Push avatars/ to GitHub so new avatars show in Discord.", 8000)

    # ---- channels -----------------------------------------------------

    # ---- servers & channels ------------------------------------------

    def _load_servers(self):
        data = servers.load(CHANNELS_FILE)
        if servers.is_legacy(data):
            return self._migrate_channels(data)
        return data.get("servers", {})

    def _migrate_channels(self, flat):
        """One-off: group the old flat channel list by Discord server (asks for each server's name)."""
        def guild_of(url):
            try:
                return discord_client.fetch_webhook_info(url).get("guild_id")
            except discord_client.WebhookError:
                return None

        def name_for(guild_id, channels, taken):
            default = next(n for n in ("My Server", *(f"Server {i}" for i in range(2, 99))) if n not in taken)
            name, ok = QInputDialog.getText(
                None, "Name this server",
                "Channels are now grouped by Discord server.\n"
                f"What should the server with # {', # '.join(channels)} be called?", text=default)
            name = name.strip() if ok else ""
            return name if name and name not in taken else default

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            grouped = servers.migrate(flat, guild_of, name_for)
        finally:
            QApplication.restoreOverrideCursor()
        # The last-message history was keyed by channel name alone.
        for name, server in grouped.items():
            for channel in server["channels"]:
                if channel in self.history:
                    self.history[servers.history_key(name, channel)] = self.history.pop(channel)
        save_json(HISTORY_FILE, self.history)
        servers.save(CHANNELS_FILE, grouped)
        if self.ui_state.value("channel"):
            owner = next((n for n, sv in grouped.items() if self.ui_state.value("channel") in sv["channels"]), None)
            if owner:
                self.ui_state.setValue("server", owner)
                self.last_channel[owner] = self.ui_state.value("channel")
        return grouped

    def save_servers(self):
        servers.save(CHANNELS_FILE, self.servers)

    def channel_url(self, server, channel):
        return self.servers.get(server, {}).get("channels", {}).get(channel)

    def populate_servers(self, select=None):
        if select not in self.servers:
            select = self.current_server if self.current_server in self.servers else next(iter(self.servers), "")
        self.current_server = select
        self.rail.set_servers(list(self.servers), select, {n: self.server_image(n) for n in self.servers})
        self.server_label.setText(select.upper() if select else "NO SERVER YET")
        self.populate_channels(self.last_channel.get(select))

    def select_server(self, name):
        if self.channel_box.current():
            self.last_channel[self.current_server] = self.channel_box.current()
        self.populate_servers(name)

    def select_channel(self, channel):
        self.last_channel[self.current_server] = channel
        self.channel_changed()
        self.refresh_preview()

    def populate_channels(self, select=None):
        channels = self.servers.get(self.current_server, {}).get("channels", {})
        select = select if select in channels else next(iter(channels), "")
        if select:
            self.last_channel[self.current_server] = select
        self.channel_box.set_channels(list(channels), select)
        self.channel_changed()
        self.refresh_preview()
        self.fit_composer()

    def fit_composer(self):
        """Never squeeze the composer (the channel row's flow layout hides its true height from Qt);
        the preview above scrolls instead."""
        lay = self.composer.layout()
        lay.activate()
        width = self.composer.width() if self.composer.width() > 100 else 510
        need = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.totalMinimumSize().height()
        self.composer.setMinimumHeight(max(need, lay.totalMinimumSize().height()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "composer"):
            self.fit_composer()

    def server_for_guild(self, guild_id):
        if not guild_id:
            return None
        return next((n for n, sv in self.servers.items() if sv.get("guild_id") == guild_id), None)

    def ask_server_name(self, title, prompt, current=""):
        while True:
            name, ok = QInputDialog.getText(self, title, prompt, text=current)
            name = name.strip()
            if not ok or not name:
                return None
            if name == current or name not in self.servers:
                return name
            QMessageBox.warning(self, title, f'There\'s already a server called "{name}".')

    def add_channel(self, new_server=False):
        dlg = AddChannelDialog(self, new_server)
        if not dlg.exec():
            return
        name, url = dlg.name.text().strip(), dlg.url.text().strip()
        guild_id = dlg.info.get("guild_id")
        server = self.server_for_guild(guild_id)
        if server is None and not new_server and self.current_server \
                and not self.servers[self.current_server].get("guild_id"):
            server = self.current_server  # server added before Discord ids were tracked
            self.servers[server]["guild_id"] = guild_id
        if server is None:
            server = self.ask_server_name("New server", "This webhook posts to a server you haven't added yet.\n"
                                                        "What should the server be called?")
            if not server:
                return
            self.servers[server] = {"guild_id": guild_id, "channels": {}}
        channels = self.servers[server]["channels"]
        if name in channels:
            return QMessageBox.warning(self, "Add channel", f'"{server}" already has a channel called "# {name}".')
        channels[name] = url
        self.save_servers()
        moved = server != self.current_server and self.current_server and not new_server
        self.last_channel[server] = name
        self.populate_servers(server)
        self.statusBar().showMessage(
            f'Added # {name} to {server}' + (" (that's the server this webhook posts to)" if moved else ""), 8000)

    def remove_channel(self, name):
        server = self.current_server
        if QMessageBox.question(self, "Remove channel", f'Remove "# {name}" from {server}?') \
                == QMessageBox.StandardButton.Yes:
            del self.servers[server]["channels"][name]
            self.history.pop(servers.history_key(server, name), None)
            save_json(HISTORY_FILE, self.history)
            self.save_servers()
            self.populate_channels(self.channel_box.current())

    def rename_server(self, old):
        new = self.ask_server_name("Rename server", "Server name:", old)
        if not new or new == old:
            return
        self.servers = {(new if k == old else k): v for k, v in self.servers.items()}
        prefix = servers.history_key(old, "")
        self.history = {(servers.history_key(new, k[len(prefix):]) if k.startswith(prefix) else k): v
                        for k, v in self.history.items()}
        if old in self.last_channel:
            self.last_channel[new] = self.last_channel.pop(old)
        save_json(HISTORY_FILE, self.history)
        self.save_servers()
        self.populate_servers(new if self.current_server == old else self.current_server)

    def server_image(self, name):
        path = self.servers[name].get("icon")
        return QPixmap(str(ROOT / path)) if path and (ROOT / path).exists() else None

    def set_server_image(self, name):
        path, _ = QFileDialog.getOpenFileName(self, f"Image for {name}", "", IMAGE_FILTER)
        if not path:
            return
        from PIL import Image
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                side = min(im.size)
                left, top = (im.width - side) // 2, (im.height - side) // 2
                im = im.crop((left, top, left + side, top + side)).resize((128, 128), Image.LANCZOS)
        except OSError as e:
            return QMessageBox.warning(self, "Server image", f"Couldn't open that image.\n{e}")
        self._delete_server_image(name)
        dest = SERVER_ICONS_DIR / f"{catalog.slugify(name) or 'server'}.png"
        n = 2
        while dest.exists():
            dest = SERVER_ICONS_DIR / f"{catalog.slugify(name) or 'server'}-{n}.png"
            n += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "PNG")
        self.servers[name]["icon"] = dest.relative_to(ROOT).as_posix()
        self.save_servers()
        self.populate_servers(self.current_server)
        self.statusBar().showMessage(f"Image set for {name}", 4000)

    def clear_server_image(self, name):
        self._delete_server_image(name)
        self.servers[name].pop("icon", None)
        self.save_servers()
        self.populate_servers(self.current_server)

    def _delete_server_image(self, name):
        path = self.servers[name].get("icon")
        if path and (ROOT / path).is_file() and (ROOT / path).parent == SERVER_ICONS_DIR:
            (ROOT / path).unlink()

    def remove_server(self, name):
        n = len(self.servers[name]["channels"])
        if QMessageBox.question(self, "Remove server",
                                f'Remove "{name}" and its {n} channel{"s" if n != 1 else ""}?') \
                != QMessageBox.StandardButton.Yes:
            return
        self._delete_server_image(name)
        del self.servers[name]
        prefix = servers.history_key(name, "")
        self.history = {k: v for k, v in self.history.items() if not k.startswith(prefix)}
        self.last_channel.pop(name, None)
        save_json(HISTORY_FILE, self.history)
        self.save_servers()
        self.populate_servers()

    # ---- settings -----------------------------------------------------

    def open_settings(self):
        sample = next(iter(self.characters.values()), {}).get("avatar")
        dlg = SettingsDialog(self, self.settings, sample)
        if dlg.exec():
            self.settings["avatar_base_url"] = dlg.value()
            save_json(SETTINGS_FILE, self.settings)

    # ---- compose & preview --------------------------------------------

    def refresh_preview(self):
        server, channel = self.current_server, self.channel_box.current()
        self.preview_channel.setText(f"{server}  ·  # {channel}" if channel else "— add a channel —")

        last = self.history.get(servers.history_key(server, channel))
        if last and last.get("cid") in self.characters and not self.edit_mode:
            images = last.get("images", 0)
            text = last["content"] + (f"\n[{images} image{'s' if images != 1 else ''}]" if images else "")
            self.context_row.set_message(self.pixmap(last["cid"], last.get("zoom", False)), last["name"],
                                         f"Last sent here · {when_text(last['time'])}", text)
            self.context_row.show()
        else:
            self.context_row.hide()

        cid = self.selected_cid
        zoomed = self.use_zoom(cid)
        has_zoom = bool(cid) and bool(self.characters[cid].get("zoom"))
        self.zoom_toggle.setEnabled(has_zoom)
        self.framing_btn.setEnabled(bool(cid))
        self.tarot_zoom.setEnabled(has_zoom)
        self.tarot_framing.setEnabled(bool(cid))
        self.tarot_zoom.setToolTip("Post with a close-up of the face" if has_zoom
                                   else "This character has no zoomed avatar")
        self.tarot_where.setText(self.preview_channel.text())
        self.zoom_toggle.setToolTip("Post with a close-up of the face" if has_zoom
                                    else "This character has no zoomed avatar")
        self.profile.set_character(self.characters.get(cid), self.pixmap(cid, zoomed) if cid else QPixmap())
        self.update_stage()
        t = self.edit_target
        shown = bool(t) if self.edit_mode else bool(cid)
        self.message_row.setVisible(shown)
        self.placeholder.setVisible(not shown)
        self.placeholder.setText("Pick a message above to edit it." if self.edit_mode
                                 else "Choose a character from the roster.")
        if t:
            kept = len(t["attachments"]) if self.keep_images.isChecked() else 0
            meta = f"editing · posted {when_text(t['time'])}"
            if kept:
                meta += f" · keeps {kept} image{'s' if kept != 1 else ''}"
            avatar = self.pixmap(t["cid"], t["zoom"]) if t["cid"] in self.characters else QPixmap()
            self.message_row.set_message(avatar, t["name"], meta, self.message.toPlainText(),
                                         self.attachments, removable=True)
        elif shown:
            self.message_row.set_message(self.pixmap(cid, zoomed), self.name_edit.text().strip(),
                                         f'{faction_label(self.characters[cid]["faction"])} · unsent',
                                         self.message.toPlainText(), self.attachments, removable=True)
        n = len(self.message.toPlainText())
        self.counter.setText(f"{n} / {discord_client.MAX_CONTENT}")
        self.counter.setStyleSheet(f"color: {'#e06a5a' if n > discord_client.MAX_CONTENT else MUTED};")

    def add_images(self):
        start = self.ui_state.value("last_image_dir", str(Path.home()))
        files, _ = QFileDialog.getOpenFileNames(self, "Attach images", start, IMAGE_FILTER)
        if files:
            self.ui_state.setValue("last_image_dir", str(Path(files[0]).parent))
            self.add_attachments(files)

    def add_attachments(self, paths):
        for p in paths:
            if p not in self.attachments and Path(p).suffix.lower() in IMAGE_SUFFIXES:
                self.attachments.append(p)
        self.refresh_preview()

    def remove_attachment(self, path):
        if path in self.attachments:
            self.attachments.remove(path)
        self.refresh_preview()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_attachments([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    def avatar_url(self, cid, zoomed=False):
        base = self.settings.get("avatar_base_url", "").strip()
        return f'{base.rstrip("/")}/{self.avatar_path(cid, zoomed)}' if base else None

    def send(self):
        if self.worker and self.worker.isRunning():
            return
        if self.edit_mode:
            return self.save_edit()
        cid, server, channel = self.selected_cid, self.current_server, self.channel_box.current()
        if not cid:
            return QMessageBox.warning(self, "Send", "Pick a character first.")
        if not channel:
            return QMessageBox.warning(self, "Send", "Add a channel first.")
        content = self.message.toPlainText()
        username = self.name_edit.text().strip()
        files = list(self.attachments)
        problems = discord_client.validate_message(content, username, files)
        if problems:
            return QMessageBox.warning(self, "Send", "\n".join(problems))

        zoomed = self.use_zoom(cid)
        avatar = self.avatar_url(cid, zoomed)
        if not avatar and not self.warned_no_avatar:
            answer = QMessageBox.question(
                self, "No avatar URL",
                "No avatar base URL is set (File → Settings), so the message will use the webhook's "
                "default picture.\n\nSend anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.warned_no_avatar = True

        self._set_sending(True)
        self.worker = DiscordWorker(discord_client.send_message, self.channel_url(server, channel),
                                    content, username, avatar, files)
        self.worker.done.connect(
            lambda ok, result: self.on_sent(ok, result, cid, username, server, channel, content, files, zoomed))
        self.worker.start()

    def on_sent(self, ok, result, cid, username, server, channel, content, files, zoomed=False):
        self._set_sending(False)
        if not ok:
            return QMessageBox.critical(self, "Send failed", result)
        key = servers.history_key(server, channel)
        entry = {"cid": cid, "name": username, "content": content, "images": len(files),
                 "zoom": zoomed, "time": datetime.now().isoformat(timespec="seconds")}
        # Every post is remembered (with Discord's message id) so Edit Mode can find it again.
        log = list(self.history.get(key, {}).get("log", []))
        if (result or {}).get("id"):
            entry["id"] = str(result["id"])
            log.append(dict(entry))
        self.history[key] = {**entry, "log": log[-LOG_LIMIT:]}
        save_json(HISTORY_FILE, self.history)
        self.attachments.clear()
        self.message.clear()  # also refreshes the preview
        self.statusBar().showMessage(f"Sent as {username} to {server} · # {channel}", 6000)

    # ---- edit mode ----------------------------------------------------

    def _build_edit_panel(self):
        panel = self.edit_panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label("POSTED HERE", "editHeading", display_font(12, QFont.Weight.DemiBold, 124)))
        head.addStretch()
        older = QPushButton("+ Older message…")
        older.setObjectName("ghost")
        older.setCursor(Qt.CursorShape.PointingHandCursor)
        older.setToolTip("Edit a message posted before Edit Mode existed: paste its link "
                         "(in Discord, right-click the message → Copy Message Link)")
        older.clicked.connect(self.open_message_link)
        head.addWidget(older)
        layout.addLayout(head)
        self.edit_list = QListWidget()
        self.edit_list.setObjectName("editList")
        self.edit_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit_list.setAccessibleName("Messages posted to this channel")
        self.edit_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.edit_list.customContextMenuRequested.connect(self.edit_list_menu)
        self.edit_list.itemClicked.connect(lambda item: self.load_edit(item.data(Qt.ItemDataRole.UserRole)))
        self.edit_list.itemActivated.connect(lambda item: self.load_edit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.edit_list)
        status = QHBoxLayout()
        status.setSpacing(8)
        self.edit_status = label("", "muted", body_font(14, italic=True))
        # One line, no word wrap: a wrapping label would push the composer down.
        self.edit_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.keep_images = QCheckBox()
        self.keep_images.setChecked(True)
        self.keep_images.setToolTip("Untick to take the images already on the message off it")
        self.keep_images.toggled.connect(lambda _: self.refresh_preview())
        self.edit_cancel = QPushButton("Cancel")
        self.edit_cancel.setObjectName("ghost")
        self.edit_cancel.setToolTip("Stop editing this message without saving")
        self.edit_cancel.clicked.connect(self.cancel_edit)
        status.addWidget(self.edit_status, 1)
        status.addWidget(self.keep_images)
        status.addWidget(self.edit_cancel)
        layout.addLayout(status)
        panel.hide()
        return panel

    def fit_edit_layout(self):
        """Edit Mode borrows the room of the character banner (Classic) or the card stage (Tarot)."""
        on, tarot = self.edit_mode, self.view == "tarot"
        self.profile.setVisible(not on)
        self.stage.setVisible(not (on and tarot))
        if tarot:
            self.edit_list.setMinimumHeight(0)
            self.edit_list.setMaximumHeight(16777215)
        else:
            self.edit_list.setFixedHeight(150)
        if not tarot:
            self.fit_composer()

    def channel_key(self):
        return servers.history_key(self.current_server, self.channel_box.current())

    def channel_log(self, key=None):
        return list(self.history.get(key or self.channel_key(), {}).get("log", []))

    def _save_log(self, key, log):
        entry = self.history.setdefault(key, {})
        log.sort(key=lambda m: int(m["id"]))
        entry["log"] = log[-LOG_LIMIT:]
        latest = next((m for m in log if m["id"] == entry.get("id")), None)
        if latest:  # the faded "last sent" line follows edits to its message
            entry.update(latest)
        save_json(HISTORY_FILE, self.history)

    def set_edit_mode(self, on):
        if on == self.edit_mode:
            return
        self.edit_mode = on
        self.edit_button.setChecked(on)
        self.edit_target = None
        if on:
            self.draft = (self.message.toPlainText(), list(self.attachments), self.name_edit.text())
            self.attachments.clear()
            self.message.clear()
        elif self.draft:
            text, files, name = self.draft
            self.draft = None
            self.attachments = files
            self.name_edit.setText(name)
            self.message.setPlainText(text)
        self.edit_panel.setVisible(on)
        self.fit_edit_layout()
        self.populate_edit_list()
        self.update_edit_state()
        self.statusBar().showMessage("Edit Mode: pick a message to change it" if on else "Back to posting", 4000)

    def update_edit_state(self):
        t = self.edit_target
        self.name_edit.setEnabled(not t)
        if t:
            self.name_edit.setText(t["name"])
        n = len(t["attachments"]) if t else 0
        self.keep_images.setVisible(bool(n))
        self.keep_images.setText(f"Keep its {n} image{'s' if n != 1 else ''}")
        self.edit_cancel.setVisible(bool(t))
        if t:
            self.edit_status.setText(f"Editing {t['name'] or 'this'}'s message")
            self.edit_status.setToolTip("A posted message keeps the name and portrait it was posted with.")
        else:
            self.edit_status.setText("Click a message to edit it · right-click to delete it")
            self.edit_status.setToolTip("")
        self._set_sending(bool(self.worker and self.worker.isRunning()))
        self.refresh_preview()

    def populate_edit_list(self):
        self.edit_list.clear()
        if not self.edit_mode:
            return
        log = self.channel_log()
        for m in reversed(log):
            first = next((line for line in m.get("content", "").splitlines() if line.strip()), "")
            snippet = first if len(first) <= 64 else first[:63].rstrip() + "…"
            extras = []
            if m.get("images"):
                extras.append(f"{m['images']} image{'s' if m['images'] != 1 else ''}")
            if m.get("edited"):
                extras.append("edited")
            item = QListWidgetItem(f"{m.get('name') or 'Unknown'}  ·  {when_text(m['time'])}"
                                   + "".join(f"  ·  {e}" for e in extras) + f"\n{snippet or '—'}")
            item.setData(Qt.ItemDataRole.UserRole, m["id"])
            item.setToolTip(m.get("content", "")[:500])
            self.edit_list.addItem(item)
            if self.edit_target and self.edit_target["id"] == m["id"]:
                self.edit_list.setCurrentItem(item)
        if not log:
            item = QListWidgetItem("Nothing posted here from the app yet.\n"
                                   "Use “+ Older message…” to bring in an earlier post.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.edit_list.addItem(item)

    def channel_changed(self):
        if not hasattr(self, "edit_list"):
            return
        if self.edit_target and self.edit_target["key"] != self.channel_key():
            self.cancel_edit()
        self.populate_edit_list()

    def cancel_edit(self):
        self.edit_target = None
        self.attachments.clear()
        self.message.clear()
        self.edit_list.clearSelection()
        self.update_edit_state()

    def edit_list_menu(self, pos):
        item = self.edit_list.itemAt(pos)
        mid = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not mid:
            return
        key = self.channel_key()
        menu = QMenu(self)
        menu.addAction("Edit", lambda: self.load_edit(mid))
        menu.addAction("Copy message ID", lambda: QApplication.clipboard().setText(mid))
        menu.addSeparator()
        menu.addAction("Delete from Discord…", lambda: self.delete_posted(mid))
        menu.addAction("Remove from this list", lambda: self.forget_message(key, mid))
        menu.exec(self.edit_list.viewport().mapToGlobal(pos))

    def guess_character(self, name):
        """The character a message brought in by link was posted as, going by its display name."""
        name = name.strip().lower()
        for pool in (self.campaign_characters(), self.characters):
            for cid, c in pool.items():
                if c["name"].lower() == name:
                    return cid
        return None

    def open_message_link(self):
        if not self.channel_url(self.current_server, self.channel_box.current()):
            return QMessageBox.warning(self, "Older message", "Pick a channel first.")
        text, ok = QInputDialog.getText(
            self, "Older message",
            f"Paste the link of a message the app posted in # {self.channel_box.current()}\n"
            "(in Discord, right-click the message → Copy Message Link), or its ID:")
        if not ok or not text.strip():
            return
        mid = discord_client.message_id_from(text)
        if not mid:
            return QMessageBox.warning(self, "Older message", "That doesn't look like a message link or ID.")
        self.load_edit(mid)

    def load_edit(self, mid):
        if not mid or (self.edit_worker and self.edit_worker.isRunning()):
            return
        server, channel = self.current_server, self.channel_box.current()
        url = self.channel_url(server, channel)
        if not url:
            return
        self.edit_status.setText("Fetching the message from Discord…")
        self.edit_worker = DiscordWorker(discord_client.fetch_message, url, mid)
        self.edit_worker.done.connect(lambda ok, result: self.on_fetched(ok, result, server, channel, mid))
        self.edit_worker.start()

    def on_fetched(self, ok, result, server, channel, mid):
        key = servers.history_key(server, channel)
        if not self.edit_mode or key != self.channel_key():
            return
        log = self.channel_log(key)
        entry = next((m for m in log if m["id"] == mid), None)
        if not ok:
            self.update_edit_state()
            if entry and "can't find" in result:
                answer = QMessageBox.question(self, "Message not found", f"{result}\n\nRemove it from the list?")
                if answer == QMessageBox.StandardButton.Yes:
                    self.forget_message(key, mid)
                return
            return QMessageBox.warning(self, "Couldn't load the message", result)
        name = (result.get("author") or {}).get("username", "")
        if entry is None:
            entry = {"id": mid, "cid": self.guess_character(name), "name": name, "zoom": False,
                     "time": local_time(result.get("timestamp"))}
            log.append(entry)
        # Discord has the final say: the message may have been changed since.
        entry["content"] = result.get("content", "")
        entry["images"] = len(result.get("attachments", []))
        self._save_log(key, log)
        self.edit_target = {"key": key, "id": mid, "cid": entry.get("cid"), "name": entry.get("name") or name,
                            "zoom": entry.get("zoom", False), "time": entry["time"],
                            "attachments": [a["id"] for a in result.get("attachments", [])]}
        if entry.get("cid") in self.campaign_characters() and entry["cid"] != self.selected_cid:
            self.select_character(entry["cid"], reset_name=False)
        self.attachments.clear()
        self.keep_images.setChecked(True)
        self.message.setPlainText(entry["content"])
        self.message.moveCursor(QTextCursor.MoveOperation.End)
        self.message.setFocus()
        self.populate_edit_list()
        self.update_edit_state()

    def save_edit(self):
        t = self.edit_target
        if not t:
            return
        server, channel = self.current_server, self.channel_box.current()
        content = self.message.toPlainText()
        files = list(self.attachments)
        keep = t["attachments"] if self.keep_images.isChecked() else []
        problems = discord_client.validate_message(content, "-", files)
        if keep:
            problems = [pr for pr in problems if pr != "Message is empty."]
        if len(files) <= discord_client.MAX_FILES < len(files) + len(keep):
            problems.append(f"{len(files) + len(keep)} images with the ones it keeps (max {discord_client.MAX_FILES}).")
        if problems:
            return QMessageBox.warning(self, "Save edit", "\n".join(problems))
        self._set_sending(True)
        self.worker = DiscordWorker(discord_client.edit_message, self.channel_url(server, channel),
                                    t["id"], content, files, keep)
        self.worker.done.connect(lambda ok, result: self.on_edited(ok, result, t, server, channel, content))
        self.worker.start()

    def on_edited(self, ok, result, t, server, channel, content):
        self._set_sending(False)
        if not ok:
            return QMessageBox.critical(self, "Edit failed", result)
        log = self.channel_log(t["key"])
        for m in log:
            if m["id"] == t["id"]:
                m["content"] = (result or {}).get("content", content)
                m["images"] = len((result or {}).get("attachments", []))
                m["edited"] = datetime.now().isoformat(timespec="seconds")
        self._save_log(t["key"], log)
        if self.edit_target is t:
            self.cancel_edit()
        self.populate_edit_list()
        self.statusBar().showMessage(f"Edited {t['name']}'s message in {server} · # {channel}", 6000)

    def delete_posted(self, mid):
        if self.edit_worker and self.edit_worker.isRunning():
            return
        server, channel = self.current_server, self.channel_box.current()
        key = self.channel_key()
        entry = next((m for m in self.channel_log(key) if m["id"] == mid), {})
        answer = QMessageBox.question(
            self, "Delete message",
            f"Delete {entry.get('name') or 'this'}'s message from # {channel} in Discord?\nThis can't be undone.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.edit_worker = DiscordWorker(discord_client.delete_message, self.channel_url(server, channel), mid)
        self.edit_worker.done.connect(lambda ok, result: self.on_deleted(ok, result, key, mid, channel))
        self.edit_worker.start()

    def on_deleted(self, ok, result, key, mid, channel):
        if not ok and "can't find" not in result:
            return QMessageBox.critical(self, "Delete failed", result)
        self.forget_message(key, mid)
        self.statusBar().showMessage(f"Deleted the message from # {channel}", 6000)

    def forget_message(self, key, mid):
        entry = self.history.get(key)
        if not entry:
            return
        log = [m for m in entry.get("log", []) if m["id"] != mid]
        if entry.get("id") == mid:  # it was the faded "last sent" line: fall back to the one before it
            if log:
                self.history[key] = {**log[-1], "log": log}
            else:
                self.history.pop(key)
        else:
            entry["log"] = log
        save_json(HISTORY_FILE, self.history)
        if self.edit_target and self.edit_target["id"] == mid:
            self.cancel_edit()
        self.populate_edit_list()
        self.refresh_preview()

    # ---- persistence --------------------------------------------------

    def _restore_state(self):
        geometry = self.ui_state.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = self.ui_state.value("splitter")
        if splitter:
            self.splitter.restoreState(splitter)
        cid = self.selected_by_campaign.get(self.campaign) or self.ui_state.value("character")
        if cid in self.campaign_characters():
            self.select_character(cid)

    def closeEvent(self, e):
        self.ui_state.setValue("geometry", self.saveGeometry())
        self.ui_state.setValue("splitter", self.splitter.saveState())
        self.ui_state.setValue("server", self.current_server)
        self.ui_state.setValue("last_channels", json.dumps(self.last_channel))
        self.ui_state.setValue("character", self.selected_cid)
        if self.selected_cid:
            self.selected_by_campaign[self.campaign] = self.selected_cid
        self.ui_state.setValue("campaign", self.campaign)
        self.ui_state.setValue("character_by_campaign", json.dumps(self.selected_by_campaign))
        self.ui_state.setValue("sort", self.sort_combo.currentText())
        self.ui_state.setValue("zoom", self.zoom_toggle.isChecked())
        self.ui_state.setValue("view", self.view)
        super().closeEvent(e)


def run_sync(parent, force=False):
    dlg = QProgressDialog("Preparing avatars…", None, 0, 0, parent)
    dlg.setWindowTitle("Set in Stone Character Board")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(500)

    def progress(done, total, text):
        dlg.setMaximum(total)
        dlg.setValue(done)
        dlg.setLabelText(f"Preparing avatar: {text}" if text else "Done")
        QApplication.processEvents()

    try:
        return catalog.sync(force=force, progress=progress)
    finally:
        dlg.close()


def main():
    if sys.platform == "win32":
        # Without its own AppUserModelID, Windows groups the app under python.exe's taskbar icon.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SetInStone.CharacterBoard")
    app = QApplication(sys.argv)
    app.setApplicationName("Set in Stone Character Board")
    app.setWindowIcon(QIcon(str(ICON_FILE)))
    load_fonts()
    app.setStyleSheet(stylesheet())
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    app.setPalette(palette)
    characters = run_sync(None)
    window = MainWindow(characters)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
