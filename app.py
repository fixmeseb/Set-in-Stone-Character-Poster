"""Set in Stone Character Board — post to Discord as a character via webhook."""

import json
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

import catalog
import discord_client

ROOT = Path(__file__).resolve().parent
CHANNELS_FILE = ROOT / "channel_list.json"
SETTINGS_FILE = ROOT / "settings.json"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.webp)"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALL_FACTIONS = "All factions"


def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


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


class AttachmentList(QListWidget):
    """List of image paths that also accepts files dragged in from Explorer."""

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMaximumHeight(90)

    def paths(self) -> list:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def add_paths(self, paths) -> None:
        existing = set(self.paths())
        for p in paths:
            if p not in existing and Path(p).suffix.lower() in IMAGE_SUFFIXES:
                item = QListWidgetItem(QIcon(p), Path(p).name)
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setToolTip(p)
                self.addItem(item)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths(u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile())
        e.acceptProposedAction()


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
        form.addRow(QLabel("The webhook is checked with Discord before it's saved."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.try_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(480, 0)

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
        form.addRow(QLabel("Public URL of the avatars/ folder. Each character's avatar URL is\n"
                           "this plus its path, e.g. …/avatars/fiery-mane/dante.png"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(620, 0)

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


class MainWindow(QMainWindow):
    def __init__(self, characters):
        super().__init__()
        self.setWindowTitle("Set in Stone Character Board")
        self.characters = characters
        self.channels = load_json(CHANNELS_FILE, {})
        self.settings = load_json(SETTINGS_FILE, {"avatar_base_url": ""})
        self.ui_state = QSettings("SetInStone", "CharacterBoard")
        self.worker = None
        self.warned_no_avatar = False

        self._build_menu()
        self._build_ui()
        self.populate_factions()
        self.populate_grid()
        self.populate_channels()
        self._restore_state()

    # ---- construction -------------------------------------------------

    def _build_menu(self):
        menu = self.menuBar().addMenu("&File")
        for text, slot in [
            ("Rescan portraits", lambda: self.resync(force=False)),
            ("Rebuild all avatars", lambda: self.resync(force=True)),
            ("Settings…", self.open_settings),
        ]:
            action = QAction(text, self)
            action.triggered.connect(slot)
            menu.addAction(action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    def _build_ui(self):
        # Left: factions
        self.faction_list = QListWidget()
        self.faction_list.currentTextChanged.connect(lambda _: self.apply_filter())

        # Center: search + portrait grid
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search characters…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.apply_filter())
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(QSize(112, 112))
        self.grid.setGridSize(QSize(132, 150))
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setWordWrap(True)
        self.grid.currentItemChanged.connect(self.on_character_selected)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.search)
        cl.addWidget(self.grid)

        # Right: compose panel
        self.preview = QLabel("Select a character")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(220, 220)

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(discord_client.MAX_USERNAME)
        self.save_name_btn = QPushButton("Save as default")
        self.save_name_btn.setToolTip("Make this the character's default display name")
        self.save_name_btn.clicked.connect(self.save_default_name)
        self.reset_name_btn = QPushButton("Reset")
        self.reset_name_btn.setToolTip("Go back to the character's default name")
        self.reset_name_btn.clicked.connect(self.reset_name)
        name_row = QHBoxLayout()
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(self.reset_name_btn)
        name_row.addWidget(self.save_name_btn)

        self.channel_combo = QComboBox()
        add_ch = QPushButton("Add…")
        add_ch.clicked.connect(self.add_channel)
        rm_ch = QPushButton("Remove")
        rm_ch.clicked.connect(self.remove_channel)
        channel_row = QHBoxLayout()
        channel_row.addWidget(self.channel_combo, 1)
        channel_row.addWidget(add_ch)
        channel_row.addWidget(rm_ch)

        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("Write the message… (Ctrl+Enter to send)")
        self.message.textChanged.connect(self.update_counter)
        self.counter = QLabel()
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.attachments = AttachmentList()
        add_img = QPushButton("Add images…")
        add_img.clicked.connect(self.add_images)
        rm_img = QPushButton("Remove")
        rm_img.clicked.connect(lambda: [self.attachments.takeItem(self.attachments.row(i))
                                        for i in self.attachments.selectedItems()])
        clear_img = QPushButton("Clear")
        clear_img.clicked.connect(self.attachments.clear)
        img_buttons = QHBoxLayout()
        img_buttons.addWidget(add_img)
        img_buttons.addWidget(rm_img)
        img_buttons.addWidget(clear_img)
        img_buttons.addStretch()
        img_box = QGroupBox("Images (drag && drop supported)")
        il = QVBoxLayout(img_box)
        il.addWidget(self.attachments)
        il.addLayout(img_buttons)

        self.send_btn = QPushButton("Send")
        self.send_btn.setMinimumHeight(36)
        self.send_btn.clicked.connect(self.send)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.send)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.send)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        self.faction_label = QLabel()
        self.faction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.faction_label.setStyleSheet("color: gray;")
        rl.addWidget(self.faction_label)
        form = QFormLayout()
        form.addRow("Display name:", name_row)
        form.addRow("Channel:", channel_row)
        rl.addLayout(form)
        rl.addWidget(self.message, 1)
        rl.addWidget(self.counter)
        rl.addWidget(img_box)
        rl.addWidget(self.send_btn)

        self.splitter = QSplitter()
        self.splitter.addWidget(self.faction_list)
        self.splitter.addWidget(center)
        self.splitter.addWidget(right)
        self.splitter.setSizes([180, 620, 420])
        self.setCentralWidget(self.splitter)
        self.resize(1280, 800)
        self.update_counter()

    # ---- population ---------------------------------------------------

    def populate_factions(self):
        current = self.faction_list.currentItem().text() if self.faction_list.currentItem() else ALL_FACTIONS
        self.faction_list.blockSignals(True)
        self.faction_list.clear()
        self.faction_list.addItem(ALL_FACTIONS)
        self.faction_list.addItems(sorted({c["faction"] for c in self.characters.values()}))
        matches = self.faction_list.findItems(current, Qt.MatchFlag.MatchExactly)
        self.faction_list.setCurrentItem(matches[0] if matches else self.faction_list.item(0))
        self.faction_list.blockSignals(False)

    def populate_grid(self):
        self.grid.clear()
        for cid, c in self.characters.items():
            item = QListWidgetItem(QIcon(str(catalog.AVATARS_DIR / c["avatar"])), c["name"])
            item.setData(Qt.ItemDataRole.UserRole, cid)
            item.setToolTip(f'{c["name"]} — {c["faction"]}')
            self.grid.addItem(item)
        self.apply_filter()

    def apply_filter(self):
        faction = self.faction_list.currentItem().text() if self.faction_list.currentItem() else ALL_FACTIONS
        needle = self.search.text().strip().lower()
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            c = self.characters[item.data(Qt.ItemDataRole.UserRole)]
            visible = (faction == ALL_FACTIONS or c["faction"] == faction) and needle in c["name"].lower()
            item.setHidden(not visible)

    def populate_channels(self, select=None):
        select = select or self.channel_combo.currentText()
        self.channel_combo.clear()
        self.channel_combo.addItems(self.channels.keys())
        if select in self.channels:
            self.channel_combo.setCurrentText(select)

    # ---- character ----------------------------------------------------

    def current_character(self):
        item = self.grid.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def on_character_selected(self, item, _prev=None):
        if not item:
            return
        c = self.characters[item.data(Qt.ItemDataRole.UserRole)]
        pix = QPixmap(str(catalog.AVATARS_DIR / c["avatar"]))
        self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        self.faction_label.setText(c["faction"])
        self.name_edit.setText(c["name"])

    def reset_name(self):
        cid = self.current_character()
        if cid:
            self.name_edit.setText(self.characters[cid]["name"])

    def save_default_name(self):
        cid = self.current_character()
        name = self.name_edit.text().strip()
        if not cid or not name:
            return
        self.characters[cid]["name"] = name
        catalog.save_characters(self.characters)
        item = self.grid.currentItem()
        item.setText(name)
        item.setToolTip(f'{name} — {self.characters[cid]["faction"]}')
        self.statusBar().showMessage(f"Default name saved: {name}", 4000)

    def resync(self, force):
        cid = self.current_character()
        self.characters = run_sync(self, force)
        self.populate_factions()
        self.populate_grid()
        self._select_character(cid)
        self.statusBar().showMessage(
            f"{len(self.characters)} characters loaded. Push avatars/ to GitHub so new avatars show in Discord.", 8000)

    def _select_character(self, cid):
        for i in range(self.grid.count()):
            if self.grid.item(i).data(Qt.ItemDataRole.UserRole) == cid:
                self.grid.setCurrentRow(i)
                return

    # ---- channels -----------------------------------------------------

    def add_channel(self):
        dlg = AddChannelDialog(self, self.channels.keys())
        if dlg.exec():
            name = dlg.name.text().strip()
            self.channels[name] = dlg.url.text().strip()
            save_json(CHANNELS_FILE, self.channels)
            self.populate_channels(select=name)
            self.statusBar().showMessage(f'Added channel "{name}" (webhook: {dlg.webhook_name})', 5000)

    def remove_channel(self):
        name = self.channel_combo.currentText()
        if not name:
            return
        if QMessageBox.question(self, "Remove channel", f'Remove "{name}" from the channel list?') \
                == QMessageBox.StandardButton.Yes:
            del self.channels[name]
            save_json(CHANNELS_FILE, self.channels)
            self.populate_channels()

    # ---- settings -----------------------------------------------------

    def open_settings(self):
        sample = next(iter(self.characters.values()), {}).get("avatar")
        dlg = SettingsDialog(self, self.settings, sample)
        if dlg.exec():
            self.settings["avatar_base_url"] = dlg.value()
            save_json(SETTINGS_FILE, self.settings)

    # ---- compose & send -----------------------------------------------

    def update_counter(self):
        n = len(self.message.toPlainText())
        self.counter.setText(f"{n} / {discord_client.MAX_CONTENT}")
        self.counter.setStyleSheet("color: red;" if n > discord_client.MAX_CONTENT else "")

    def add_images(self):
        start = self.ui_state.value("last_image_dir", str(Path.home()))
        files, _ = QFileDialog.getOpenFileNames(self, "Add images", start, IMAGE_FILTER)
        if files:
            self.ui_state.setValue("last_image_dir", str(Path(files[0]).parent))
            self.attachments.add_paths(files)

    def avatar_url(self, cid):
        base = self.settings.get("avatar_base_url", "").strip()
        return f'{base.rstrip("/")}/{self.characters[cid]["avatar"]}' if base else None

    def send(self):
        if self.worker and self.worker.isRunning():
            return
        cid = self.current_character()
        channel = self.channel_combo.currentText()
        if not cid:
            return QMessageBox.warning(self, "Send", "Pick a character first.")
        if not channel:
            return QMessageBox.warning(self, "Send", "Add a channel first.")
        content = self.message.toPlainText()
        username = self.name_edit.text().strip()
        files = self.attachments.paths()
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
            self.warned_no_avatar = True  # only ask once per session

        self.send_btn.setEnabled(False)
        self.send_btn.setText("Sending…")
        self.worker = SendWorker(self.channels[channel], content, username, avatar, files)
        self.worker.done.connect(lambda ok, err: self.on_sent(ok, err, username, channel))
        self.worker.start()

    def on_sent(self, ok, err, username, channel):
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Send")
        if ok:
            self.message.clear()
            self.attachments.clear()
            self.statusBar().showMessage(f"Sent as {username} to #{channel}", 6000)
        else:
            QMessageBox.critical(self, "Send failed", err)

    # ---- persistence --------------------------------------------------

    def _restore_state(self):
        geometry = self.ui_state.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = self.ui_state.value("splitter")
        if splitter:
            self.splitter.restoreState(splitter)
        last_channel = self.ui_state.value("channel")
        if last_channel in self.channels:
            self.channel_combo.setCurrentText(last_channel)
        self._select_character(self.ui_state.value("character"))

    def closeEvent(self, e):
        self.ui_state.setValue("geometry", self.saveGeometry())
        self.ui_state.setValue("splitter", self.splitter.saveState())
        self.ui_state.setValue("channel", self.channel_combo.currentText())
        self.ui_state.setValue("character", self.current_character())
        super().closeEvent(e)


def run_sync(parent, force=False):
    dlg = QProgressDialog("Preparing avatars…", None, 0, 0, parent)
    dlg.setWindowTitle("Set in Stone Character Board")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(500)

    def progress(done, total, label):
        dlg.setMaximum(total)
        dlg.setValue(done)
        dlg.setLabelText(f"Preparing avatar: {label}" if label else "Done")
        QApplication.processEvents()

    try:
        return catalog.sync(force=force, progress=progress)
    finally:
        dlg.close()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Set in Stone Character Board")
    characters = run_sync(None)
    window = MainWindow(characters)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
