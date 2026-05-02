"""GUI front-end for allmydox — select a folder and a database, then index."""
from __future__ import annotations

import json
import subprocess
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit,
    QComboBox, QProgressBar, QListWidget, QListWidgetItem, QSizePolicy,
    QFrame, QCheckBox,
)
from PyQt6.QtGui import QTextCursor, QColor

import db
import extractor
import processor


# ---------------------------------------------------------------------------
# Known spaCy models available for download
# ---------------------------------------------------------------------------

SPACY_VERSION = "3.8.0"

KNOWN_MODELS: dict[str, str] = {
    "de_core_news_sm": "German (small)",
    "de_core_news_md": "German (medium)",
    "de_core_news_lg": "German (large)",
    "en_core_web_sm":  "English (small)",
    "en_core_web_md":  "English (medium)",
    "en_core_web_lg":  "English (large)",
    "fr_core_news_sm": "French (small)",
    "fr_core_news_md": "French (medium)",
    "es_core_news_sm": "Spanish (small)",
    "it_core_news_sm": "Italian (small)",
    "nl_core_news_sm": "Dutch (small)",
    "pt_core_news_sm": "Portuguese (small)",
    "pl_core_news_sm": "Polish (small)",
}

DEFAULT_MODELS_DIR = Path.home() / ".allmydox_models"
SETTINGS_FILE      = Path.home() / ".allmydox_gui.json"


# ---------------------------------------------------------------------------
# Helpers — model discovery
# ---------------------------------------------------------------------------

def _folder_models(folder: Path) -> list[str]:
    """Return model names found as packages in a models folder."""
    if not folder.exists():
        return []
    result = []
    for d in sorted(folder.iterdir()):
        if d.is_dir() and (d / "meta.json").exists():
            result.append(d.name)   # directory name IS the package name (e.g. de_core_news_lg)
    return result


def _model_data_path(models_folder: Path, model_name: str) -> str | None:
    """Return the spaCy model data directory path for a folder-installed model.

    pip --target installs de_core_news_lg as:
      <folder>/de_core_news_lg/de_core_news_lg-3.8.0/   <- model data here
    spacy.load() accepts this path directly, which is more robust than
    sys.path manipulation.
    """
    pkg_dir = models_folder / model_name
    if not pkg_dir.is_dir():
        return None
    for sub in sorted(pkg_dir.iterdir()):
        if sub.is_dir() and (sub / "config.cfg").exists():
            return str(sub)
    return None


def _system_models() -> list[str]:
    """Return spaCy models already installed in the Python environment."""
    try:
        import spacy.util
        return sorted(spacy.util.get_installed_models())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _DownloadWorker(QThread):
    log  = pyqtSignal(str)
    done = pyqtSignal(bool, str)   # success, message

    def __init__(self, model: str, target_dir: Path):
        super().__init__()
        self._model  = model
        self._target = target_dir

    def run(self):
        try:
            self._target.mkdir(parents=True, exist_ok=True)
            url = (
                f"https://github.com/explosion/spacy-models/releases/download/"
                f"{self._model}-{SPACY_VERSION}/"
                f"{self._model}-{SPACY_VERSION}-py3-none-any.whl"
            )
            self.log.emit(f"Downloading {self._model} {SPACY_VERSION} …")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "--target", str(self._target), "--quiet", url],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self.done.emit(True, f"{self._model} installed successfully.")
            else:
                self.done.emit(False, (result.stderr or result.stdout).strip())
        except Exception:
            self.done.emit(False, traceback.format_exc())


class _IndexWorker(QThread):
    log      = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    done     = pyqtSignal(bool, str)

    def __init__(self, directory: str, db_path: str, model: str,
                 models_folder: str, exts: list[str], reindex_changed: bool):
        super().__init__()
        self._directory      = directory
        self._db_path        = db_path
        self._model          = model
        self._models_folder  = models_folder
        self._exts           = exts
        self._reindex_changed = reindex_changed

    def run(self):
        try:
            # Resolve model: use full data path for folder-installed models,
            # fall back to model name for system-installed ones.
            model_to_use = self._model
            if self._models_folder:
                data_path = _model_data_path(Path(self._models_folder), self._model)
                if data_path:
                    model_to_use = data_path

            directory = Path(self._directory).resolve()
            doc_files = []
            for ext in self._exts:
                e = ext if ext.startswith(".") else f".{ext}"
                doc_files.extend(sorted(directory.rglob(f"*{e}")))

            self.log.emit(f"Found {len(doc_files)} document(s) in '{directory}'.")
            self.progress.emit(0, len(doc_files))

            conn = db.connect(self._db_path)
            db.create_tables(conn)
            processor.prime_caches(conn)

            total      = len(doc_files)
            width      = len(str(total))
            new_count  = 0
            upd_count  = 0

            for idx, doc_path in enumerate(doc_files, start=1):
                rel       = doc_path.relative_to(directory)
                file_mtime = doc_path.stat().st_mtime
                info      = db.get_document_info(conn, str(doc_path.parent), doc_path.name)

                if info is not None:
                    file_id, stored_mtime = info
                    if stored_mtime is not None and stored_mtime == file_mtime:
                        self.log.emit(
                            f"  [{idx:{width}}/{total}] {rel}  —  skipped (unchanged)"
                        )
                        self.progress.emit(idx, total)
                        continue
                    if not self._reindex_changed or stored_mtime is None:
                        self.log.emit(
                            f"  [{idx:{width}}/{total}] {rel}  —  skipped (already indexed)"
                        )
                        self.progress.emit(idx, total)
                        continue
                    # File changed — remove old data first
                    self.log.emit(f"  [{idx:{width}}/{total}] {rel}  —  changed, re-indexing …")
                    db.delete_document(conn, file_id)
                    conn.commit()
                    is_update = True
                else:
                    self.log.emit(f"  [{idx:{width}}/{total}] {rel}  …")
                    is_update = False

                try:
                    file_id = db.insert_document(
                        conn,
                        filename=doc_path.name,
                        folderpath=str(doc_path.parent),
                        size=doc_path.stat().st_size,
                        extension=doc_path.suffix.lower(),
                        mtime=file_mtime,
                    )
                    pages = extractor.extract(doc_path)
                    processor.process_document(conn, file_id, pages, model=model_to_use)
                    conn.commit()
                    if is_update:
                        upd_count += 1
                        self.log.emit(f"    ok  {len(pages)} page(s)  [updated]")
                    else:
                        new_count += 1
                        self.log.emit(f"    ok  {len(pages)} page(s)")
                except Exception as exc:
                    conn.rollback()
                    self.log.emit(f"    ERROR: {exc}")

                self.progress.emit(idx, total)

            conn.close()
            parts = []
            if new_count:
                parts.append(f"{new_count} new")
            if upd_count:
                parts.append(f"{upd_count} updated")
            summary = ", ".join(parts) if parts else "no changes"
            self.done.emit(True, f"Finished. {summary} document(s) indexed.")
        except Exception:
            self.done.emit(False, traceback.format_exc())


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(data: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("allmydox — indexer")
        self.resize(820, 720)
        self._worker:    _IndexWorker    | None = None
        self._dl_worker: _DownloadWorker | None = None
        self._build_ui()
        self._apply_dark_theme()
        self._load_settings()
        self._refresh_models()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # --- Source folder ---
        root.addWidget(self._section_label("Source folder"))
        root.addLayout(self._path_row(
            attr="_folder_edit",
            placeholder="Select or type a directory path…",
            browse_cb=self._browse_folder,
        ))

        root.addWidget(self._separator())

        # --- Target database ---
        root.addWidget(self._section_label("Target database"))
        root.addLayout(self._path_row(
            attr="_db_edit",
            placeholder="Select existing .db or type path for a new one…",
            browse_cb=self._browse_db,
        ))

        root.addWidget(self._separator())

        # --- Language model ---
        root.addWidget(self._section_label("Language model"))

        # Models folder row
        mf_row = QHBoxLayout()
        mf_row.addWidget(QLabel("Models folder:"))
        self._models_folder_edit = QLineEdit()
        self._models_folder_edit.setPlaceholderText(str(DEFAULT_MODELS_DIR))
        self._models_folder_edit.textChanged.connect(self._on_models_folder_changed)
        mf_row.addWidget(self._models_folder_edit)
        btn_mf = QPushButton("Browse…")
        btn_mf.setFixedWidth(90)
        btn_mf.clicked.connect(self._browse_models_folder)
        mf_row.addWidget(btn_mf)
        root.addLayout(mf_row)

        # Model list
        list_hdr = QHBoxLayout()
        list_hdr.addWidget(QLabel("Available models  (click to select):"))
        list_hdr.addStretch()
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setFixedWidth(80)
        btn_refresh.clicked.connect(self._refresh_models)
        list_hdr.addWidget(btn_refresh)
        root.addLayout(list_hdr)

        self._model_list = QListWidget()
        self._model_list.setFixedHeight(130)
        self._model_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        root.addWidget(self._model_list)

        # Download row
        dl_row = QHBoxLayout()
        dl_row.addWidget(QLabel("Download model:"))
        self._dl_combo = QComboBox()
        self._dl_combo.setMinimumWidth(220)
        for name, label in KNOWN_MODELS.items():
            self._dl_combo.addItem(f"{name}  —  {label}", userData=name)
        dl_row.addWidget(self._dl_combo)
        self._dl_btn = QPushButton("Download")
        self._dl_btn.setFixedWidth(100)
        self._dl_btn.clicked.connect(self._download_model)
        dl_row.addWidget(self._dl_btn)
        self._dl_status = QLabel("")
        self._dl_status.setStyleSheet("color:#888; font-size:11px;")
        dl_row.addWidget(self._dl_status)
        dl_row.addStretch()
        root.addLayout(dl_row)

        root.addWidget(self._separator())

        # --- Options ---
        self._reindex_cb = QCheckBox("Re-index changed files  (detected by modification time)")
        self._reindex_cb.setChecked(True)
        root.addWidget(self._reindex_cb)

        # --- Start / Stop ---
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start indexing")
        self._start_btn.setFixedHeight(34)
        self._start_btn.clicked.connect(self._start)
        btn_row.addWidget(self._start_btn)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedHeight(34)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self._stop_btn)
        root.addLayout(btn_row)

        # --- Progress bar ---
        self._progress = QProgressBar()
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%v / %m")
        root.addWidget(self._progress)

        # --- Log ---
        root.addWidget(self._section_label("Log"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._log)

    def _path_row(self, attr: str, placeholder: str,
                  browse_cb) -> QHBoxLayout:
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        setattr(self, attr, edit)
        row.addWidget(edit)
        btn = QPushButton("Browse…")
        btn.setFixedWidth(90)
        btn.clicked.connect(browse_cb)
        row.addWidget(btn)
        return row

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:bold; font-size:12px;")
        return lbl

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#444;")
        return line

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#1e1e1e; color:#d4d4d4; }
            QLineEdit, QComboBox, QPlainTextEdit {
                background:#2d2d2d; border:1px solid #555;
                border-radius:4px; padding:4px 8px; color:#d4d4d4;
            }
            QComboBox::drop-down { border:none; }
            QListWidget {
                background:#2d2d2d; border:1px solid #555; color:#d4d4d4;
            }
            QListWidget::item:hover    { background:#3a3a3a; }
            QListWidget::item:selected { background:#264f78; color:#ffffff; }
            QPushButton {
                background:#2d2d2d; border:1px solid #555;
                border-radius:4px; padding:4px 12px; color:#d4d4d4;
            }
            QPushButton:hover    { background:#3a3a3a; }
            QPushButton:disabled { color:#666; }
            QProgressBar {
                background:#2d2d2d; border:1px solid #555;
                border-radius:4px; text-align:center; color:#d4d4d4;
            }
            QProgressBar::chunk { background:#264f78; border-radius:3px; }
            QFrame[frameShape="4"] { color:#444; }
        """)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings(self):
        s = _load_settings()
        if s.get("source_folder"):
            self._folder_edit.setText(s["source_folder"])
        if s.get("db_path"):
            self._db_edit.setText(s["db_path"])
        mf = s.get("models_folder") or str(DEFAULT_MODELS_DIR)
        self._models_folder_edit.setText(mf)
        self._last_model = s.get("model", "")

    def _save_current_settings(self):
        _save_settings({
            "source_folder":  self._folder_edit.text(),
            "db_path":        self._db_edit.text(),
            "models_folder":  self._models_folder_edit.text(),
            "model":          self._selected_model(),
        })

    # ------------------------------------------------------------------
    # Model list
    # ------------------------------------------------------------------

    def _models_folder_path(self) -> Path:
        t = self._models_folder_edit.text().strip()
        return Path(t) if t else DEFAULT_MODELS_DIR

    def _on_models_folder_changed(self):
        self._refresh_models()

    def _refresh_models(self):
        folder   = self._models_folder_path()
        in_folder = _folder_models(folder)
        in_system = _system_models()

        # Merge: prefer folder entry, then system
        seen:  set[str]   = set()
        items: list[tuple[str, str]] = []   # (model_name, source_label)
        for m in in_folder:
            if m not in seen:
                seen.add(m)
                items.append((m, "models folder"))
        for m in in_system:
            if m not in seen:
                seen.add(m)
                items.append((m, "system"))

        self._model_list.clear()
        prev = self._last_model if hasattr(self, "_last_model") else ""

        for name, source in items:
            label = KNOWN_MODELS.get(name, "")
            display = f"{name}  —  {label}" if label else name
            display += f"   [{source}]"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if source == "system":
                item.setForeground(QColor("#aaaaaa"))
            self._model_list.addItem(item)
            if name == prev:
                self._model_list.setCurrentItem(item)

        if self._model_list.currentItem() is None and self._model_list.count():
            self._model_list.setCurrentRow(0)

        if not items:
            placeholder = QListWidgetItem("No models found — download one below")
            placeholder.setForeground(QColor("#666666"))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._model_list.addItem(placeholder)

    def _selected_model(self) -> str:
        item = self._model_list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or ""

    # ------------------------------------------------------------------
    # Browse dialogs
    # ------------------------------------------------------------------

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select source folder",
            self._folder_edit.text() or str(Path.home()),
        )
        if path:
            self._folder_edit.setText(path)

    def _browse_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Select or create database",
            self._db_edit.text() or str(Path.home()),
            "SQLite databases (*.db);;All files (*)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path:
            self._db_edit.setText(path)

    def _browse_models_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select models folder",
            self._models_folder_edit.text() or str(Path.home()),
        )
        if path:
            self._models_folder_edit.setText(path)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _download_model(self):
        if self._dl_worker and self._dl_worker.isRunning():
            return
        model = self._dl_combo.currentData()
        if not model:
            return
        folder = self._models_folder_path()
        self._dl_btn.setEnabled(False)
        self._dl_status.setText("Downloading…")

        self._dl_worker = _DownloadWorker(model, folder)
        self._dl_worker.log.connect(self._log_line)
        self._dl_worker.done.connect(self._on_download_done)
        self._dl_worker.start()

    def _on_download_done(self, success: bool, message: str):
        self._dl_btn.setEnabled(True)
        self._dl_status.setText("Done." if success else "Failed.")
        self._log_line(message)
        if success:
            self._refresh_models()

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def _start(self):
        folder   = self._folder_edit.text().strip()
        db_path  = self._db_edit.text().strip()
        model    = self._selected_model()

        if not folder or not Path(folder).is_dir():
            self._log_line("ERROR: please select a valid source folder.")
            return
        if not db_path:
            self._log_line("ERROR: please specify a target database path.")
            return
        if not model:
            self._log_line("ERROR: please select a language model from the list.")
            return

        self._save_current_settings()
        self._log.clear()
        self._progress.setValue(0)
        self._progress.setMaximum(1)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        mf = self._models_folder_edit.text().strip()
        self._worker = _IndexWorker(
            folder, db_path, model, mf,
            ["pdf", "doc", "docx", "xls", "xlsx", "txt"],
            reindex_changed=self._reindex_cb.isChecked(),
        )
        self._worker.log.connect(self._log_line)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
            self._log_line("— stopped by user —")
        self._set_idle()

    def _on_progress(self, current: int, total: int):
        self._progress.setMaximum(total)
        self._progress.setValue(current)

    def _on_done(self, success: bool, message: str):
        self._log_line("")
        self._log_line(message)
        self._set_idle()

    def _set_idle(self):
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _log_line(self, text: str):
        self._log.appendPlainText(text)
        self._log.moveCursor(QTextCursor.MoveOperation.End)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
