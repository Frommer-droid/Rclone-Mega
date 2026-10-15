"""Browse and export reports without mixing output from different tasks."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from app.core.run_history import RunHistory


class RunHistoryDialog(QDialog):
    def __init__(self, history: RunHistory, task_id: str, task_name: str, parent=None):
        super().__init__(parent)
        self.history = history
        self.task_id = task_id
        self.setWindowTitle(f"Запуски — {task_name}")
        self.resize(980, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        title = QLabel(task_name)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(12)
        self.runs = QListWidget()
        self.runs.setMinimumWidth(260)
        self.runs.setAccessibleName("Запуски по времени")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setObjectName("codeEditor")
        self.output.setAccessibleName("Отчёт выбранного запуска")
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        splitter.addWidget(self.runs)
        splitter.addWidget(self.output)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_button)
        actions.addStretch()
        self.md_button = QPushButton("Сохранить .md")
        self.log_button = QPushButton("Сохранить .log")
        self.md_button.clicked.connect(lambda: self.export(True))
        self.log_button.clicked.connect(lambda: self.export(False))
        actions.addWidget(self.md_button)
        actions.addWidget(self.log_button)
        layout.addLayout(actions)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        actions.addWidget(close)
        self.runs.currentItemChanged.connect(self._select)
        self.refresh()

    def refresh(self):
        selected = self.runs.currentItem()
        run_id = selected.data(Qt.ItemDataRole.UserRole)["run_id"] if selected else None
        self.runs.clear()
        for record in self.history.records(self.task_id):
            mode = "Проверка" if record["mode"] == "dry-run" else "Синхронизация"
            item = QListWidgetItem(
                f"{self.history.display_time(record['started_at'])}\n{mode} · {record['status']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.runs.addItem(item)
            if record["run_id"] == run_id:
                self.runs.setCurrentItem(item)
        if self.runs.currentRow() < 0 and self.runs.count():
            self.runs.setCurrentRow(0)
        if not self.runs.count():
            self.output.setPlainText(
                "История появится после первого запуска задачи."
            )
        self._update_buttons()

    def _update_buttons(self):
        item = self.runs.currentItem()
        finished = bool(
            item and item.data(Qt.ItemDataRole.UserRole)["status"] != "Выполняется"
        )
        self.md_button.setEnabled(finished)
        self.log_button.setEnabled(finished)

    def _select(self, current, previous):
        if current:
            try:
                text = self.history.preview(current.data(Qt.ItemDataRole.UserRole))
            except (OSError, ValueError) as exc:
                text = f"Не удалось прочитать отчёт: {exc}"
            self.output.setPlainText(text)
        self._update_buttons()

    def export(self, markdown: bool):
        item = self.runs.currentItem()
        if not item:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        extension = "md" if markdown else "log"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить отчёт о запуске",
            self.history.filename(record, extension),
            f"Отчёт (*.{extension})",
        )
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix("." + extension)
        try:
            self.history.export(record, destination, markdown)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Не удалось сохранить отчёт", str(exc))
            return
        QMessageBox.information(self, "Отчёт сохранён", str(destination))
