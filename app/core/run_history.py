"""Persistent reports for individual task runs; output streams directly to disk."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.core.app_config import APP_VERSION


class RunHistory:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.active: dict | None = None
        self.failure = ""

    def _directory(self, task_id: str) -> Path:
        return self.root / hashlib.sha256(task_id.encode()).hexdigest()[:24]

    def _save(self, record: dict) -> None:
        path = self._directory(record["task_id"]) / f"{record['run_id']}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    def start(
        self, task, mode: str, reason: str, executable: str, args: list[str]
    ) -> None:
        self.failure = ""
        now = datetime.now().astimezone()
        record = {
            "run_id": now.strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid4().hex[:8],
            "task_id": task.id,
            "task_name": task.name,
            "source_path": task.source_path,
            "remote_path": task.remote_path,
            "started_at": now.isoformat(timespec="seconds"),
            "finished_at": "",
            "mode": mode,
            "reason": reason,
            "status": "Выполняется",
            "summary": "",
            "app_version": APP_VERSION,
            "command": subprocess.list2cmdline([executable, *args]),
        }
        self.active = record
        try:
            self._directory(task.id).mkdir(parents=True, exist_ok=True)
            self._save(record)
            self.append("Запуск: " + record["command"])
        except OSError as exc:
            self.failure = str(exc)

    def append(self, line: str) -> None:
        if self.active is None or self.failure:
            return
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if isinstance(event, dict) and "msg" in event:
            message = str(event["msg"])
            if event.get("object"):
                message += f" [{event['object']}]"
            if event.get("stats"):
                message += " " + json.dumps(event["stats"], ensure_ascii=False)
            line = f"[{str(event.get('level', 'INFO')).upper()}] {message}"
        try:
            path = self._directory(self.active["task_id"])
            with (path / f"{self.active['run_id']}.log").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(
                    f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {line}\n"
                )
        except OSError as exc:
            self.failure = str(exc)

    def finish(self, result: dict, status: str) -> None:
        if self.active is None:
            return
        record = self.active
        record.update(
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            status=status,
        )
        for key in (
            "summary",
            "exit_code",
            "crashed",
            "stopped_by_user",
            "error_count",
            "last_stats",
            "output_truncated",
            "change_candidates",
            "delete_candidates",
        ):
            record[key] = result.get(key)
        record["history_error"] = self.failure
        self.append(f"Итог: {status}. {result.get('summary', '')}")
        record["history_error"] = self.failure
        try:
            self._save(record)
        except OSError as exc:
            self.failure = str(exc)
        finally:
            self.active = None

    def records(self, task_id: str, limit: int | None = None) -> list[dict]:
        records = []
        for path in sorted(self._directory(task_id).glob("*.json"), reverse=True):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or record.get("task_id") != task_id:
                    continue
                required = (
                    "run_id",
                    "task_name",
                    "mode",
                    "status",
                    "started_at",
                    "source_path",
                    "remote_path",
                    "app_version",
                    "command",
                )
                if any(not isinstance(record.get(key), str) for key in required):
                    continue
                if record.get("run_id") != path.stem:
                    continue
                if record.get("status") == "Выполняется" and (
                    self.active is None or self.active["run_id"] != record["run_id"]
                ):
                    record["status"] = "Прервано: результат не сохранён"
                records.append(record)
                if limit is not None and len(records) >= limit:
                    break
            except (OSError, ValueError):
                continue
        return records

    def log_path(self, record: dict) -> Path:
        return self._directory(record["task_id"]) / f"{record['run_id']}.log"

    @staticmethod
    def display_time(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M:%S")
        except ValueError:
            return value

    @staticmethod
    def header(record: dict) -> str:
        mode = "Проверка" if record["mode"] == "dry-run" else "Синхронизация"
        fields = [
            ("Задача", record["task_name"]),
            ("Начало", record["started_at"]),
            ("Окончание", record.get("finished_at") or "Не зафиксировано"),
            ("Режим", mode),
            ("Причина запуска", record.get("reason", "")),
            ("Статус", record["status"]),
            ("Итог", record.get("summary", "")),
            ("Код завершения", record.get("exit_code", "Не зафиксирован")),
            ("Сообщений об ошибках", record.get("error_count", "")),
            ("Источник", record["source_path"]),
            ("Назначение", record["remote_path"]),
            ("Версия приложения", record["app_version"]),
            ("Команда", record["command"]),
            (
                "Статистика",
                json.dumps(record.get("last_stats") or {}, ensure_ascii=False),
            ),
        ]
        if record.get("output_truncated"):
            fields.append(("Предупреждение", "rclone сообщил о сокращении вывода"))
        if record.get("history_error"):
            fields.append(("Ошибка записи истории", record["history_error"]))
        return "\n".join(f"{label}: {value}" for label, value in fields)

    def preview(self, record: dict) -> str:
        path = self.log_path(record)
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - 256_000))
            data = stream.read().decode("utf-8", errors="replace")
        note = (
            "[Показан конец журнала. Экспорт содержит полный вывод.]\n"
            if size > 256_000
            else ""
        )
        return self.header(record) + "\n\n" + note + data

    @staticmethod
    def filename(record: dict, extension: str) -> str:
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", record["task_name"]).strip(" .")
        return f"{name[:80] or 'task'}_{record['run_id']}.{extension}"

    def export(self, record: dict, destination: Path, markdown: bool) -> None:
        source = self.log_path(record)
        if destination.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Выберите файл вне внутренней истории запусков.")
        # Open source first: a missing report must not truncate an existing export.
        with source.open("r", encoding="utf-8") as incoming:
            with destination.open("w", encoding="utf-8", newline="\n") as outgoing:
                if markdown:
                    outgoing.write("# Отчёт о запуске\n\n")
                    # Indentation keeps arbitrary filenames/output out of Markdown syntax.
                    for line in self.header(record).splitlines():
                        outgoing.write("    " + line + "\n")
                    outgoing.write("\n## Вывод rclone\n\n")
                    for line in incoming:
                        outgoing.write("    " + line)
                else:
                    outgoing.write(self.header(record) + "\n\nВывод rclone:\n\n")
                    shutil.copyfileobj(incoming, outgoing)
