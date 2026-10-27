"""Set in Stone Character Board — post to Discord as a character via webhook."""

import json
import math
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QByteArray, QMimeData, QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, QThread, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QColor, QDrag, QFont, QFontDatabase, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPalette,
    QPen, QPixmap, QPolygonF, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QSplitter, QToolButton,
    QVBoxLayout, QWidget,
)

import catalog
import discord_client

ROOT = Path(__file__).resolve().parent
CHANNELS_FILE = ROOT / "channel_list.json"
SETTINGS_FILE = ROOT / "settings.json"
HISTORY_FILE = ROOT / "history.json"
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
    "Gods of Dagda": "#d9cfae",
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

FAVORITES = "__favorites__"
ALL = "__all__"
# Factions in this order first; any others (e.g. new folders) follow alphabetically.
FACTION_ORDER = [
    "Gods of Dagda", "Ribeira Winds", "House Lamine", "Megaira's Beacon", "Rose Tempest", "Linaria's Dewdrops",
    "Fiery Mane", "Tale of the Moon", "Bridal Party of the Pale Raven", "Kingdom of Arago", "Temple Army",
    "Unaffiliated",
]


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
    QPushButton#pillAdd {{ background: transparent; border: 1px dashed {LINE_HI}; border-radius: 14px;
                           padding: 5px 14px; color: {GOLD}; font-size: 15px; }}
    QPushButton#attach {{ background: transparent; border: 2px dashed {GOLD}; color: {GOLD};
                          padding: 0; }}
    QPushButton#attach:hover {{ border-color: {GOLD_HI}; color: {GOLD_HI}; }}
    QPushButton#send {{ background: {SEAL}; color: #f6ecd6; border: 1px solid {GOLD};
                        font-family: "{DISPLAY_FAMILY}"; font-size: 15px; font-weight: 700; padding: 0 18px; }}
    QPushButton#send:hover {{ background: {SEAL_HI}; }}
    QPushButton#send:disabled {{ background: {RAISED}; color: {MUTED}; border-color: {LINE}; }}
    QToolButton#remove {{ background: {INK}; border: 1px solid {GOLD}; border-radius: 9px; color: {GOLD_HI};
                          font-size: 12px; }}
    QToolButton#fileMenu {{ background: transparent; border: 0; color: {MUTED}; font-size: 15px; padding: 4px 8px; }}
    QToolButton#fileMenu:hover {{ color: {GOLD_HI}; }}
    QToolButton#fileMenu::menu-indicator {{ image: none; }}
    QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px; }}
    QMenu::item:selected {{ background: {RAISED}; color: {GOLD_HI}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}

    QSplitter::handle {{ background: {LINE}; }}
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
        self.setToolTip(f'{self.name} — {character["faction"]}\nClick the star to favorite (or press F)')
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
        self.setAccessibleName(f'{character["name"]}, {character["faction"]}' if character else "No character chosen")
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
                       self.character["faction"].upper())
            p.setFont(display_font(32, QFont.Weight.Bold, 104))
            name = p.fontMetrics().elidedText(self.character["name"], Qt.TextElideMode.ElideRight, int(w * 0.6))
            p.drawText(QRectF(22, 0, w - 44, h - 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, name)
        p.setPen(QPen(QColor(GOLD), 1))
        p.drawLine(QPointF(0, h - 0.5), QPointF(w, h - 0.5))


# ---- message preview ---------------------------------------------------

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


class ChannelPills(QWidget):
    selected = pyqtSignal(str)
    addRequested = pyqtSignal()
    removeRequested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.flow = FlowLayout(self, hspacing=6, vspacing=6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.buttonClicked.connect(lambda b: self.selected.emit(b.property("channel")))

    def set_channels(self, names, current):
        for b in self.group.buttons():
            self.group.removeButton(b)
        while self.flow.count():
            self.flow.takeAt(0).widget().deleteLater()
        for name in names:
            b = QPushButton(f"# {name}")
            b.setObjectName("pill")
            b.setCheckable(True)
            b.setChecked(name == current)
            b.setProperty("channel", name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip("Right-click to remove")
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _, n=name, btn=b: self._menu(n, btn))
            self.group.addButton(b)
            self.flow.addWidget(b)
        add = QPushButton("+ Channel")
        add.setObjectName("pillAdd")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self.addRequested)
        self.flow.addWidget(add)

    def current(self):
        b = self.group.checkedButton()
        return b.property("channel") if b else ""

    def _menu(self, name, button):
        menu = QMenu(self)
        menu.addAction(f'Remove "# {name}"…', lambda: self.removeRequested.emit(name))
        menu.exec(button.mapToGlobal(QPoint(0, button.height())))


# ---- dialogs -------------------------------------------------------------

class AddChannelDialog(QDialog):
    def __init__(self, parent, existing_names):
        super().__init__(parent)
        self.setWindowTitle("Add channel")
        self.existing = existing_names
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://discord.com/api/webhooks/…")
        self.url.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout(self)
        form.addRow("Channel name:", self.name)
        form.addRow("Webhook URL:", self.url)
        form.addRow(label("The webhook is checked with Discord before it's saved.", "muted"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.try_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(520, 0)

    def try_accept(self):
        name, url = self.name.text().strip(), self.url.text().strip()
        if not name:
            return QMessageBox.warning(self, "Add channel", "Give the channel a name.")
        if name in self.existing:
            return QMessageBox.warning(self, "Add channel", f'A channel called "{name}" already exists.')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = discord_client.fetch_webhook_info(url)
        except discord_client.WebhookError as e:
            return QMessageBox.warning(self, "Add channel", str(e))
        finally:
            QApplication.restoreOverrideCursor()
        self.webhook_name = info.get("name", "")
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


class SendWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, url, content, username, avatar_url, files):
        super().__init__()
        self.args = (url, content, username, avatar_url, files)

    def run(self):
        try:
            discord_client.send_message(*self.args)
            self.done.emit(True, "")
        except discord_client.WebhookError as e:
            self.done.emit(False, str(e))


# ---- main window ---------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, characters):
        super().__init__()
        self.setWindowTitle("Set in Stone Character Board")
        self.characters = characters
        self.channels = load_json(CHANNELS_FILE, {})
        self.settings = load_json(SETTINGS_FILE, {"avatar_base_url": ""})
        self.history = load_json(HISTORY_FILE, {})
        self.ui_state = QSettings("SetInStone", "CharacterBoard")
        self.worker = None
        self.warned_no_avatar = False
        self.selected_cid = None
        self.attachments = []
        self.tiles = {}
        self.sections = []
        self.pixmaps = {}
        self.mode = ALL
        self.setAcceptDrops(True)

        self._build_ui()
        self.populate_nav()
        self.populate_roster()
        self.populate_channels(self.ui_state.value("channel"))
        self._restore_state()
        self.refresh_preview()

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
        self.splitter.addWidget(self._build_nav())
        self.splitter.addWidget(self._build_center())
        self.splitter.addWidget(self._build_panel())
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 710, 510])
        rl.addWidget(self.splitter, 1)
        self.setCentralWidget(root)
        self.statusBar()
        self.resize(1500, 900)
        self.setMinimumSize(1400, 760)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.send)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.send)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search.setFocus())

    def _build_header(self):
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(46)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 10, 0)
        hl.setSpacing(10)
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
        menu_button = QToolButton()
        menu_button.setObjectName("fileMenu")
        menu_button.setText("File  ▾")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        menu.addAction("Rescan portraits", lambda: self.resync(force=False))
        menu.addAction("Rebuild all avatars", lambda: self.resync(force=True))
        menu.addSeparator()
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        menu_button.setMenu(menu)
        hl.addWidget(menu_button)
        return header

    def _build_nav(self):
        nav = QWidget()
        nav.setObjectName("nav")
        nav.setMinimumWidth(200)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(14, 22, 14, 14)
        layout.setSpacing(2)
        heading = label("FACTIONS", font=display_font(12, QFont.Weight.DemiBold, 124))
        heading.setStyleSheet(f"color: {MUTED}; padding: 0 10px 10px;")
        layout.addWidget(heading)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.buttonClicked.connect(lambda b: self.set_mode(b.property("mode")))
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(2)
        layout.addLayout(self.nav_layout)
        layout.addStretch()
        return nav

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
        top.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        top.addStretch()
        top.addWidget(self.search)
        top.addWidget(label("Sort by", "muted", body_font(15)))
        top.addWidget(self.sort_combo)
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
        pl.addWidget(card_scroll, 1)
        self.context_hint = label("The faded line is the last message sent from here to this channel.",
                                  "muted", body_font(14, italic=True))
        self.context_hint.setWordWrap(True)
        pl.addWidget(self.context_hint)
        layout.addWidget(preview, 1)

        # Composer (bottom)
        composer = QWidget()
        composer.setObjectName("composer")
        col = QVBoxLayout(composer)
        col.setContentsMargins(24, 16, 24, 18)
        col.setSpacing(12)

        as_row = QHBoxLayout()
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
        save = QPushButton("Save as default")
        save.setObjectName("ghost")
        save.setToolTip("Make this the character's default display name")
        save.clicked.connect(self.save_default_name)
        as_row.addWidget(self.name_edit, 1)
        as_row.addWidget(reset)
        as_row.addWidget(save)
        col.addLayout(as_row)

        to_row = QHBoxLayout()
        to_row.setSpacing(8)
        to_label = label("to", "muted", body_font(16, italic=True))
        to_row.addWidget(to_label, 0, Qt.AlignmentFlag.AlignTop)
        self.pills = ChannelPills()
        self.pills.selected.connect(lambda _: self.refresh_preview())
        self.pills.addRequested.connect(self.add_channel)
        self.pills.removeRequested.connect(self.remove_channel)
        to_row.addWidget(self.pills, 1)
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
        self.message = QPlainTextEdit()
        self.message.setObjectName("message")
        self.message.setFont(body_font(18))
        self.message.setPlaceholderText("Write your words…")
        self.message.setFixedHeight(110)
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
        write_row.addWidget(self.message, 1)
        write_row.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(write_row)

        col.addSpacing(10)
        foot = QHBoxLayout()
        foot.addWidget(label("Ctrl+Enter to send · drop images anywhere", "muted", body_font(14, italic=True)))
        foot.addStretch()
        self.counter = label("", "muted", body_font(14))
        foot.addWidget(self.counter)
        col.addLayout(foot)
        layout.addWidget(composer)
        return panel

    # ---- roster -------------------------------------------------------

    def populate_nav(self):
        for b in self.nav_group.buttons():
            self.nav_group.removeButton(b)
            b.deleteLater()
        entries = [(FAVORITES, f"Favorites  ({self.favorite_count()})", star_icon()),
                   (ALL, "All factions", dot_icon(GOLD))]
        for faction in sorted({c["faction"] for c in self.characters.values()}, key=faction_key):
            entries.append((faction, faction, dot_icon(FACTION_COLORS.get(faction, GOLD))))
        if self.mode not in [e[0] for e in entries]:
            self.mode = ALL
        for mode, text, icon in entries:
            b = QPushButton(icon, "  " + text)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setChecked(mode == self.mode)
            b.setProperty("mode", mode)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(b)
            self.nav_layout.addWidget(b)
        # Widen the rail so the longest faction name is never cut off.
        rail = self.nav_layout.parentWidget()
        rail.setMinimumWidth(max(200, max(b.sizeHint().width() for b in self.nav_group.buttons()) + 28))

    def favorite_count(self):
        return sum(1 for c in self.characters.values() if c.get("favorite"))

    def update_favorites_label(self):
        for b in self.nav_group.buttons():
            if b.property("mode") == FAVORITES:
                b.setText(f"  Favorites  ({self.favorite_count()})")

    def pixmap(self, cid):
        if cid not in self.pixmaps:
            self.pixmaps[cid] = QPixmap(str(catalog.AVATARS_DIR / self.characters[cid]["avatar"]))
        return self.pixmaps[cid]

    def populate_roster(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 18, 12, 24)
        layout.setSpacing(28)
        self.tiles, self.sections = {}, []
        by_faction = self.sort_combo.currentText() == "Faction"
        ordered = sorted(self.characters.items(), key=lambda kv: SORT_KEYS[self.sort_combo.currentText()](kv[1]))
        section = None
        for cid, c in ordered:
            title = c["faction"] if by_faction else None
            if section is None or (by_faction and section.property("faction") != title):
                section = RosterSection(title)
                section.setProperty("faction", title)
                section.reordered.connect(self.save_order)
                self.sections.append(section)
                layout.addWidget(section)
            tile = PortraitTile(cid, c, self.pixmap(cid))
            tile.set_selected(cid == self.selected_cid)
            tile.clicked.connect(self.select_character)
            tile.favoriteToggled.connect(self.toggle_favorite)
            tile.draggable = by_faction
            if by_faction:
                tile.setToolTip(tile.toolTip() + "\nDrag (or Ctrl+Left/Right) to reorder within the faction")
                tile.moveRequested.connect(self.step_character)
            section.add(tile)
            self.tiles[cid] = tile
        layout.addStretch()
        self.scroll.setWidget(content)
        self.apply_filter()

    def save_order(self, cids):
        for i, cid in enumerate(cids):
            self.characters[cid]["order"] = i
        catalog.save_characters(self.characters)
        self.statusBar().showMessage(f'Saved the order of {self.characters[cids[0]]["faction"]}', 3000)

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
            shown += bool(visible)
        single_faction = self.mode not in (ALL, FAVORITES)
        for section in self.sections:
            section.setVisible(any(t.isVisibleTo(section) for t in section.tiles))
            section.header.setVisible(bool(section.property("faction")) and not single_faction)

        self.title.setText({ALL: "The Roster", FAVORITES: "Favorites"}.get(self.mode, self.mode))
        self.count.setText(f"{shown} soul" if shown == 1 else f"{shown} souls")
        if shown:
            self.empty.hide()
            self.scroll.show()
        else:
            self.scroll.hide()
            self.empty.show()
            if self.mode == FAVORITES and not needle:
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
        if reset_name:
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
        self.update_favorites_label()
        if self.mode == FAVORITES:
            self.apply_filter()

    def reset_name(self):
        if self.selected_cid:
            self.name_edit.setText(self.characters[self.selected_cid]["name"])

    def save_default_name(self):
        cid, name = self.selected_cid, self.name_edit.text().strip()
        if not cid or not name:
            return
        self.characters[cid]["name"] = name
        catalog.save_characters(self.characters)
        self.tiles[cid].set_name(name)
        self.profile.update()
        self.statusBar().showMessage(f"Default name saved: {name}", 4000)

    def resync(self, force):
        self.characters = run_sync(self, force)
        self.pixmaps.clear()
        self.populate_nav()
        self.populate_roster()
        if self.selected_cid not in self.characters:
            self.selected_cid = None
        self.refresh_preview()
        self.statusBar().showMessage(
            f"{len(self.characters)} characters loaded. Push avatars/ to GitHub so new avatars show in Discord.", 8000)

    # ---- channels -----------------------------------------------------

    def populate_channels(self, select=None):
        select = select if select in self.channels else next(iter(self.channels), "")
        self.pills.set_channels(list(self.channels), select)
        self.refresh_preview()

    def add_channel(self):
        dlg = AddChannelDialog(self, self.channels.keys())
        if dlg.exec():
            name = dlg.name.text().strip()
            self.channels[name] = dlg.url.text().strip()
            save_json(CHANNELS_FILE, self.channels)
            self.populate_channels(select=name)
            self.statusBar().showMessage(f'Added channel "{name}" (webhook: {dlg.webhook_name})', 5000)

    def remove_channel(self, name):
        if QMessageBox.question(self, "Remove channel", f'Remove "# {name}" from the channel list?') \
                == QMessageBox.StandardButton.Yes:
            del self.channels[name]
            save_json(CHANNELS_FILE, self.channels)
            self.populate_channels(self.pills.current())

    # ---- settings -----------------------------------------------------

    def open_settings(self):
        sample = next(iter(self.characters.values()), {}).get("avatar")
        dlg = SettingsDialog(self, self.settings, sample)
        if dlg.exec():
            self.settings["avatar_base_url"] = dlg.value()
            save_json(SETTINGS_FILE, self.settings)

    # ---- compose & preview --------------------------------------------

    def refresh_preview(self):
        channel = self.pills.current()
        self.preview_channel.setText(f"# {channel}" if channel else "— add a channel —")

        last = self.history.get(channel)
        if last and last.get("cid") in self.characters:
            sent = datetime.fromisoformat(last["time"])
            when = sent.strftime("%I:%M %p").lstrip("0")
            if sent.date() != datetime.now().date():
                when = sent.strftime("%b %d, ") + when
            images = last.get("images", 0)
            text = last["content"] + (f"\n[{images} image{'s' if images != 1 else ''}]" if images else "")
            self.context_row.set_message(self.pixmap(last["cid"]), last["name"], f"Last sent here · {when}", text)
            self.context_row.show()
        else:
            self.context_row.hide()
        self.context_hint.setVisible(self.context_row.isVisibleTo(self.context_row.parentWidget()))

        cid = self.selected_cid
        self.profile.set_character(self.characters.get(cid), self.pixmap(cid) if cid else QPixmap())
        self.message_row.setVisible(bool(cid))
        self.placeholder.setVisible(not cid)
        if cid:
            self.message_row.set_message(self.pixmap(cid), self.name_edit.text().strip(),
                                         f'{self.characters[cid]["faction"]} · unsent',
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

    def avatar_url(self, cid):
        base = self.settings.get("avatar_base_url", "").strip()
        return f'{base.rstrip("/")}/{self.characters[cid]["avatar"]}' if base else None

    def send(self):
        if self.worker and self.worker.isRunning():
            return
        cid, channel = self.selected_cid, self.pills.current()
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

        avatar = self.avatar_url(cid)
        if not avatar and not self.warned_no_avatar:
            answer = QMessageBox.question(
                self, "No avatar URL",
                "No avatar base URL is set (File → Settings), so the message will use the webhook's "
                "default picture.\n\nSend anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.warned_no_avatar = True

        self.send_btn.setEnabled(False)
        self.send_btn.setText("SENDING…")
        self.worker = SendWorker(self.channels[channel], content, username, avatar, files)
        self.worker.done.connect(lambda ok, err: self.on_sent(ok, err, cid, username, channel, content, files))
        self.worker.start()

    def on_sent(self, ok, err, cid, username, channel, content, files):
        self.send_btn.setEnabled(True)
        self.send_btn.setText("SEAL && SEND")
        if not ok:
            return QMessageBox.critical(self, "Send failed", err)
        self.history[channel] = {"cid": cid, "name": username, "content": content,
                                 "images": len(files), "time": datetime.now().isoformat(timespec="seconds")}
        save_json(HISTORY_FILE, self.history)
        self.attachments.clear()
        self.message.clear()  # also refreshes the preview
        self.statusBar().showMessage(f"Sent as {username} to # {channel}", 6000)

    # ---- persistence --------------------------------------------------

    def _restore_state(self):
        geometry = self.ui_state.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = self.ui_state.value("splitter")
        if splitter:
            self.splitter.restoreState(splitter)
        self.select_character(self.ui_state.value("character"))

    def closeEvent(self, e):
        self.ui_state.setValue("geometry", self.saveGeometry())
        self.ui_state.setValue("splitter", self.splitter.saveState())
        self.ui_state.setValue("channel", self.pills.current())
        self.ui_state.setValue("character", self.selected_cid)
        self.ui_state.setValue("sort", self.sort_combo.currentText())
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
