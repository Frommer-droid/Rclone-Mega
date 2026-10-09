# -*- coding: utf-8 -*-
"""Запуск команд rclone через QProcess."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from app.core.app_config import app_root
from app.core.memory_limits import (
    MAX_CHANGE_DETAILS,
    MAX_CHANGE_DETAIL_CHARS,
    MAX_DIAGNOSTIC_CHARS,
    MAX_OUTPUT_LINE_CHARS,
    bounded_change_details,
)
from app.models.sync_task import SyncTask


DEFAULT_EXCLUDES = (
    "__pycache__/**",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".mypy_cache/**",
    "Thumbs.db",
    ".DS_Store",
    "*.tmp",
    "*.temp",
    "*.swp",
    "~$*",
)


def with_config_args(args: list[str], config_path: str) -> list[str]:
    return ["--config", config_path, *args]


def _exclude_to_filter_rule(pattern: str) -> str:
    return f"- {pattern}"


def _needs_implicit_exclude_all(filter_rules: list[str]) -> bool:
    return bool(filter_rules) and all(rule.startswith("+ ") for rule in filter_rules)


def build_sync_args(task: SyncTask, dry_run: bool) -> list[str]:
    args = [
        "sync",
        task.source_path,
        task.remote_path,
        "--use-json-log",
        "--log-level",
        "INFO",
        "--stats",
        "1s",
        "--max-delete",
        str(task.max_delete),
        f"--mega-hard-delete={str(task.hard_delete).lower()}",
    ]

    if dry_run:
        args.append("--dry-run")
        args.extend(["--combined", "-"])

    if task.use_backup_dir and task.backup_dir:
        args.extend(["--backup-dir", task.backup_dir])

    # Встроенные исключения имеют приоритет над разрешающими правилами задачи.
    for pattern in dict.fromkeys((*DEFAULT_EXCLUDES, *task.excludes)):
        args.extend(["--filter", _exclude_to_filter_rule(pattern)])

    if task.filter_rules:
        for rule in task.filter_rules:
            args.extend(["--filter", rule])
        if _needs_implicit_exclude_all(task.filter_rules):
            args.extend(["--filter", "- /**"])
    return args


class RcloneRunner(QObject):
    command_started = Signal(object)
    command_output = Signal(str)
    stats_updated = Signal(object)
    command_finished = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(app_root()))
        self.process.started.connect(self._on_started)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)

        self._current_meta: dict[str, Any] | None = None
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._raw_output_lines: list[str] = []
        self._raw_output_chars = 0
        self._output_truncated = False
        self._discard_stdout_line = False
        self._discard_stderr_line = False
        self._last_stats: dict[str, Any] = {}
        self._error_count = 0
        self._delete_candidates = 0
        self._change_candidates = 0
        self._combined_change_candidates = 0
        self._combined_delete_candidates = 0
        self._change_details: dict[str, list[str]] = {}
        self._stop_requested = False
        self._terminal_emitted = False
        self._last_error_message = ""

    @property
    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def run_task(
        self, rclone_path: str, config_path: str, task: SyncTask, dry_run: bool
    ) -> bool:
        mode = "dry-run" if dry_run else "sync"
        return self._start(
            rclone_path,
            with_config_args(build_sync_args(task, dry_run), config_path),
            {
                "kind": "task",
                "task_id": task.id,
                "task_name": task.name,
                "mode": mode,
                "source_path": task.source_path,
                "remote_path": task.remote_path,
            },
        )

    def run_diagnostic(
        self,
        rclone_path: str,
        config_path: str,
        name: str,
        args: list[str],
        title: str,
    ) -> bool:
        return self._start(
            rclone_path,
            with_config_args(args, config_path),
            {
                "kind": "diagnostic",
                "diagnostic_name": name,
                "title": title,
                "mode": name,
            },
        )

    def stop(self) -> None:
        if not self.is_running:
            return
        self._stop_requested = True
        self.command_output.emit("Останавливаю текущий процесс rclone...")
        self.process.terminate()
        QTimer.singleShot(3000, self._kill_if_needed)

    def _kill_if_needed(self) -> None:
        if self.is_running:
            self.process.kill()

    def _start(
        self, rclone_path: str, args: list[str], meta: dict[str, Any]
    ) -> bool:
        if self.is_running:
            return False

        self._current_meta = {**meta, "rclone_path": rclone_path, "args": list(args)}
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._raw_output_lines = []
        self._raw_output_chars = 0
        self._output_truncated = False
        self._discard_stdout_line = False
        self._discard_stderr_line = False
        self._last_stats = {}
        self._error_count = 0
        self._delete_candidates = 0
        self._change_candidates = 0
        self._combined_change_candidates = 0
        self._combined_delete_candidates = 0
        self._change_details = {}
        self._stop_requested = False
        self._terminal_emitted = False
        self._last_error_message = ""
        self.process.setWorkingDirectory(str(app_root()))
        self.process.start(rclone_path, args)
        self.busy_changed.emit(True)
        return True

    def _on_started(self) -> None:
        if not self._current_meta:
            return
        self.command_started.emit(dict(self._current_meta))
        command_text = " ".join(
            [self._current_meta["rclone_path"], *self._current_meta["args"]]
        )
        self.command_output.emit(f"Запуск: {command_text}")

    def _read_stdout(self) -> None:
        self._consume_output(
            bytes(self.process.readAllStandardOutput()).decode(
                "utf-8", errors="replace"
            ),
            is_error=False,
        )

    def _read_stderr(self) -> None:
        self._consume_output(
            bytes(self.process.readAllStandardError()).decode(
                "utf-8", errors="replace"
            ),
            is_error=True,
        )

    def _consume_output(self, chunk: str, *, is_error: bool) -> None:
        if not chunk:
            return

        buffer_name = "_stderr_buffer" if is_error else "_stdout_buffer"
        discard_name = "_discard_stderr_line" if is_error else "_discard_stdout_line"
        if getattr(self, discard_name):
            # Не интерпретировать хвост слишком длинной строки как новую запись.
            _discarded, separator, chunk = chunk.partition("\n")
            if not separator:
                return
            setattr(self, discard_name, False)
        current = getattr(self, buffer_name) + chunk
        lines = current.splitlines(keepends=True)

        tail = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            tail = lines.pop()

        if len(tail) > MAX_OUTPUT_LINE_CHARS:
            tail = ""
            setattr(self, discard_name, True)
            self._mark_output_truncated()
        setattr(self, buffer_name, tail)

        for line in lines:
            if len(line) > MAX_OUTPUT_LINE_CHARS:
                self._mark_output_truncated()
            else:
                self._handle_line(line.rstrip("\r\n"), is_error=is_error)

    def _mark_output_truncated(self) -> None:
        if not self._output_truncated:
            self._output_truncated = True
            self._error_count += 1
            self.command_output.emit(
                "[ERROR] Вывод rclone превысил безопасный предел. "
                "Результат команды будет отмечен как неполный."
            )

    def _flush_buffers(self) -> None:
        if self._stdout_buffer:
            self._handle_line(self._stdout_buffer, is_error=False)
            self._stdout_buffer = ""
        if self._stderr_buffer:
            self._handle_line(self._stderr_buffer, is_error=True)
            self._stderr_buffer = ""

    def _handle_line(self, line: str, *, is_error: bool) -> None:
        text = line.strip()
        if not text:
            return
        if self._current_meta and self._current_meta.get("kind") == "diagnostic":
            if self._raw_output_chars + len(text) + 1 <= MAX_DIAGNOSTIC_CHARS:
                self._raw_output_lines.append(text)
                self._raw_output_chars += len(text) + 1
            else:
                self._mark_output_truncated()
            if self._current_meta.get("diagnostic_name") == "remote-quota":
                return
        if self._is_combined_equal_line(text):
            return

        combined_change = self._parse_combined_change(text)
        if combined_change:
            object_name, detail = combined_change
            self._combined_change_candidates += 1
            if text.startswith("- "):
                self._combined_delete_candidates += 1
            self._add_change_detail(object_name, detail)
            self.command_output.emit(f"[DRY-RUN] {object_name}: {detail}")
            return

        event = self._parse_line(text)
        if event["kind"] == "stats":
            self._last_stats = event["stats"]
            self.stats_updated.emit(event["stats"])
            return

        if event["kind"] == "log":
            level = str(event.get("level") or ("ERROR" if is_error else "INFO")).upper()
            message = str(event.get("message") or "")
            object_name = str(event.get("object_name") or "")
            combined = f"{message} {object_name}".lower()
            if level in {"ERROR", "FATAL"}:
                self._error_count += 1
            if "delete" in combined or "deleted" in combined or "удал" in combined:
                self._delete_candidates += 1
            if self._is_dry_run_change(combined):
                self._change_candidates += 1
                self._add_change_detail(
                    object_name,
                    self._detail_from_log_event(event),
                )

            rendered = f"[{level}] {message}".strip()
            if object_name:
                rendered = f"{rendered} [{object_name}]"
            self.command_output.emit(rendered)
            return

        if is_error:
            self._error_count += 1
            self.command_output.emit(f"[STDERR] {text}")
        else:
            if self._is_dry_run_change(text.lower()):
                self._change_candidates += 1
            self.command_output.emit(text)

    def _is_combined_equal_line(self, text: str) -> bool:
        return (
            bool(self._current_meta)
            and self._current_meta.get("mode") == "dry-run"
            and len(text) >= 3
            and text[0] == "="
            and text[1] == " "
        )

    def _parse_combined_change(self, text: str) -> tuple[str, str] | None:
        if not self._current_meta or self._current_meta.get("mode") != "dry-run":
            return None
        if len(text) < 3 or text[1] != " ":
            return None

        marker = text[0]
        object_name = text[2:].strip()
        if not object_name:
            return None
        if self._is_progress_status_path(object_name):
            return None

        details = {
            "*": "отличается от облака",
            "+": "есть локально, отсутствует в облаке",
            "-": "есть в облаке, будет удалён при зеркалировании",
            "!": "ошибка сравнения",
        }
        detail = details.get(marker)
        if not detail:
            return None
        return object_name, detail

    def _is_progress_status_path(self, object_name: str) -> bool:
        normalized = object_name.strip().lower()
        return normalized.endswith(
            (
                ": checking",
                ": transferring",
                ": deleting",
                ": renamed",
                ": moving",
            )
        )

    def _detail_from_log_event(self, event: dict[str, Any]) -> str:
        skipped = str(event.get("skipped") or "").lower()
        message = str(event.get("message") or "").strip()
        normalized_message = message.lower()
        size = event.get("size")
        size_text = f", размер {size} байт" if isinstance(size, int) and size > 0 else ""

        if skipped == "copy" or "skipped copy as --dry-run" in normalized_message:
            return f"будет скопирован{size_text}"
        if skipped == "delete" or "skipped delete as --dry-run" in normalized_message:
            return "будет удалён"
        if skipped == "update" or "skipped update as --dry-run" in normalized_message:
            return f"будет обновлён{size_text}"
        if skipped == "move" or "skipped move as --dry-run" in normalized_message:
            return "будет перемещён"
        if skipped == "mkdir" or "skipped mkdir as --dry-run" in normalized_message:
            return "будет создана папка"
        if skipped == "rmdir" or "skipped rmdir as --dry-run" in normalized_message:
            return "будет удалена папка"
        if message:
            return message
        return "изменение dry-run"

    def _add_change_detail(self, object_name: str, detail: str) -> None:
        if not object_name or not detail:
            return
        object_name = object_name[:MAX_CHANGE_DETAIL_CHARS]
        detail = detail[:MAX_CHANGE_DETAIL_CHARS]
        if object_name not in self._change_details and len(self._change_details) >= MAX_CHANGE_DETAILS:
            return
        details = self._change_details.setdefault(object_name, [])
        if detail not in details and len(details) < 4:
            details.append(detail)

    def _change_details_list(self) -> list[str]:
        return bounded_change_details([
            f"{object_name}: {'; '.join(details)}"
            for object_name, details in self._change_details.items()
        ])

    def _stats_change_count(self) -> int | None:
        if not self._last_stats:
            return None

        keys = (
            "transfers",
            "deletes",
            "deletedDirs",
            "renames",
            "serverSideCopies",
            "serverSideMoves",
        )
        total = 0
        for key in keys:
            value = self._last_stats.get(key, 0)
            if isinstance(value, int | float):
                total += int(value)
        return max(0, total)

    def _stats_delete_count(self) -> int | None:
        if not self._last_stats:
            return None

        total = 0
        for key in ("deletes", "deletedDirs"):
            value = self._last_stats.get(key, 0)
            if isinstance(value, int | float):
                total += int(value)
        return max(0, total)

    def _is_dry_run_change(self, text: str) -> bool:
        if not self._current_meta or self._current_meta.get("mode") != "dry-run":
            return False

        return any(
            marker in text
            for marker in (
                "would ",
                "skipped copy as --dry-run",
                "skipped update as --dry-run",
                "skipped delete as --dry-run",
                "skipped move as --dry-run",
                "skipped mkdir as --dry-run",
                "skipped rmdir as --dry-run",
                "удал",
            )
        )

    def _parse_line(self, line: str) -> dict[str, Any]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return {"kind": "raw", "text": line}

        stats = payload.get("stats")
        if isinstance(stats, dict):
            return {"kind": "stats", "stats": stats}

        return {
            "kind": "log",
            "level": payload.get("level") or payload.get("severity") or "",
            "message": payload.get("msg") or payload.get("message") or line,
            "object_name": payload.get("object") or payload.get("path") or "",
            "skipped": payload.get("skipped") or "",
            "size": payload.get("size"),
        }

    def _on_error(self, error: QProcess.ProcessError) -> None:
        self._last_error_message = self.process.errorString()
        self.command_output.emit(f"Ошибка запуска процесса: {self._last_error_message}")

        if (
            error == QProcess.ProcessError.FailedToStart
            and self._current_meta
            and not self._terminal_emitted
        ):
            self._emit_finished(exit_code=-1, crashed=False)

    def _on_finished(
        self, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        if self._terminal_emitted:
            return
        self._emit_finished(
            exit_code=exit_code,
            crashed=exit_status == QProcess.ExitStatus.CrashExit,
        )

    def _emit_finished(self, *, exit_code: int, crashed: bool) -> None:
        self._terminal_emitted = True
        self._flush_buffers()

        meta = dict(self._current_meta or {})
        success = (
            exit_code == 0 and not crashed
            and not self._stop_requested and not self._output_truncated
        )
        if self._stop_requested:
            summary = "Остановлено пользователем."
        elif self._output_truncated:
            summary = "Вывод rclone превысил безопасный предел; результат неполный."
        elif success:
            summary = "Команда завершилась успешно."
        elif self._last_error_message:
            summary = self._last_error_message
        else:
            summary = f"Команда завершилась с кодом {exit_code}."

        parsed_delete_candidates = max(
            self._delete_candidates,
            self._combined_delete_candidates,
            sum(
                1
                for details in self._change_details.values()
                if any("будет удал" in detail for detail in details)
            ),
        )
        parsed_change_candidates = max(
            self._change_candidates,
            self._combined_change_candidates,
            len(self._change_details),
        )
        if meta.get("mode") == "dry-run":
            stats_change_count = self._stats_change_count()
            stats_delete_count = self._stats_delete_count()
            if stats_change_count is not None:
                parsed_change_candidates = stats_change_count
                if stats_change_count == 0:
                    self._change_details = {}
            if stats_delete_count is not None:
                parsed_delete_candidates = stats_delete_count

        result = {
            **meta,
            "success": success,
            "exit_code": exit_code,
            "crashed": crashed,
            "stopped_by_user": self._stop_requested,
            "error_count": self._error_count,
            "delete_candidates": parsed_delete_candidates,
            "change_candidates": parsed_change_candidates,
            "change_details": self._change_details_list(),
            "last_stats": dict(self._last_stats),
            "output": "\n".join(self._raw_output_lines),
            "output_truncated": self._output_truncated,
            "summary": summary,
        }

        # Итог содержит отдельные копии; не удерживать прошлый вывод в idle.
        self._raw_output_lines = []
        self._raw_output_chars = 0
        self._change_details = {}
        self._last_stats = {}

        self._current_meta = None
        # Сначала переводим runner в idle, затем сообщаем о завершении.
        # Это позволяет обработчику завершения безопасно запустить следующую
        # задачу без риска, что состояние новой команды будет затёрто хвостом
        # предыдущей.
        self.busy_changed.emit(False)
        self.command_finished.emit(result)
