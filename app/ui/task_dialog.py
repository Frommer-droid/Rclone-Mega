# -*- coding: utf-8 -*-
"""Диалог создания и редактирования задачи."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
)

from app.models.sync_task import SyncTask
from app.services.rclone_config import (
    build_remote_path,
    is_valid_remote_name,
    is_valid_remote_path,
    remote_name_from_path,
)


INTERVAL_MAX_DAYS = 30


class TaskDialog(QDialog):
    def __init__(
        self,
        task: SyncTask | None = None,
        parent: QDialog | None = None,
        remote_names: list[str] | None = None,
        default_remote_name: str = "",
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._updating_remote_combo = False
        self.remote_names = self._normalize_remote_names(
            remote_names or ([default_remote_name] if default_remote_name else [])
        )
        self.default_remote_name = (
            default_remote_name
            if is_valid_remote_name(default_remote_name)
            else self.remote_names[0] if self.remote_names else ""
        )
        self.setWindowTitle("Задача синхронизации")
        self.setModal(True)
        self._restore_geometry_or_default()
        self._create_ui()
        if task:
            self._load_task(task)
        else:
            if self.default_remote_name:
                self._set_remote_combo_value(self.default_remote_name)
                self.remote_edit.setText(build_remote_path(self.default_remote_name))

    def _settings_store(self):  # type: ignore[no-untyped-def]
        parent = self.parentWidget()
        while parent is not None:
            store = getattr(parent, "settings_store", None)
            if store is not None:
                return store
            parent = parent.parentWidget()
        return None

    def _restore_geometry_or_default(self) -> None:
        store = self._settings_store()
        if store is not None:
            try:
                saved = store.get_task_dialog_settings()
                x = saved.get("x")
                y = saved.get("y")
                width = int(saved.get("width", 780))
                height = int(saved.get("height", 640))
            except (TypeError, ValueError):
                saved = None  # type: ignore[assignment]
            else:
                if isinstance(x, int) and isinstance(y, int):
                    from PySide6.QtWidgets import QApplication

                    width = max(400, min(width, 1600))
                    height = max(300, min(height, 1200))
                    screen = self.screen() or QApplication.primaryScreen()
                    if screen is not None:
                        available = screen.availableGeometry()
                        x = max(
                            available.x(),
                            min(
                                x,
                                available.x()
                                + available.width()
                                - min(width, 200),
                            ),
                        )
                        y = max(
                            available.y(),
                            min(
                                y,
                                available.y()
                                + available.height()
                                - min(height, 200),
                            ),
                        )
                    self.resize(width, height)
                    self.move(x, y)
                    return
        self.resize(780, 640)

    def _save_geometry(self) -> None:
        store = self._settings_store()
        if store is None:
            return
        try:
            geo = self.geometry()
            store.set_dialog_geometry(
                "task_dialog",
                x=self.pos().x(),
                y=self.pos().y(),
                width=geo.width(),
                height=geo.height(),
            )
            store.save()
        except Exception:
            pass

    def _create_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_edit = QLineEdit()
        self.source_edit = QLineEdit()
        self.remote_combo = QComboBox()
        self.remote_combo.setEditable(False)
        self.remote_edit = QLineEdit()
        self.remote_edit.setPlaceholderText("remote:папка/подпапка")
        self._updating_remote_combo = True
        for name in self.remote_names:
            self.remote_combo.addItem(name)
        self._updating_remote_combo = False
        self.remote_combo.currentTextChanged.connect(
            self._apply_remote_combo_to_remote_path
        )
        self.enabled_checkbox = QCheckBox("Задача включена")
        self.enabled_checkbox.setChecked(True)
        self.dry_run_checkbox = QCheckBox("Сначала выполнять dry-run")
        self.dry_run_checkbox.setChecked(True)
        self.max_delete_spin = QSpinBox()
        self.max_delete_spin.setRange(-1, 100_000)
        self.max_delete_spin.setValue(20)
        self.max_delete_spin.setToolTip(
            "-1 — без лимита удалений; 0 — запретить удаления."
        )
        self.use_backup_checkbox = QCheckBox("Использовать backup-dir")
        self.hard_delete_checkbox = QCheckBox("Удалять безвозвратно (минуя корзину MEGA)")
        self.hard_delete_checkbox.setToolTip(
            "При зеркалировании удалённые файлы нельзя будет восстановить из корзины MEGA. "
            "Сканирование ничего не удаляет. При включённом backup-dir файлы "
            "перемещаются в резервную папку."
        )
        self.backup_edit = QLineEdit()
        self.interval_days_combo = self._create_interval_combo(
            INTERVAL_MAX_DAYS, "д."
        )
        self.interval_hours_combo = self._create_interval_combo(23, "ч.")
        self.interval_minutes_combo = self._create_interval_combo(59, "мин.")
        self.scheduled_time_checkbox = QCheckBox("Привязать к времени")
        self.scheduled_time_edit = QTimeEdit()
        self.scheduled_time_edit.setDisplayFormat("HH:mm")
        self.scheduled_time_edit.setTime(QTime(0, 0))
        self.interval_paused = False
        self.interval_state_label = QLabel("Интервал активен")
        self.interval_state_label.setObjectName("mutedLabel")
        self.excludes_edit = QPlainTextEdit()
        self.excludes_edit.setPlaceholderText("Один шаблон exclude на строку")
        self.excludes_edit.setToolTip(
            "Дополнительные исключения задачи. Автоматически исключаются __pycache__, "
            "*.pyc, *.pyo, .pytest_cache, .ruff_cache, .mypy_cache, Thumbs.db, "
            ".DS_Store, *.tmp, *.temp, *.swp и ~$*. Правила действуют во всех подпапках."
        )
        self.filter_rules_edit = QPlainTextEdit()
        self.filter_rules_edit.setPlaceholderText(
            "+ /Нужная/**\n"
            "+ /Ещё одна/**"
        )

        browse_button = QPushButton("Обзор…")
        browse_button.clicked.connect(self._select_source_folder)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_edit, 1)
        source_row.addWidget(browse_button)

        interval_row = QHBoxLayout()
        interval_row.addWidget(self.interval_days_combo)
        interval_row.addWidget(self.interval_hours_combo)
        interval_row.addWidget(self.interval_minutes_combo)
        interval_row.addStretch(1)

        scheduled_time_row = QHBoxLayout()
        scheduled_time_row.addWidget(self.scheduled_time_checkbox)
        scheduled_time_row.addWidget(self.scheduled_time_edit)
        scheduled_time_row.addStretch(1)

        interval_state_row = QHBoxLayout()
        self.pause_interval_button = QPushButton("Отключить временно")
        self.pause_interval_button.clicked.connect(self._pause_interval)
        self.resume_interval_button = QPushButton("Включить")
        self.resume_interval_button.clicked.connect(self._resume_interval)
        interval_state_row.addWidget(self.interval_state_label)
        interval_state_row.addWidget(self.pause_interval_button)
        interval_state_row.addWidget(self.resume_interval_button)
        interval_state_row.addStretch(1)

        form.addRow("Имя:", self.name_edit)
        form.addRow("Локальная папка:", source_row)
        form.addRow("Подключение:", self.remote_combo)
        form.addRow("Удалённый путь:", self.remote_edit)
        form.addRow("", self.enabled_checkbox)
        form.addRow("", self.dry_run_checkbox)
        form.addRow("max-delete:", self.max_delete_spin)
        form.addRow("", self.hard_delete_checkbox)
        form.addRow("", self.use_backup_checkbox)
        form.addRow("backup-dir:", self.backup_edit)
        form.addRow("Интервал:", interval_row)
        form.addRow("Старт:", scheduled_time_row)
        form.addRow("", interval_state_row)
        form.addRow("Exclude:", self.excludes_edit)
        form.addRow("Фильтры rclone:", self.filter_rules_edit)

        root.addLayout(form)

        note = QLabel(
            "Удалённый путь должен быть в формате `remote:папка/подпапка`. "
            "Для разрешённых подпапок укажите `+ ...`; всё остальное будет исключено автоматически. "
            "Новые и изменённые параметры задачи сбрасывают статус предыдущего dry-run."
        )
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        root.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Сохранить")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        root.addStretch(1)
        root.addLayout(buttons)

        self.use_backup_checkbox.toggled.connect(self.backup_edit.setEnabled)
        self.backup_edit.setEnabled(False)
        self.scheduled_time_checkbox.toggled.connect(self._update_scheduled_time_ui)
        self._update_scheduled_time_ui()
        self._update_interval_pause_ui()

    def _create_interval_combo(self, maximum: int, suffix: str) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(112)
        combo.view().setMinimumWidth(112)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for value in range(maximum + 1):
            combo.addItem(f"{value} {suffix}", value)
        return combo

    def _load_task(self, task: SyncTask) -> None:
        self.name_edit.setText(task.name)
        self.source_edit.setText(task.source_path)
        if remote_name := remote_name_from_path(task.remote_path):
            self._set_remote_combo_value(remote_name)
        self.remote_edit.setText(task.remote_path)
        self.enabled_checkbox.setChecked(task.enabled)
        self.dry_run_checkbox.setChecked(task.dry_run_first)
        self.max_delete_spin.setValue(task.max_delete)
        self.hard_delete_checkbox.setChecked(task.hard_delete)
        self.use_backup_checkbox.setChecked(task.use_backup_dir)
        self.backup_edit.setEnabled(task.use_backup_dir)
        self.backup_edit.setText(task.backup_dir)
        self._set_interval_minutes(task.interval_minutes)
        if task.scheduled_time:
            self.scheduled_time_checkbox.setChecked(True)
            self.scheduled_time_edit.setTime(
                QTime.fromString(task.scheduled_time, "HH:mm")
            )
        self.interval_paused = task.interval_paused
        self._update_scheduled_time_ui()
        self._update_interval_pause_ui()
        self.excludes_edit.setPlainText("\n".join(task.excludes))
        self.filter_rules_edit.setPlainText("\n".join(task.filter_rules))

    def _normalize_remote_names(self, names: list[str]) -> list[str]:
        normalized: list[str] = []
        for name in names:
            candidate = name.strip().removesuffix(":").strip()
            if is_valid_remote_name(candidate) and candidate not in normalized:
                normalized.append(candidate)
        return normalized

    def _set_remote_combo_value(self, remote_name: str) -> None:
        normalized = remote_name.strip().removesuffix(":").strip()
        if not is_valid_remote_name(normalized):
            return
        if normalized not in self.remote_names:
            return
        self._updating_remote_combo = True
        self.remote_combo.setCurrentText(normalized)
        self._updating_remote_combo = False

    def _apply_remote_combo_to_remote_path(self, remote_name: str) -> None:
        if self._updating_remote_combo:
            return
        normalized = remote_name.strip().removesuffix(":").strip()
        if not is_valid_remote_name(normalized):
            return

        current_path = self.remote_edit.text().strip()
        if current_path and is_valid_remote_path(current_path):
            _, subpath = current_path.split(":", 1)
        else:
            subpath = current_path
        self.remote_edit.setText(build_remote_path(normalized, subpath))

    def _set_interval_minutes(self, value: int) -> None:
        total = max(0, int(value))
        days, remainder = divmod(total, 24 * 60)
        hours, minutes = divmod(remainder, 60)
        self.interval_days_combo.setCurrentIndex(min(days, INTERVAL_MAX_DAYS))
        self.interval_hours_combo.setCurrentIndex(hours)
        self.interval_minutes_combo.setCurrentIndex(minutes)

    def _interval_minutes(self) -> int:
        days = int(self.interval_days_combo.currentData() or 0)
        hours = int(self.interval_hours_combo.currentData() or 0)
        minutes = int(self.interval_minutes_combo.currentData() or 0)
        return days * 24 * 60 + hours * 60 + minutes

    def _scheduled_time(self) -> str:
        if not self.scheduled_time_checkbox.isChecked():
            return ""
        return self.scheduled_time_edit.time().toString("HH:mm")

    def _pause_interval(self) -> None:
        self.interval_paused = True
        self._update_interval_pause_ui()

    def _resume_interval(self) -> None:
        self.interval_paused = False
        self._update_interval_pause_ui()

    def _update_interval_pause_ui(self) -> None:
        self.interval_state_label.setText(
            "Интервал временно отключен"
            if self.interval_paused
            else "Интервал активен"
        )
        self.pause_interval_button.setEnabled(not self.interval_paused)
        self.resume_interval_button.setEnabled(self.interval_paused)

    def _update_scheduled_time_ui(self) -> None:
        self.scheduled_time_edit.setEnabled(self.scheduled_time_checkbox.isChecked())

    def _select_source_folder(self) -> None:
        start_dir = self.source_edit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            "Выберите локальную папку",
            start_dir,
        )
        if selected:
            self.source_edit.setText(selected)

    def accept(self) -> None:
        errors = self._validate_inputs()
        if errors:
            QMessageBox.warning(self, "Проверьте форму", "\n".join(errors))
            return
        self._save_geometry()
        super().accept()

    def reject(self) -> None:
        self._save_geometry()
        super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._save_geometry()
        super().closeEvent(event)

    def _validate_inputs(self) -> list[str]:
        errors: list[str] = []
        if not self.name_edit.text().strip():
            errors.append("Введите имя задачи.")

        source_path = self.source_edit.text().strip()
        if not source_path:
            errors.append("Выберите локальную папку.")
        elif not Path(source_path).exists():
            errors.append("Локальная папка не существует.")

        remote_path = self.remote_edit.text().strip()
        if not is_valid_remote_path(remote_path):
            errors.append("Удалённый путь должен быть в формате `remote:папка`.")
        elif remote_name_from_path(remote_path) not in self.remote_names:
            errors.append("Выберите remote из списка настроенных подключений.")

        if self.use_backup_checkbox.isChecked():
            backup_dir = self.backup_edit.text().strip()
            if not backup_dir:
                errors.append("Укажите backup-dir или отключите эту опцию.")
            elif not is_valid_remote_path(backup_dir):
                errors.append("backup-dir должен быть в формате `remote:папка`.")
            elif remote_name_from_path(backup_dir) not in self.remote_names:
                errors.append("backup-dir должен использовать настроенный remote.")

        if self.scheduled_time_checkbox.isChecked() and self._interval_minutes() <= 0:
            errors.append("Для запуска по времени задайте интервал больше нуля.")

        for rule in self._filter_rules():
            if not (rule.startswith("+ ") or rule.startswith("- ")):
                errors.append(
                    "Каждая строка фильтров rclone должна начинаться с `+ ` или `- `."
                )
                break

        return errors

    def _filter_rules(self) -> list[str]:
        return [
            line.strip()
            for line in self.filter_rules_edit.toPlainText().splitlines()
            if line.strip() and not line.strip().startswith(("#", ";"))
        ]

    def build_task(self, existing: SyncTask | None = None) -> SyncTask:
        excludes = [
            line.strip()
            for line in self.excludes_edit.toPlainText().splitlines()
            if line.strip()
        ]
        filter_rules = self._filter_rules()

        if existing:
            return SyncTask(
                id=existing.id,
                name=self.name_edit.text().strip(),
                source_path=self.source_edit.text().strip(),
                remote_path=self.remote_edit.text().strip(),
                enabled=self.enabled_checkbox.isChecked(),
                dry_run_first=self.dry_run_checkbox.isChecked(),
                max_delete=self.max_delete_spin.value(),
                hard_delete=self.hard_delete_checkbox.isChecked(),
                use_backup_dir=self.use_backup_checkbox.isChecked(),
                backup_dir=self.backup_edit.text().strip(),
                excludes=excludes,
                filter_rules=filter_rules,
                interval_minutes=self._interval_minutes(),
                interval_paused=self.interval_paused,
                scheduled_time=self._scheduled_time(),
                last_run_started_at=existing.last_run_started_at,
                last_run_finished_at=existing.last_run_finished_at,
                last_status=existing.last_status,
                last_mode=existing.last_mode,
                last_error=existing.last_error,
                last_summary=existing.last_summary,
                last_dry_run_at=existing.last_dry_run_at,
                last_delete_candidates=existing.last_delete_candidates,
                last_change_candidates=existing.last_change_candidates,
                last_change_details=list(existing.last_change_details),
            )

        return SyncTask.create(
            name=self.name_edit.text().strip(),
            source_path=self.source_edit.text().strip(),
            remote_path=self.remote_edit.text().strip(),
            enabled=self.enabled_checkbox.isChecked(),
            dry_run_first=self.dry_run_checkbox.isChecked(),
            max_delete=self.max_delete_spin.value(),
            hard_delete=self.hard_delete_checkbox.isChecked(),
            use_backup_dir=self.use_backup_checkbox.isChecked(),
            backup_dir=self.backup_edit.text().strip(),
            excludes=excludes,
            filter_rules=filter_rules,
            interval_minutes=self._interval_minutes(),
            interval_paused=self.interval_paused,
            scheduled_time=self._scheduled_time(),
        )
