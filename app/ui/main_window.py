# -*- coding: utf-8 -*-
"""Главное окно приложения."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.app_config import (
    APP_NAME,
    APP_VERSION,
    bundled_rclone_path,
    detect_default_rclone_path,
    rclone_config_path,
)
from app.core.autostart import is_autostart_enabled, set_autostart_enabled
from app.core.settings_store import SettingsStore
from app.core.memory_limits import (
    MAX_LOG_BLOCKS,
    MAX_LOG_MESSAGE_CHARS,
    bounded_change_details,
)
from app.models.sync_task import SyncTask
from app.services.rclone_config import (
    configure_mega_remotes,
    is_valid_remote_name,
    list_configured_remotes,
    normalize_remote_name,
    parse_remote_list,
    read_mega_credentials_file,
    remote_name_from_path,
    remote_prefix,
)
from app.services.rclone_runner import RcloneRunner
from app.ui.task_dialog import TaskDialog


class MainWindow(QMainWindow):
    WM_NCRBUTTONDOWN = 0x00A4
    WM_NCRBUTTONUP = 0x00A5
    HTCLOSE = 20

    def __init__(self, settings_store: SettingsStore) -> None:
        super().__init__()
        self.settings_store = settings_store
        self.tasks = [
            SyncTask.from_dict(item) for item in self.settings_store.get_tasks_data()
        ]
        self.runner = RcloneRunner(self)
        self.command_queue: list[dict[str, object]] = []
        self._scheduled_confirmation_task_ids: set[str] = set()
        self._pending_confirmation_task_ids: list[str] = []
        self._current_task_id: str | None = None
        self._updating_table = False
        self._task_sort_column: int | None = None
        self._task_sort_order = Qt.SortOrder.AscendingOrder
        self._remote_check_total = 0
        self._remote_check_done = 0
        self._remote_check_failures: list[str] = []
        self._quota_remote_name = ""

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self._create_ui()
        self._create_tray_icon()
        self._connect_runner()
        self._load_settings_into_ui()
        self._restore_geometry()
        self._refresh_table()
        self._set_busy(False)

        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(800)
        self._geometry_save_timer.timeout.connect(self._save_geometry)

        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.setInterval(30_000)
        self.scheduler_timer.timeout.connect(self._check_due_tasks)
        self.scheduler_timer.start()
        if self._runtime_checks_enabled():
            QTimer.singleShot(0, self._startup_check_remotes)

    def _runtime_checks_enabled(self) -> bool:
        return self.settings_store.path == rclone_config_path().parent / "settings.json"

    def _create_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("titleLabel")
        subtitle_container = QVBoxLayout()
        subtitle_container.addWidget(title)
        header.addLayout(subtitle_container)
        header.addStretch(1)
        self.remote_status_label = QLabel("Remote: не проверено")
        self.remote_status_label.setObjectName("statusBadge")
        header.addWidget(self.remote_status_label)
        root_layout.addLayout(header)

        root_layout.addWidget(self._build_rclone_group())

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setOpaqueResize(True)
        self.content_splitter.setHandleWidth(10)
        self.content_splitter.addWidget(self._build_tasks_group())
        self.log_group = self._build_log_group()
        self.content_splitter.addWidget(self.log_group)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.splitterMoved.connect(self._save_splitter_sizes)
        root_layout.addWidget(self.content_splitter, 1)

        self.setCentralWidget(root)
        self._create_status_bar()

    def _build_rclone_group(self) -> QGroupBox:
        group = QGroupBox("Подключения rclone")
        layout = QVBoxLayout(group)
        main_row = QHBoxLayout()

        self.rclone_mode_label = QLabel("rclone: встроенный")
        self.rclone_mode_label.setObjectName("mutedLabel")
        self.remote_combo = QComboBox()
        self.remote_combo.setEditable(False)
        self.remote_combo.setMinimumWidth(140)
        self.remote_combo.currentTextChanged.connect(self._on_remote_selection_changed)
        self.remote_quota_bar = QProgressBar()
        self.remote_quota_bar.setFixedWidth(220)
        self.remote_quota_bar.setFixedHeight(28)
        self.remote_quota_bar.setRange(0, 1000)
        self.remote_quota_bar.setValue(0)
        self.remote_quota_bar.setFormat("Квота: —")

        self.rclone_path_edit = QLineEdit()
        self.rclone_path_edit.setPlaceholderText(r"vendor\rclone\rclone.exe")
        self.rclone_path_edit.editingFinished.connect(self._save_runtime_state)

        browse_button = QPushButton("Обзор…")
        browse_button.clicked.connect(self._browse_rclone)

        builtin_button = QPushButton("Встроенный rclone")
        builtin_button.clicked.connect(self._use_bundled_rclone)

        version_button = QPushButton("Версия rclone")
        version_button.clicked.connect(self._run_version)

        config_button = QPushButton("Путь к rclone.conf")
        config_button.clicked.connect(self._run_config_file)

        refresh_remotes_button = QPushButton("Обновить remote")
        refresh_remotes_button.clicked.connect(self._refresh_remote_names_from_config)

        setup_mega_button = QPushButton("Добавить Remote")
        setup_mega_button.clicked.connect(self._select_credentials_file_and_import_remotes)

        self.remote_check_button = QPushButton("Проверить аккаунты")
        self.remote_check_button.clicked.connect(self._run_mega_check)

        self.advanced_rclone_button = QPushButton("Дополнительно")
        self.advanced_rclone_button.setCheckable(True)
        self.advanced_rclone_button.toggled.connect(self._toggle_rclone_advanced)
        self.advanced_button = self.advanced_rclone_button

        self.log_toggle_button = QPushButton("Показать журнал")
        self.log_toggle_button.setCheckable(True)
        self.log_toggle_button.toggled.connect(self._set_log_visible)

        main_row.addWidget(self.rclone_mode_label)
        main_row.addWidget(QLabel("Remote:"))
        main_row.addWidget(self.remote_combo)
        main_row.addWidget(self.remote_quota_bar)
        main_row.addStretch(1)
        main_row.addWidget(setup_mega_button)
        main_row.addWidget(self.remote_check_button)
        main_row.addWidget(self.advanced_rclone_button)
        main_row.addWidget(self.log_toggle_button)
        layout.addLayout(main_row)

        self.rclone_advanced_panel = QWidget()
        advanced_layout = QVBoxLayout(self.rclone_advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("rclone.exe:"))
        path_row.addWidget(self.rclone_path_edit, 1)
        path_row.addWidget(browse_button)
        path_row.addWidget(builtin_button)
        advanced_layout.addLayout(path_row)

        diagnostics_row = QHBoxLayout()
        diagnostics_row.addWidget(version_button)
        diagnostics_row.addWidget(config_button)
        diagnostics_row.addWidget(refresh_remotes_button)
        diagnostics_row.addStretch(1)
        advanced_layout.addLayout(diagnostics_row)
        self.rclone_advanced_panel.hide()
        layout.addWidget(self.rclone_advanced_panel)

        startup_row = QHBoxLayout()
        self.autostart_checkbox = QCheckBox("Автозагрузка Windows")
        self.autostart_checkbox.toggled.connect(self._toggle_autostart)
        self.start_minimized_checkbox = QCheckBox("Запускать в трее")
        self.start_minimized_checkbox.toggled.connect(self._toggle_start_minimized)
        startup_row.addWidget(self.autostart_checkbox)
        startup_row.addWidget(self.start_minimized_checkbox)
        startup_row.addStretch(1)
        layout.addLayout(startup_row)

        hint = QLabel(
            "Обычный сценарий: один раз импортировать MEGA remote из INI-файла, "
            "после этого «Все аккаунты» показывает общую очередь задач. "
            "«Зеркалировать всё» проверяет задачи и запускает их последовательно. При запуске приложение "
            "проверяет уже настроенные remote из локального rclone.conf."
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return group

    def _build_tasks_group(self) -> QGroupBox:
        group = QGroupBox("Задачи синхронизации")
        layout = QVBoxLayout(group)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "☐",
                "Имя",
                "Аккаунт",
                "Запуск",
                "Режим",
                "След. попытка",
                "Статус",
                "Действия",
            ]
        )
        header_tooltips = [
            "Включить или отключить все задачи",
            "Имя",
            "Облачный аккаунт; полный путь назначения — в подсказке",
            "Последний запуск",
            "Режим",
            "Следующая попытка",
            "Статус",
            "Действия",
        ]
        for column, tooltip in enumerate(header_tooltips):
            if 1 <= column <= 6:
                tooltip += ". Нажмите для сортировки; повторный клик меняет направление."
            if item := self.table.horizontalHeaderItem(column):
                item.setToolTip(tooltip)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(36)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(3, 142)
        self.table.setColumnWidth(4, 86)
        self.table.setColumnWidth(5, 148)
        self.table.setColumnWidth(7, 448)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.itemDoubleClicked.connect(lambda _: self._edit_selected_task())
        self.table.itemSelectionChanged.connect(self._update_action_buttons)
        header.sectionClicked.connect(self._on_table_header_clicked)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Добавить")
        self.add_button.clicked.connect(self._add_task)
        self.edit_button = QPushButton("Изменить")
        self.edit_button.clicked.connect(self._edit_selected_task)
        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete_selected_task)
        self.check_all_button = QPushButton("Проверить все")
        self.check_all_button.clicked.connect(self._check_all_tasks)
        self.sync_all_button = QPushButton("Зеркалировать всё")
        self.sync_all_button.clicked.connect(self._sync_all_tasks)
        self.stop_all_button = QPushButton("Остановить все")
        self.stop_all_button.setObjectName("dangerButton")
        self.stop_all_button.clicked.connect(self._stop_all_commands)

        for button in (self.add_button, self.edit_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        for button in (
            self.check_all_button,
            self.sync_all_button,
            self.stop_all_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Журнал")
        layout = QVBoxLayout(group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_BLOCKS)
        self.log_view.setUndoRedoEnabled(False)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log_view)
        return group

    def _create_status_bar(self) -> None:
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.status_label = QLabel("Готово.")
        self.stats_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(180)
        self.progress_bar.hide()
        status_bar.addWidget(self.status_label, 1)
        status_bar.addPermanentWidget(self.stats_label)
        status_bar.addPermanentWidget(self.progress_bar)

    def _create_tray_icon(self) -> None:
        self.tray_icon: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = QApplication.windowIcon()
        if icon.isNull():
            return

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(APP_NAME)
        self.tray_menu = self._build_tray_menu()
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.messageClicked.connect(self._show_window_from_notification)
        self.tray_icon.show()

    def _build_tray_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.aboutToShow.connect(self._update_tray_menu)

        self.tray_show_action = QAction("Открыть", self)
        self.tray_show_action.triggered.connect(self._show_window_from_notification)
        menu.addAction(self.tray_show_action)

        self.tray_hide_action = QAction("Свернуть в трей", self)
        self.tray_hide_action.triggered.connect(self.hide_to_tray)
        menu.addAction(self.tray_hide_action)

        menu.addSeparator()

        self.tray_exit_action = QAction("Выход", self)
        self.tray_exit_action.triggered.connect(self._exit_from_tray)
        menu.addAction(self.tray_exit_action)
        self._update_tray_menu()

        return menu

    def _update_tray_menu(self) -> None:
        if not hasattr(self, "tray_hide_action"):
            return
        self.tray_hide_action.setVisible(self.isVisible() and not self.isMinimized())

    def _on_tray_activated(
        self, reason: QSystemTrayIcon.ActivationReason
    ) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._show_window_from_notification()

    def hide_to_tray(self) -> None:
        if not self.tray_icon:
            self.showMinimized()
            return
        self._save_geometry()
        self.hide()

    def _show_window_from_notification(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _exit_from_tray(self) -> None:
        if self.close():
            if self.tray_icon:
                self.tray_icon.hide()
            app = QApplication.instance()
            if app:
                app.quit()

    def _connect_runner(self) -> None:
        self.runner.command_started.connect(self._on_command_started)
        self.runner.command_output.connect(self._append_log)
        self.runner.stats_updated.connect(self._on_stats_updated)
        self.runner.command_finished.connect(self._on_command_finished)
        self.runner.busy_changed.connect(self._set_busy)

    def _load_settings_into_ui(self) -> None:
        self.rclone_path_edit.setText(self.settings_store.get_rclone_path())
        self._update_rclone_mode_label()
        self._set_remote_combo_items(
            self.settings_store.get_remote_names(),
            self.settings_store.get_selected_remote(),
        )
        self.autostart_checkbox.blockSignals(True)
        self.autostart_checkbox.setChecked(
            self.settings_store.get_autostart_enabled() or is_autostart_enabled()
        )
        self.autostart_checkbox.blockSignals(False)
        self.start_minimized_checkbox.blockSignals(True)
        self.start_minimized_checkbox.setChecked(
            self.settings_store.get_start_minimized()
        )
        self.start_minimized_checkbox.blockSignals(False)

    def _set_remote_combo_items(
        self, remote_names: list[str], selected_remote: str | None = None
    ) -> None:
        normalized_names: list[str] = []
        for name in remote_names:
            normalized = normalize_remote_name(name)
            if is_valid_remote_name(normalized) and normalized not in normalized_names:
                normalized_names.append(normalized)
        if not normalized_names:
            self.remote_combo.blockSignals(True)
            self.remote_combo.clear()
            self.remote_combo.blockSignals(False)
            self.settings_store.set_remote_names([])
            self.settings_store.set_selected_remote("")
            self._set_quota_unavailable("Квота: —")
            self._refresh_table()
            return

        selected = normalize_remote_name(selected_remote or normalized_names[0])
        if not is_valid_remote_name(selected):
            selected = normalized_names[0]
        if selected not in normalized_names:
            selected = normalized_names[0]

        self.remote_combo.blockSignals(True)
        self.remote_combo.clear()
        self.remote_combo.addItem("Все аккаунты", "")
        for name in normalized_names:
            self.remote_combo.addItem(name, name)
        self.remote_combo.setCurrentIndex(
            0
            if self.settings_store.settings.get("show_all_accounts", True)
            else self.remote_combo.findData(selected)
        )
        self.remote_combo.blockSignals(False)
        self.settings_store.set_remote_names(normalized_names)
        self.settings_store.set_selected_remote(selected)
        self._update_account_scope_ui()

    def _all_accounts_selected(self) -> bool:
        return (
            self.remote_combo.currentIndex() >= 0
            and self.remote_combo.currentData() == ""
        )

    def _update_account_scope_ui(self) -> None:
        all_accounts = self._all_accounts_selected()
        self.sync_all_button.setText(
            "Зеркалировать всё" if all_accounts else "Зеркалировать аккаунт"
        )
        self.check_all_button.setText(
            "Проверить все" if all_accounts else "Проверить аккаунт"
        )
        self.remote_check_button.setText(
            "Проверить аккаунты" if all_accounts else "Проверить выбранный"
        )
        if all_accounts:
            count = len(self.settings_store.get_remote_names())
            self.remote_status_label.setText(f"Все аккаунты: {count}")
            self._set_quota_unavailable(f"Аккаунтов: {count}")

    def _current_remote_name(self) -> str:
        if self._all_accounts_selected():
            return ""
        remote_name = normalize_remote_name(self.remote_combo.currentText())
        if not is_valid_remote_name(remote_name):
            QMessageBox.warning(
                self,
                "Remote",
                "Сначала добавьте Remote из INI-файла.",
            )
            return ""
        return remote_name

    def _on_remote_selection_changed(self, remote_name: str) -> None:
        self.settings_store.settings["show_all_accounts"] = (
            self._all_accounts_selected()
        )
        self._update_account_scope_ui()
        if self._all_accounts_selected():
            self.settings_store.save()
            self._refresh_table()
            return
        normalized = normalize_remote_name(remote_name)
        if not is_valid_remote_name(normalized):
            return
        self.settings_store.set_selected_remote(normalized)
        self.settings_store.save()
        self.remote_status_label.setText(f"{remote_prefix(normalized)} не проверено")
        if self._runtime_checks_enabled():
            self._request_remote_quota(normalized)
        self._refresh_table()

    def _visible_tasks(self) -> list[SyncTask]:
        if self._all_accounts_selected():
            return list(self.tasks)
        selected_remote = normalize_remote_name(self.remote_combo.currentText())
        if not is_valid_remote_name(selected_remote):
            return []
        return [
            task
            for task in self.tasks
            if remote_name_from_path(task.remote_path) == selected_remote
        ]

    def _toggle_autostart(self, enabled: bool) -> None:
        try:
            path = set_autostart_enabled(enabled)
        except Exception as exc:
            self.autostart_checkbox.blockSignals(True)
            self.autostart_checkbox.setChecked(not enabled)
            self.autostart_checkbox.blockSignals(False)
            QMessageBox.warning(
                self,
                "Автозагрузка",
                f"Не удалось обновить автозагрузку Windows:\n{exc}",
            )
            return

        self.settings_store.set_autostart_enabled(enabled)
        if enabled:
            self.settings_store.set_start_minimized(True)
            self.start_minimized_checkbox.blockSignals(True)
            self.start_minimized_checkbox.setChecked(True)
            self.start_minimized_checkbox.blockSignals(False)
        self._save_runtime_state()

        if path:
            action = "создана" if enabled else "удалена"
            self._append_log(f"Автозагрузка {action}: {path}")

    def _toggle_start_minimized(self, enabled: bool) -> None:
        self.settings_store.set_start_minimized(enabled)
        self._save_runtime_state()

    def _restore_geometry(self) -> None:
        window = self.settings_store.get_window_settings()
        saved_geometry = window.get("geometry", "")
        restored = False
        if isinstance(saved_geometry, str) and saved_geometry:
            restored = self.restoreGeometry(
                QByteArray.fromBase64(saved_geometry.encode("ascii", errors="ignore"))
            )
        if not restored:
            width = int(window.get("width", 1200))
            height = int(window.get("height", 760))
            x = int(window.get("x", 120))
            y = int(window.get("y", 120))
            self.resize(width, height)
            self.move(x, y)
            if bool(window.get("maximized", False)):
                self.showMaximized()
        self._restore_log_visibility()
        self._restore_splitter_sizes()

    def _save_geometry(self) -> None:
        geo = self.normalGeometry() if self.isMaximized() else self.geometry()
        position = geo.topLeft() if self.isMaximized() else self.pos()
        window = self.settings_store.get_window_settings()
        window.update(
            {
                "x": position.x(),
                "y": position.y(),
                "width": geo.width(),
                "height": geo.height(),
                "maximized": self.isMaximized(),
                "geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
            }
        )
        self._save_runtime_state()

    def _restore_confirm_dialog_geometry(
        self, dialog: QDialog, max_width: int, max_height: int
    ) -> bool:
        saved = self.settings_store.get_confirm_dialog_settings()
        try:
            x = saved.get("x")
            y = saved.get("y")
            width = int(saved.get("width", 720))
            height = int(saved.get("height", 560))
        except (TypeError, ValueError):
            return False
        if not isinstance(x, int) or not isinstance(y, int):
            return False
        width = max(400, min(width, max_width))
        height = max(300, min(height, max_height))
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = max(
                available.x(),
                min(x, available.x() + available.width() - min(width, 200)),
            )
            y = max(
                available.y(),
                min(y, available.y() + available.height() - min(height, 200)),
            )
        dialog.resize(width, height)
        dialog.move(x, y)
        return True

    def _save_confirm_dialog_geometry(self, dialog: QDialog) -> None:
        geo = dialog.geometry()
        self.settings_store.set_dialog_geometry(
            "confirm_dialog",
            x=dialog.pos().x(),
            y=dialog.pos().y(),
            width=geo.width(),
            height=geo.height(),
        )
        self.settings_store.save()

    def _restore_splitter_sizes(self) -> None:
        window = self.settings_store.get_window_settings()
        raw_sizes = window.get("content_splitter_sizes", [])
        if not bool(window.get("log_visible", False)):
            self.content_splitter.setSizes([780, 0])
            return
        if (
            isinstance(raw_sizes, list)
            and len(raw_sizes) == 2
            and all(isinstance(value, int) and value > 0 for value in raw_sizes)
        ):
            self.content_splitter.setSizes(raw_sizes)
        else:
            self.content_splitter.setSizes([520, 260])

    def _save_splitter_sizes(self) -> None:
        if hasattr(self, "log_group") and self.log_group.isHidden():
            return
        window = self.settings_store.get_window_settings()
        window["content_splitter_sizes"] = self.content_splitter.sizes()
        self._save_runtime_state()

    def _restore_log_visibility(self) -> None:
        window = self.settings_store.get_window_settings()
        self._set_log_visible(bool(window.get("log_visible", False)), save=False)

    def _valid_splitter_sizes(self, raw_sizes: object) -> list[int] | None:
        if (
            isinstance(raw_sizes, list)
            and len(raw_sizes) == 2
            and all(isinstance(value, int) and value > 0 for value in raw_sizes)
        ):
            return raw_sizes
        return None

    def _current_task_panel_height(self) -> int:
        sizes = self.content_splitter.sizes()
        if len(sizes) == 2 and sizes[0] > 0:
            return sizes[0]
        task_height = self.content_splitter.widget(0).height()
        if task_height > 0:
            return task_height
        stored_sizes = self._valid_splitter_sizes(
            self.settings_store.get_window_settings().get("content_splitter_sizes", [])
        )
        if stored_sizes:
            return stored_sizes[0]
        return 520

    def _resize_window_for_log_toggle(self, delta_height: int) -> None:
        if delta_height == 0 or self.isMaximized():
            return
        target_height = max(self.minimumHeight(), self.height() + delta_height)
        self.resize(self.width(), target_height)

    def _set_log_visible(self, visible: bool, *, save: bool = True) -> None:
        window = self.settings_store.get_window_settings()
        stored_sizes = self._valid_splitter_sizes(window.get("content_splitter_sizes", []))
        current_sizes = self.content_splitter.sizes()
        current_task_height = self._current_task_panel_height()
        default_log_height = stored_sizes[1] if stored_sizes else 260
        handle_height = 10
        was_visible = not self.log_group.isHidden()

        if visible and not was_visible and save:
            self._resize_window_for_log_toggle(default_log_height + handle_height)
        elif not visible and was_visible:
            if self._valid_splitter_sizes(current_sizes):
                window["content_splitter_sizes"] = current_sizes
                default_log_height = current_sizes[1]
            if save:
                self._resize_window_for_log_toggle(-(default_log_height + handle_height))

        self.log_group.setVisible(visible)
        self.content_splitter.setHandleWidth(handle_height if visible else 0)
        self.log_toggle_button.blockSignals(True)
        self.log_toggle_button.setChecked(visible)
        self.log_toggle_button.setText("Скрыть журнал" if visible else "Показать журнал")
        self.log_toggle_button.blockSignals(False)

        window["log_visible"] = visible
        if visible:
            if save:
                self.content_splitter.setSizes([current_task_height, default_log_height])
            elif stored_sizes:
                self.content_splitter.setSizes(stored_sizes)
            else:
                self.content_splitter.setSizes([520, 260])
        else:
            self.content_splitter.setSizes([current_task_height, 0])

        if save:
            self._save_runtime_state()

    def _save_runtime_state(self) -> None:
        self.settings_store.set_rclone_path(self.rclone_path_edit.text())
        remote_name = normalize_remote_name(self.remote_combo.currentText())
        if is_valid_remote_name(remote_name):
            self.settings_store.set_selected_remote(remote_name)
        elif not self._all_accounts_selected():
            self.settings_store.set_selected_remote("")
        self.settings_store.settings["show_all_accounts"] = (
            self._all_accounts_selected()
        )
        self.settings_store.set_tasks_data([task.to_dict() for task in self.tasks])
        self.settings_store.set_remote_names(self.settings_store.get_remote_names())
        self.settings_store.save()
        self._update_rclone_mode_label()

    def _refresh_table(self) -> None:
        selected_task_id = self._selected_task_id()
        visible_tasks = self._visible_tasks()
        if self._task_sort_column is not None:
            visible_tasks = sorted(
                visible_tasks,
                key=self._task_sort_key,
                reverse=self._task_sort_order == Qt.SortOrder.DescendingOrder,
            )
        self._updating_table = True
        self.table.setRowCount(len(visible_tasks))

        for row, task in enumerate(visible_tasks):
            self.table.setRowHeight(row, 48)
            active_item = QTableWidgetItem()
            active_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            active_item.setCheckState(
                Qt.CheckState.Checked if task.enabled else Qt.CheckState.Unchecked
            )
            active_item.setData(Qt.ItemDataRole.UserRole, task.id)
            self.table.setItem(row, 0, active_item)

            values = [
                task.name,
                remote_name_from_path(task.remote_path),
                task.last_run_label(),
                task.mode_label(),
                task.next_run_label(),
                task.last_status,
            ]
            for offset, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, task.id)
                if offset == 2:
                    item.setToolTip(task.remote_path)
                self.table.setItem(row, offset, item)

            self.table.setCellWidget(row, 7, self._build_task_actions_widget(task))

        self._updating_table = False
        self._update_active_header_state()

        if selected_task_id:
            self._select_task_by_id(selected_task_id)
        if self.table.currentRow() < 0 and visible_tasks:
            self.table.selectRow(0)

        self._update_action_buttons()

    def _task_sort_key(self, task: SyncTask) -> tuple[int, float | str]:
        column = self._task_sort_column
        if column == 3:
            value = task.last_run_finished_at or task.last_run_started_at
            try:
                return (0, datetime.fromisoformat(value).timestamp())
            except ValueError:
                return (1, value.casefold())
        if column == 5:
            label = task.next_run_label()
            due_at = task.due_run_at()
            if due_at and (label == "Сейчас" or label[:1].isdigit()):
                return (0, due_at.timestamp())
            return (1, label.casefold())
        value = {
            1: task.name,
            2: remote_name_from_path(task.remote_path),
            4: task.mode_label(),
            6: task.last_status,
        }.get(column, "")
        return (0, value.casefold())

    def _build_task_actions_widget(self, task: SyncTask) -> QWidget:
        widget = QWidget()
        widget.setAutoFillBackground(True)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        check_button = QPushButton("Проверить")
        check_button.clicked.connect(lambda _, task_id=task.id: self._check_task(task_id))
        check_button.setEnabled(not self.runner.is_running and task.enabled)

        sync_button = QPushButton("Синхронизировать")
        sync_button.clicked.connect(lambda _, task_id=task.id: self._sync_task(task_id))
        sync_button.setEnabled(not self.runner.is_running and task.enabled)

        stop_button = QPushButton("Остановить")
        stop_button.setObjectName("dangerButton")
        stop_button.clicked.connect(lambda _, task_id=task.id: self._stop_task(task_id))
        stop_button.setEnabled(
            self._current_task_id == task.id or self._is_task_queued_any(task.id)
        )

        button_widths = {
            check_button: 112,
            sync_button: 172,
            stop_button: 112,
        }
        for button, width in button_widths.items():
            button.setFixedWidth(width)
            button.setMinimumHeight(32)
            layout.addWidget(button)

        return widget

    def _selected_task_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole))

    def _selected_task(self) -> SyncTask | None:
        task_id = self._selected_task_id()
        if not task_id:
            return None
        return self._find_task(task_id)

    def _select_task_by_id(self, task_id: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == task_id:
                self.table.selectRow(row)
                break

    def _find_task(self, task_id: str) -> SyncTask | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def _update_action_buttons(self) -> None:
        has_selection = self._selected_task() is not None
        visible_tasks = self._visible_tasks()
        for button in (self.edit_button, self.delete_button):
            button.setEnabled(has_selection and not self.runner.is_running)
        self.add_button.setEnabled(not self.runner.is_running)
        self.check_all_button.setEnabled(
            bool(visible_tasks) and not self.runner.is_running
        )
        self.sync_all_button.setEnabled(
            bool(visible_tasks) and not self.runner.is_running
        )
        self.stop_all_button.setEnabled(self.runner.is_running or bool(self.command_queue))

    def _browse_rclone(self) -> None:
        start_dir = (
            str(Path(self.rclone_path_edit.text()).parent)
            if self.rclone_path_edit.text().strip()
            else str(Path.home())
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите rclone.exe",
            start_dir,
            "Исполняемые файлы (*.exe);;Все файлы (*)",
        )
        if path:
            self.rclone_path_edit.setText(path)
            self.settings_store.set_use_custom_rclone(True)
            self._save_runtime_state()

    def _use_bundled_rclone(self) -> None:
        self.settings_store.set_use_custom_rclone(False)
        self.rclone_path_edit.setText(detect_default_rclone_path())
        self._save_runtime_state()
        self._append_log(f"Используется основной rclone: {self.rclone_path_edit.text()}.")

    def _toggle_rclone_advanced(self, checked: bool) -> None:
        self.rclone_advanced_panel.setVisible(checked)
        self.advanced_rclone_button.setText(
            "Скрыть детали" if checked else "Дополнительно"
        )

    def _update_rclone_mode_label(self) -> None:
        if not hasattr(self, "rclone_mode_label"):
            return

        rclone_path = (
            self.rclone_path_edit.text().strip() or detect_default_rclone_path()
        )
        if self.settings_store.get_use_custom_rclone():
            mode = "rclone: внешний"
        elif self._same_path(rclone_path, bundled_rclone_path()):
            mode = "rclone: встроенный"
        else:
            mode = "rclone: найден автоматически"

        self.rclone_mode_label.setText(mode)
        self.rclone_mode_label.setToolTip(rclone_path)

    @staticmethod
    def _same_path(left: str | Path, right: str | Path) -> bool:
        try:
            return Path(left).resolve() == Path(right).resolve()
        except OSError:
            return Path(left) == Path(right)

    def _select_credentials_file_and_import_remotes(self) -> None:
        venv_dir = rclone_config_path().parent / ".venv"
        start_dir = str(venv_dir if venv_dir.exists() else Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите INI-файл с MEGA аккаунтами",
            start_dir,
            "INI и текстовые файлы (*.ini *.txt);;Все файлы (*)",
        )
        if path:
            self._import_remotes_from_credentials_file(Path(path))

    def _import_remotes_from_credentials_file(
        self, path: Path, *, show_messages: bool = True
    ) -> bool:
        rclone_path = self._current_rclone_path(show_warnings=show_messages)
        if not rclone_path:
            return False

        try:
            credentials = read_mega_credentials_file(path)
        except ValueError as exc:
            if show_messages:
                QMessageBox.warning(self, "Добавить Remote", str(exc))
            self._append_log("Импорт remote из INI не выполнен: файл не прочитан.")
            return False

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = configure_mega_remotes(
                rclone_path=rclone_path,
                config_path=rclone_config_path(),
                credentials=credentials,
            )
        finally:
            QApplication.restoreOverrideCursor()

        if result.configured_remote_names:
            for remote_name in result.configured_remote_names:
                self.settings_store.add_remote_name(remote_name)
            self._set_remote_combo_items(
                self.settings_store.get_remote_names(),
                result.configured_remote_names[0],
            )
            self._save_runtime_state()
            if self._runtime_checks_enabled():
                self._request_remote_quota(result.configured_remote_names[0])

        self._append_log(result.summary)
        if result.failed_remote_names and show_messages:
            QMessageBox.warning(self, "Добавить Remote", result.summary)
        elif show_messages:
            QMessageBox.information(self, "Добавить Remote", result.summary)

        if result.configured_remote_names:
            self._queue_remote_checks(result.configured_remote_names)
        return result.success

    def _add_task(self) -> None:
        remote_names = self.settings_store.get_remote_names()
        current_remote = (
            self._current_remote_name() or self.settings_store.get_selected_remote()
        )
        if not remote_names or not current_remote:
            return
        dialog = TaskDialog(
            parent=self,
            remote_names=remote_names,
            default_remote_name=current_remote,
        )
        if dialog.exec() != TaskDialog.DialogCode.Accepted:
            return
        task = dialog.build_task()
        self.tasks.append(task)
        self._append_log(f"Добавлена задача `{task.name}`.")
        self._save_runtime_state()
        self._refresh_table()
        self._select_task_by_id(task.id)

    def _edit_selected_task(self) -> None:
        task = self._selected_task()
        if not task:
            return

        dialog = TaskDialog(
            task=task,
            parent=self,
            remote_names=self.settings_store.get_remote_names(),
            default_remote_name=self._current_remote_name() or remote_name_from_path(task.remote_path),
        )
        if dialog.exec() != TaskDialog.DialogCode.Accepted:
            return

        updated = dialog.build_task(existing=task)
        signature_changed = (
            task.operational_signature() != updated.operational_signature()
        )

        task.name = updated.name
        task.source_path = updated.source_path
        task.remote_path = updated.remote_path
        task.enabled = updated.enabled
        task.dry_run_first = updated.dry_run_first
        task.max_delete = updated.max_delete
        task.hard_delete = updated.hard_delete
        task.use_backup_dir = updated.use_backup_dir
        task.backup_dir = updated.backup_dir
        task.excludes = list(updated.excludes)
        task.filter_rules = list(updated.filter_rules)
        task.interval_minutes = updated.interval_minutes
        task.interval_paused = updated.interval_paused
        task.scheduled_time = updated.scheduled_time

        if signature_changed:
            task.reset_runtime_state()

        self._append_log(f"Обновлена задача `{task.name}`.")
        self._save_runtime_state()
        self._refresh_table()
        self._select_task_by_id(task.id)

    def _delete_selected_task(self) -> None:
        task = self._selected_task()
        if not task:
            return
        answer = QMessageBox.question(
            self,
            "Удаление задачи",
            f"Удалить задачу `{task.name}`?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.tasks = [item for item in self.tasks if item.id != task.id]
        self._append_log(f"Удалена задача `{task.name}`.")
        self._save_runtime_state()
        self._refresh_table()

    def _check_selected_task(self) -> None:
        task = self._selected_task()
        if task:
            self._check_task(task.id)

    def _check_task(self, task_id: str) -> None:
        task = self._find_task(task_id)
        if task:
            self._enqueue_task(
                task,
                dry_run=True,
                reason="Ручная проверка",
                scheduled_confirmation=True,
            )

    def _sync_selected_task(self) -> None:
        task = self._selected_task()
        if task:
            self._sync_task(task.id)

    def _sync_task(self, task_id: str) -> None:
        task = self._find_task(task_id)
        if not task:
            return
        if task.needs_first_dry_run():
            QMessageBox.warning(
                self,
                "Сначала проверка",
                "Эта задача ещё не проходила dry-run. Сначала нажмите `Проверить`.",
            )
            return

        message = (
            "Будет запущен `rclone sync`, который может удалить лишние файлы в облаке."
        )
        if task.last_delete_candidates:
            message += (
                f"\n\nПо последней проверке найдено потенциальных удалений: "
                f"{task.last_delete_candidates}."
            )
        answer = QMessageBox.question(
            self,
            "Подтвердите синхронизацию",
            message,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._enqueue_task(task, dry_run=False, reason="Ручной sync")

    def _check_all_tasks(self) -> None:
        enabled_tasks = [task for task in self._visible_tasks() if task.enabled]
        if not enabled_tasks:
            QMessageBox.information(
                self,
                "Нет задач",
                "Нет включённых задач в текущем списке для проверки.",
            )
            return

        for task in enabled_tasks:
            self._enqueue_task(
                task,
                dry_run=True,
                reason="Массовая проверка",
                silent=True,
                scheduled_confirmation=True,
            )

        self._append_log(
            f"В очередь проверки добавлено задач: {len(enabled_tasks)}."
        )
        self._start_next_queued_command()

    def _sync_all_tasks(self) -> None:
        enabled_tasks = [task for task in self._visible_tasks() if task.enabled]
        if not enabled_tasks:
            QMessageBox.information(
                self,
                "Нет задач",
                "Нет включённых задач в текущем списке для запуска.",
            )
            return

        queued = 0
        account_order = {
            name: index
            for index, name in enumerate(
                dict.fromkeys(
                    remote_name_from_path(task.remote_path) for task in enabled_tasks
                )
            )
        }
        for task in sorted(
            enabled_tasks,
            key=lambda task: account_order[remote_name_from_path(task.remote_path)],
        ):
            self._enqueue_task(
                task,
                dry_run=True,
                reason="Проверка перед массовым зеркалированием",
                silent=True,
                scheduled_confirmation=True,
            )
            queued += 1

        if queued:
            self._append_log(
                f"В очередь добавлено задач: {queued}. Запуск будет последовательным."
            )
            self._start_next_queued_command()

    def _enqueue_task(
        self,
        task: SyncTask,
        *,
        dry_run: bool,
        reason: str,
        silent: bool = False,
        scheduled_confirmation: bool = False,
    ) -> None:
        if self._is_task_queued(task.id, dry_run):
            return
        self.command_queue.append(
            {
                "kind": "task",
                "task_id": task.id,
                "dry_run": dry_run,
                "reason": reason,
                "scheduled_confirmation": scheduled_confirmation,
            }
        )
        if not silent:
            mode = "Проверка" if dry_run else "Синхронизация"
            self._append_log(f"{mode} задачи `{task.name}` добавлена в очередь.")
        self._start_next_queued_command()

    def _is_task_queued(self, task_id: str, dry_run: bool) -> bool:
        return any(
            item.get("kind") == "task"
            and item.get("task_id") == task_id
            and bool(item.get("dry_run")) == dry_run
            for item in self.command_queue
        )

    def _is_task_queued_any(self, task_id: str) -> bool:
        return any(
            item.get("kind") == "task" and item.get("task_id") == task_id
            for item in self.command_queue
        )

    def _remove_task_from_queue(self, task_id: str) -> int:
        before = len(self.command_queue)
        self.command_queue = [
            item
            for item in self.command_queue
            if not (item.get("kind") == "task" and item.get("task_id") == task_id)
        ]
        return before - len(self.command_queue)

    def _current_rclone_path(self, *, show_warnings: bool = True) -> str:
        rclone_path = self.rclone_path_edit.text().strip()
        if not rclone_path:
            if show_warnings:
                QMessageBox.warning(
                    self,
                    "Не найден rclone",
                    "Не удалось определить путь к `rclone.exe`.",
                )
            self.command_queue.clear()
            return ""
        if not Path(rclone_path).exists():
            if show_warnings:
                QMessageBox.warning(
                    self,
                    "rclone недоступен",
                    f"`rclone.exe` не найден:\n{rclone_path}",
                )
            self.command_queue.clear()
            return ""
        return rclone_path

    def _run_version(self) -> None:
        self._enqueue_diagnostic("version", ["version"], "Проверка версии rclone")

    def _run_config_file(self) -> None:
        self._enqueue_diagnostic(
            "config-file",
            ["config", "file"],
            "Путь к active rclone.conf",
        )

    def _startup_check_remotes(self) -> None:
        if self.runner.is_running or self.command_queue:
            return

        rclone_path = self._current_rclone_path(show_warnings=False)
        if not rclone_path:
            self.remote_status_label.setText("Remote: rclone недоступен")
            return

        result = list_configured_remotes(rclone_path, rclone_config_path())
        if not result.success:
            self.remote_status_label.setText("Remote: ошибка чтения конфига")
            self._append_log("Не удалось прочитать список remote при запуске.")
            return

        remote_names = parse_remote_list(result.output)
        if not remote_names:
            self.remote_status_label.setText("Remote: нет настроенных")
            return

        selected_remote = self.settings_store.get_selected_remote()
        if selected_remote not in remote_names:
            selected_remote = remote_names[0]
        self._set_remote_combo_items(remote_names, selected_remote)
        self._save_runtime_state()
        self._queue_remote_checks(remote_names)
        if self._runtime_checks_enabled() and not self._all_accounts_selected():
            self._request_remote_quota(selected_remote)

    def _refresh_remote_names_from_config(self) -> None:
        rclone_path = self._current_rclone_path()
        if not rclone_path:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = list_configured_remotes(rclone_path, rclone_config_path())
        finally:
            QApplication.restoreOverrideCursor()

        if not result.success:
            QMessageBox.warning(self, "Remote", result.summary)
            self._append_log("Не удалось обновить список remote из rclone.conf.")
            return

        remote_names = parse_remote_list(result.output)
        if not remote_names:
            QMessageBox.information(
                self,
                "Remote",
                "В текущем rclone.conf пока нет настроенных remote.",
            )
            return

        selected_remote = self._current_remote_name()
        if selected_remote not in remote_names:
            selected_remote = remote_names[0]
        self._set_remote_combo_items(remote_names, selected_remote)
        self._save_runtime_state()
        if self._runtime_checks_enabled() and not self._all_accounts_selected():
            self._request_remote_quota(selected_remote)
        self._append_log(f"Обновлён список remote: {', '.join(remote_names)}.")

    def _queue_remote_checks(self, remote_names: list[str]) -> None:
        normalized_names: list[str] = []
        for remote_name in remote_names:
            normalized = normalize_remote_name(remote_name)
            if is_valid_remote_name(normalized) and normalized not in normalized_names:
                normalized_names.append(normalized)
        if not normalized_names:
            return

        self._remote_check_total = len(normalized_names)
        self._remote_check_done = 0
        self._remote_check_failures = []
        for remote_name in normalized_names:
            remote = remote_prefix(remote_name)
            self._enqueue_diagnostic(
                "remote-batch-check",
                ["about", remote],
                f"Проверка remote {remote}",
                start_immediately=False,
            )
        self.remote_status_label.setText(
            f"Remote: проверка 0/{self._remote_check_total}"
        )
        self._start_next_queued_command()

    def _request_remote_quota(self, remote_name: str) -> None:
        normalized = normalize_remote_name(remote_name)
        if not is_valid_remote_name(normalized):
            self._set_quota_unavailable("Квота: —")
            return

        self._quota_remote_name = normalized
        self.remote_quota_bar.setRange(0, 0)
        self.remote_quota_bar.setFormat("Квота: проверка…")
        self._enqueue_diagnostic(
            "remote-quota",
            ["about", remote_prefix(normalized), "--json"],
            f"Квота remote {remote_prefix(normalized)}",
            start_immediately=False,
        )
        self._start_next_queued_command()

    def _set_quota_unavailable(self, text: str = "Квота: недоступна") -> None:
        self.remote_quota_bar.setRange(0, 1000)
        self.remote_quota_bar.setValue(0)
        self.remote_quota_bar.setFormat(text)

    def _handle_remote_quota_result(self, result: dict[str, object]) -> None:
        remote = self._diagnostic_remote_label(result).removesuffix(":")
        if self._all_accounts_selected() or remote != self._current_remote_name():
            return
        if not bool(result.get("success")):
            self._set_quota_unavailable("Квота: ошибка")
            return

        quota = self._parse_quota_output(str(result.get("output") or ""))
        if not quota:
            self._set_quota_unavailable("Квота: нет данных")
            return
        self._update_quota_bar(quota)

    def _parse_quota_output(self, output: str) -> dict[str, int] | None:
        text = output.strip()
        if not text:
            return None

        try:
            return self._normalize_quota_payload(json.loads(text))
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None

        try:
            return self._normalize_quota_payload(json.loads(text[start : end + 1]))
        except json.JSONDecodeError:
            return None

    def _normalize_quota_payload(self, payload: object) -> dict[str, int] | None:
        if not isinstance(payload, dict):
            return None
        quota = {
            key: int(value)
            for key, value in payload.items()
            if key in {"total", "used", "free", "trashed", "other"}
            and isinstance(value, int | float)
            and value >= 0
        }
        return quota or None

    def _update_quota_bar(self, quota: dict[str, int]) -> None:
        used = int(quota.get("used", 0))
        total = int(quota.get("total", 0))
        if total <= 0:
            self.remote_quota_bar.setRange(0, 1000)
            self.remote_quota_bar.setValue(0)
            self.remote_quota_bar.setFormat(f"Занято {self._format_bytes_gib(used)}")
            return

        percent_value = min(1000, max(0, round(used / total * 1000)))
        percent_text = round(used / total * 100)
        self.remote_quota_bar.setRange(0, 1000)
        self.remote_quota_bar.setValue(percent_value)
        self.remote_quota_bar.setFormat(
            f"{self._format_bytes_gib(used)} / {self._format_bytes_gib(total)} "
            f"({percent_text}%)"
        )

    def _format_bytes_gib(self, value: int) -> str:
        gib = max(0, value) / (1024**3)
        if gib >= 10:
            return f"{gib:.1f} ГБ"
        return f"{gib:.2f} ГБ"

    def _run_mega_check(self) -> None:
        if self._all_accounts_selected():
            self._queue_remote_checks(self.settings_store.get_remote_names())
            return
        remote_name = self._current_remote_name()
        if not remote_name:
            return
        remote = remote_prefix(remote_name)
        self._enqueue_diagnostic(
            "remote-lsd",
            ["lsd", remote],
            f"Проверка доступа к {remote}",
            start_immediately=False,
        )
        self._enqueue_diagnostic(
            "remote-about",
            ["about", remote],
            f"Проверка `rclone about {remote}`",
        )
        self.remote_status_label.setText(f"{remote} идёт проверка…")
        self._start_next_queued_command()

    def _enqueue_diagnostic(
        self,
        name: str,
        args: list[str],
        title: str,
        *,
        start_immediately: bool = True,
    ) -> None:
        self.command_queue.append(
            {
                "kind": "diagnostic",
                "name": name,
                "args": args,
                "title": title,
            }
        )
        if start_immediately:
            self._start_next_queued_command()

    def _start_next_queued_command(self) -> None:
        if self.runner.is_running or not self.command_queue:
            return

        item = self.command_queue.pop(0)
        rclone_path = self._current_rclone_path()
        if not rclone_path:
            return

        if item["kind"] == "diagnostic":
            self.runner.run_diagnostic(
                rclone_path,
                str(rclone_config_path()),
                str(item["name"]),
                list(item["args"]),  # type: ignore[arg-type]
                str(item["title"]),
            )
            return

        task = self._find_task(str(item["task_id"]))
        if not task:
            self._start_next_queued_command()
            return

        if not Path(task.source_path).exists():
            task.last_status = "Источник не найден"
            task.last_error = "Локальная папка не существует."
            self._append_log(
                f"Задача `{task.name}` пропущена: локальная папка не найдена."
            )
            self._save_runtime_state()
            self._refresh_table()
            self.command_queue.clear()
            return

        dry_run = bool(item["dry_run"])
        if dry_run and bool(item.get("scheduled_confirmation")):
            self._scheduled_confirmation_task_ids.add(task.id)
        task.last_run_started_at = datetime.now().isoformat(timespec="seconds")
        task.last_mode = "dry-run" if dry_run else "sync"
        task.last_status = "Выполняется"
        task.last_error = ""
        task.last_summary = str(item.get("reason") or "")
        self._current_task_id = task.id
        self._save_runtime_state()
        self._refresh_table()
        self._select_task_by_id(task.id)
        self.runner.run_task(rclone_path, str(rclone_config_path()), task, dry_run)

    def _on_command_started(self, meta: dict[str, object]) -> None:
        if meta.get("kind") == "diagnostic":
            self.status_label.setText(str(meta.get("title") or "Проверка rclone…"))
        else:
            mode = "Проверка" if meta.get("mode") == "dry-run" else "Синхронизация"
            self.status_label.setText(
                f"{mode}: {meta.get('task_name', 'Безымянная задача')}"
            )

    def _on_stats_updated(self, stats: dict[str, object]) -> None:
        parts: list[str] = []
        if stats.get("transfers") is not None:
            parts.append(f"Передач: {stats['transfers']}")
        if stats.get("checks") is not None:
            parts.append(f"Проверок: {stats['checks']}")
        if stats.get("errors") is not None:
            parts.append(f"Ошибок: {stats['errors']}")
        if stats.get("speed") is not None:
            parts.append(f"Скорость: {stats['speed']}")
        self.stats_label.setText(" | ".join(parts))

    def _on_command_finished(self, result: dict[str, object]) -> None:
        self.stats_label.setText("")

        if result.get("kind") == "diagnostic":
            self._handle_diagnostic_result(result)
            self._start_next_queued_command()
            return

        self._current_task_id = None
        self._handle_task_result(result)
        if not bool(result.get("success")) or bool(result.get("stopped_by_user")):
            self.command_queue.clear()
        self._start_next_queued_command()
        self._show_pending_confirmation_if_idle()

    def _handle_diagnostic_result(self, result: dict[str, object]) -> None:
        success = bool(result.get("success"))
        name = str(result.get("diagnostic_name") or "")
        summary = str(result.get("summary") or "")
        self.status_label.setText(summary)

        if name == "remote-quota":
            self._handle_remote_quota_result(result)
        elif name == "remote-batch-check":
            remote = self._diagnostic_remote_label(result)
            self._remote_check_done += 1
            if not success:
                self._remote_check_failures.append(remote)
            if self._remote_check_done >= self._remote_check_total:
                available = self._remote_check_total - len(self._remote_check_failures)
                self.remote_status_label.setText(
                    f"Remote: доступно {available}/{self._remote_check_total}"
                )
                if self._remote_check_failures:
                    self._append_log(
                        "Ошибки проверки remote: "
                        + ", ".join(self._remote_check_failures)
                    )
            else:
                self.remote_status_label.setText(
                    f"Remote: проверка {self._remote_check_done}/"
                    f"{self._remote_check_total}"
                )
        elif name.startswith("remote-"):
            remote = self._diagnostic_remote_label(result)
            self.remote_status_label.setText(
                f"{remote} доступен" if success else f"{remote} ошибка проверки"
            )

        if not success:
            self._append_log(
                f"Диагностика `{result.get('title', name)}` завершилась ошибкой."
            )

    def _diagnostic_remote_label(self, result: dict[str, object]) -> str:
        args = list(result.get("args") or [])
        for item in args:
            text = str(item)
            if text.endswith(":"):
                return text
        return "Remote:"

    def _handle_task_result(self, result: dict[str, object]) -> None:
        task = self._find_task(str(result.get("task_id")))
        if not task:
            return

        scheduled_confirmation = (
            task.id in self._scheduled_confirmation_task_ids
            and task.last_mode == "dry-run"
        )
        self._scheduled_confirmation_task_ids.discard(task.id)

        task.last_run_finished_at = datetime.now().isoformat(timespec="seconds")
        task.last_delete_candidates = int(result.get("delete_candidates") or 0)
        task.last_change_candidates = int(result.get("change_candidates") or 0)
        task.last_change_details = bounded_change_details(result.get("change_details"))
        task.last_error = ""
        task.last_summary = str(result.get("summary") or "")

        if bool(result.get("stopped_by_user")):
            task.last_status = "Остановлена пользователем"
        elif bool(result.get("success")):
            task.last_status = "Успешно"
            if task.last_mode == "dry-run":
                task.last_dry_run_at = task.last_run_finished_at
                if scheduled_confirmation:
                    if task.last_change_candidates > 0:
                        task.last_status = "Ожидает подтверждения"
                    else:
                        task.last_status = "Без изменений"
        else:
            task.last_status = "Ошибка"
            task.last_error = str(result.get("summary") or "")

        self.status_label.setText(f"{task.name}: {task.last_status}")
        self._save_runtime_state()
        self._refresh_table()
        self._select_task_by_id(task.id)

        if task.last_mode == "dry-run" and task.last_delete_candidates:
            self._append_log(
                f"Dry-run задачи `{task.name}` показал потенциальных удалений: "
                f"{task.last_delete_candidates}."
            )
        elif (
            task.last_mode == "dry-run"
            and bool(result.get("success"))
            and task.last_change_candidates == 0
        ):
            self._append_log(f"Dry-run задачи `{task.name}` не нашёл изменений.")

        if (
            scheduled_confirmation
            and bool(result.get("success"))
            and task.last_change_candidates > 0
        ):
            self._queue_pending_confirmation(task)

        if task.last_mode == "sync" and bool(result.get("success")):
            remote_name = remote_name_from_path(task.remote_path)
            if (
                self._runtime_checks_enabled()
                and remote_name == self._current_remote_name()
            ):
                self._request_remote_quota(remote_name)

    def _show_notification(self, title: str, message: str) -> None:
        if self.tray_icon and QSystemTrayIcon.supportsMessages():
            self.tray_icon.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                10_000,
            )

    def _queue_pending_confirmation(self, task: SyncTask) -> None:
        if task.id not in self._pending_confirmation_task_ids:
            self._pending_confirmation_task_ids.append(task.id)

    def _show_pending_confirmation_if_idle(self) -> None:
        if self.runner.is_running or self.command_queue:
            return

        tasks = [
            task
            for task_id in self._pending_confirmation_task_ids
            if (task := self._find_task(task_id)) is not None
            and task.last_status == "Ожидает подтверждения"
            and task.last_change_candidates > 0
        ]
        if not tasks:
            self._pending_confirmation_task_ids.clear()
            return

        message = (
            f"Проверка нашла изменения в задачах: {len(tasks)}. "
            "Нужно подтверждение для боевого зеркалирования."
        )
        self._append_log(message)
        self._show_notification("Rclone Mega", message)
        self._show_window_from_notification()

        action, selected_tasks = self._select_tasks_for_sync(tasks)
        self._pending_confirmation_task_ids = [
            task_id
            for task_id in self._pending_confirmation_task_ids
            if task_id not in {task.id for task in selected_tasks}
        ]

        if action == "defer":
            self._append_log("Зеркалирование отложено.")
            return
        if action == "pause":
            self._append_log(
                f"Интервал временно отключен для задач: {len(selected_tasks)}."
            )
            return
        if not selected_tasks:
            self._append_log("Зеркалирование отложено.")
            return

        for task in selected_tasks:
            self._enqueue_task(
                task,
                dry_run=False,
                reason="Подтверждённый sync после проверки",
                silent=True,
            )
        self._append_log(
            f"В очередь добавлено подтверждённых задач: {len(selected_tasks)}."
        )
        self._start_next_queued_command()

    def _select_tasks_for_sync(
        self, tasks: list[SyncTask]
    ) -> tuple[str, list[SyncTask]]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Подтвердите зеркалирование")
        layout = QVBoxLayout(dialog)

        scroll_area = QScrollArea(dialog)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll_area)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(
            "Dry-run нашёл изменения. Выберите задачи для боевого sync."
        )
        label.setWordWrap(True)
        content_layout.addWidget(label)

        checkboxes: list[tuple[QCheckBox, SyncTask]] = []
        for task in tasks:
            account = remote_name_from_path(task.remote_path)
            text = f"{task.name} ({account}): изменений {task.last_change_candidates}"
            if task.last_delete_candidates:
                text += f", удалений {task.last_delete_candidates}"
            if task.hard_delete and not (task.use_backup_dir and task.backup_dir):
                text += " — удаление безвозвратно"
            checkbox = QCheckBox(text)
            checkbox.setChecked(True)
            content_layout.addWidget(checkbox)
            checkboxes.append((checkbox, task))
            details_text = self._task_change_details_text(task)
            if details_text:
                details_label = QLabel(details_text)
                details_label.setWordWrap(True)
                details_label.setObjectName("mutedLabel")
                content_layout.addWidget(details_label)

        warning = QLabel(
            "Боевой `rclone sync` может удалить устаревшие файлы в MEGA."
        )
        warning.setWordWrap(True)
        warning.setObjectName("mutedLabel")
        content_layout.addWidget(warning)
        content_layout.addStretch()
        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)

        buttons = QDialogButtonBox()
        selected_button = buttons.addButton(
            "Зеркалировать выбранные", QDialogButtonBox.ButtonRole.AcceptRole
        )
        all_button = buttons.addButton(
            "Зеркалировать все", QDialogButtonBox.ButtonRole.AcceptRole
        )
        defer_button = buttons.addButton(
            "Отложить", QDialogButtonBox.ButtonRole.RejectRole
        )
        pause_button = buttons.addButton(
            "Отключить интервал", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        layout.addWidget(buttons)

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available_geometry = screen.availableGeometry()
            maximum_height = max(1, int(available_geometry.height() * 0.85))
            maximum_width = max(1, int(available_geometry.width() * 0.9))
            dialog.setMaximumHeight(maximum_height)
            dialog.setMaximumWidth(maximum_width)
            restored = self._restore_confirm_dialog_geometry(
                dialog, maximum_width, maximum_height
            )
            if not restored:
                dialog.resize(
                    min(720, maximum_width),
                    min(dialog.sizeHint().height(), maximum_height),
                )
        else:
            restored = self._restore_confirm_dialog_geometry(dialog, 720, 900)
            if not restored:
                dialog.resize(720, 560)

        clicked_button = None

        def remember_and_close(button) -> None:
            nonlocal clicked_button
            clicked_button = button
            dialog.accept()

        buttons.clicked.connect(remember_and_close)
        dialog.exec()
        self._save_confirm_dialog_geometry(dialog)

        if clicked_button == all_button:
            return "sync", list(tasks)
        if clicked_button == selected_button:
            return "sync", [task for checkbox, task in checkboxes if checkbox.isChecked()]
        if clicked_button == defer_button:
            self._defer_confirmation_tasks(tasks)
            return "defer", list(tasks)
        if clicked_button == pause_button:
            selected_tasks = [task for checkbox, task in checkboxes if checkbox.isChecked()]
            self._pause_interval_tasks(selected_tasks or tasks)
            return "pause", selected_tasks or list(tasks)
        return "defer", []

    def _task_change_details_text(self, task: SyncTask) -> str:
        if task.last_change_details:
            visible = [f"  {item}" for item in task.last_change_details[:12]]
            hidden_count = max(
                len(task.last_change_details), task.last_change_candidates
            ) - len(visible)
            if hidden_count > 0:
                visible.append(f"  ...ещё {hidden_count}")
            return "\n".join(visible)
        if task.last_change_candidates:
            return "  Детали изменений доступны в журнале dry-run."
        return ""

    def _append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if len(text) > MAX_LOG_MESSAGE_CHARS:
            text = text[:MAX_LOG_MESSAGE_CHARS] + " …[сообщение сокращено]"
        self.log_view.appendPlainText(f"[{timestamp}] {text}")
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_busy(self, busy: bool) -> None:
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
        self._update_action_buttons()
        self._refresh_table()

    def _stop_current_command(self) -> None:
        self.runner.stop()

    def _stop_task(self, task_id: str) -> None:
        removed = self._remove_task_from_queue(task_id)
        task = self._find_task(task_id)
        if self._current_task_id == task_id:
            self.runner.stop()
            if task:
                self._append_log(f"Останавливаю задачу `{task.name}`.")
        elif removed and task:
            self._append_log(f"Задача `{task.name}` удалена из очереди.")
        self._refresh_table()
        self._update_action_buttons()

    def _stop_all_commands(self) -> None:
        queued = len(self.command_queue)
        self.command_queue.clear()
        if self.runner.is_running:
            self.runner.stop()
        self._append_log(f"Остановка всех задач. Очередь очищена: {queued}.")
        self._refresh_table()
        self._update_action_buttons()

    def _defer_interval_tasks(self, tasks: list[SyncTask]) -> None:
        self._defer_confirmation_tasks(tasks)

    def _defer_confirmation_tasks(self, tasks: list[SyncTask]) -> None:
        for task in tasks:
            task.last_status = "Отложено"
        deferred_ids = {task.id for task in tasks}
        self._pending_confirmation_task_ids = [
            task_id
            for task_id in self._pending_confirmation_task_ids
            if task_id not in deferred_ids
        ]
        self._save_runtime_state()
        self._refresh_table()

    def _pause_interval_tasks(self, tasks: list[SyncTask]) -> None:
        for task in tasks:
            task.interval_paused = True
            task.last_status = "Интервал отключен"
        paused_ids = {task.id for task in tasks}
        self._pending_confirmation_task_ids = [
            task_id
            for task_id in self._pending_confirmation_task_ids
            if task_id not in paused_ids
        ]
        self._save_runtime_state()
        self._refresh_table()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.column() != 0:
            return

        task_id = str(item.data(Qt.ItemDataRole.UserRole))
        task = self._find_task(task_id)
        if not task:
            return

        task.enabled = item.checkState() == Qt.CheckState.Checked
        self._save_runtime_state()
        self._update_active_header_state()
        self._update_action_buttons()

    def _on_table_header_clicked(self, column: int) -> None:
        if 1 <= column <= 6:
            if column == self._task_sort_column:
                self._task_sort_order = (
                    Qt.SortOrder.DescendingOrder
                    if self._task_sort_order == Qt.SortOrder.AscendingOrder
                    else Qt.SortOrder.AscendingOrder
                )
            else:
                self._task_sort_column = column
                self._task_sort_order = Qt.SortOrder.AscendingOrder
            header = self.table.horizontalHeader()
            header.setSortIndicator(column, self._task_sort_order)
            header.setSortIndicatorShown(True)
            self._refresh_table()
            return

        visible_tasks = self._visible_tasks()
        if column != 0 or not visible_tasks:
            return

        enable_all = not all(task.enabled for task in visible_tasks)
        for task in visible_tasks:
            task.enabled = enable_all

        self._save_runtime_state()
        self._refresh_table()
        action = "включены" if enable_all else "отключены"
        self._append_log(f"Все задачи в текущем списке {action}.")

    def _update_active_header_state(self) -> None:
        header_item = self.table.horizontalHeaderItem(0)
        if not header_item:
            return

        visible_tasks = self._visible_tasks()
        if not visible_tasks or not any(task.enabled for task in visible_tasks):
            header_item.setText("☐")
            header_item.setToolTip("Включить все задачи в текущем списке")
        elif all(task.enabled for task in visible_tasks):
            header_item.setText("☑")
            header_item.setToolTip("Отключить все задачи в текущем списке")
        else:
            header_item.setText("◩")
            header_item.setToolTip(
                "Часть задач в текущем списке включена. Нажмите, чтобы включить все."
            )

    def _check_due_tasks(self) -> None:
        if self.runner.is_running:
            return

        now = datetime.now()
        due_tasks = []
        for task in self.tasks:
            if not task.enabled or task.interval_minutes <= 0:
                continue
            if task.interval_paused:
                continue
            if task.last_status == "Ожидает подтверждения":
                continue
            if not task.last_run_finished_at and not task.last_dry_run_at:
                continue

            due_at = task.due_run_at()
            if due_at and due_at <= now:
                due_tasks.append(task)

        for task in due_tasks:
            self._enqueue_task(
                task,
                dry_run=True,
                reason="Плановая проверка по интервалу",
                silent=True,
                scheduled_confirmation=True,
            )

        if due_tasks:
            self._append_log(
                f"Планировщик добавил в очередь задач: {len(due_tasks)}."
            )

    def nativeEvent(self, event_type, message):
        if sys.platform != "win32":
            return super().nativeEvent(event_type, message)

        msg = ctypes.wintypes.MSG.from_address(int(message))
        if (
            msg.message in {self.WM_NCRBUTTONDOWN, self.WM_NCRBUTTONUP}
            and msg.wParam == self.HTCLOSE
        ):
            if msg.message == self.WM_NCRBUTTONUP:
                self.hide_to_tray()
            return True, 0

        return super().nativeEvent(event_type, message)

    def _schedule_geometry_save(self) -> None:
        timer = getattr(self, "_geometry_save_timer", None)
        if timer is not None:
            timer.start()

    def moveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().moveEvent(event)
        self._schedule_geometry_save()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._schedule_geometry_save()

    def closeEvent(self, event) -> None:
        if self.runner.is_running:
            answer = QMessageBox.question(
                self,
                "Закрытие приложения",
                "Сейчас выполняется команда rclone. Остановить её и закрыть приложение?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.command_queue.clear()
            self.runner.stop()

        self._save_geometry()
        super().closeEvent(event)
