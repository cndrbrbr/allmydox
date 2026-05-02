"""GUI front-end for allmydox — select a folder and a database, then index."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit,
    QComboBox, QProgressBar, QSizePolicy,
)
from PyQt6.QtGui import QTextCursor

import db
import extractor
import processor


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class _IndexWorker(QThread):
    log      = pyqtSignal(str)          # one line of text
    progress = pyqtSignal(int, int)     # current, total
    done     = pyqtSignal(bool, str)    # success, message

    def __init__(self, directory: str, db_path: str, model: str, exts: list[str]):
        super().__init__()
        self._directory = directory
        self._db_path   = db_path
        self._model     = model
        self._exts      = exts

    def run(self):
        try:
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

            total = len(doc_files)
            width = len(str(total))
            done_count = 0

            for idx, doc_path in enumerate(doc_files, start=1):
                rel = doc_path.relative_to(directory)

                if db.document_exists(conn, str(doc_path.parent), doc_path.name):
                    self.log.emit(f"  [{idx:{width}}/{total}] {rel}  —  skipped (already indexed)")
                    self.progress.emit(idx, total)
                    continue

                self.log.emit(f"  [{idx:{width}}/{total}] {rel}  …")
                try:
                    file_id = db.insert_document(
                        conn,
                        filename=doc_path.name,
                        folderpath=str(doc_path.parent),
                        size=doc_path.stat().st_size,
                        extension=doc_path.suffix.lower(),
                    )
                    pages = extractor.extract(doc_path)
                    processor.process_document(conn, file_id, pages, model=self._model)
                    conn.commit()
                    done_count += 1
                    self.log.emit(f"    ✓  {len(pages)} page(s)")
                except Exception as exc:
                    conn.rollback()
                    self.log.emit(f"    ERROR: {exc}")

                self.progress.emit(idx, total)

            conn.close()
            self.done.emit(True, f"Finished. {done_count} new document(s) indexed.")
        except Exception:
            self.done.emit(False, traceback.format_exc())


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("allmydox — indexer")
        self.resize(780, 580)
        self._worker: _IndexWorker | None = None
        self._build_ui()
        self._apply_dark_theme()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        # --- Source folder ---
        root.addWidget(self._section_label("Source folder"))
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Select or type a directory path…")
        folder_row.addWidget(self._folder_edit)
        btn_folder = QPushButton("Browse…")
        btn_folder.setFixedWidth(90)
        btn_folder.clicked.connect(self._browse_folder)
        folder_row.addWidget(btn_folder)
        root.addLayout(folder_row)

        # --- Target database ---
        root.addWidget(self._section_label("Target database"))
        db_row = QHBoxLayout()
        self._db_edit = QLineEdit()
        self._db_edit.setPlaceholderText("Select existing .db or type path for a new one…")
        db_row.addWidget(self._db_edit)
        btn_db = QPushButton("Browse…")
        btn_db.setFixedWidth(90)
        btn_db.clicked.connect(self._browse_db)
        db_row.addWidget(btn_db)
        root.addLayout(db_row)

        # --- spaCy model ---
        root.addWidget(self._section_label("spaCy language model"))
        model_row = QHBoxLayout()
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        for m in ("de_core_news_sm", "en_core_web_sm", "fr_core_news_sm",
                  "es_core_news_sm", "it_core_news_sm"):
            self._model_combo.addItem(m)
        model_row.addWidget(self._model_combo)
        model_row.addStretch()
        root.addLayout(model_row)

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
        self._log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._log)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:bold; font-size:12px;")
        return lbl

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#1e1e1e; color:#d4d4d4; }
            QLineEdit, QComboBox, QPlainTextEdit {
                background:#2d2d2d; border:1px solid #555;
                border-radius:4px; padding:4px 8px; color:#d4d4d4;
            }
            QComboBox::drop-down { border:none; }
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
        """)

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select source folder",
                                                self._folder_edit.text() or str(Path.home()))
        if path:
            self._folder_edit.setText(path)

    def _browse_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Select or create database", self._db_edit.text() or str(Path.home()),
            "SQLite databases (*.db);;All files (*)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path:
            self._db_edit.setText(path)

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def _start(self):
        folder = self._folder_edit.text().strip()
        db_path = self._db_edit.text().strip()
        model = self._model_combo.currentText().strip()

        if not folder or not Path(folder).is_dir():
            self._log_line("ERROR: please select a valid source folder.")
            return
        if not db_path:
            self._log_line("ERROR: please specify a target database path.")
            return
        if not model:
            self._log_line("ERROR: please specify a spaCy model.")
            return

        self._log.clear()
        self._progress.setValue(0)
        self._progress.setMaximum(1)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        self._worker = _IndexWorker(folder, db_path, model, ["pdf", "docx", "txt"])
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
