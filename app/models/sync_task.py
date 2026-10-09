# -*- coding: utf-8 -*-
"""Модель задачи синхронизации."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from uuid import uuid4

from app.core.memory_limits import bounded_change_details


def _normalize_patterns(items: list[str]) -> list[str]:
    return [item.strip() for item in items if item and item.strip()]


def _normalize_filter_rules(items: list[str]) -> list[str]:
    return [
        item.strip()
        for item in items
        if item and item.strip() and not item.strip().startswith(("#", ";"))
    ]


def _normalize_max_delete(value: object, default: int = 20) -> int:
    if value is None or value == "":
        return default
    return max(-1, int(value))


def _normalize_scheduled_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = time.fromisoformat(text)
    except ValueError:
        return ""
    return parsed.strftime("%H:%M")


def format_timestamp(value: str) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%d.%m.%Y %H:%M")


@dataclass(slots=True)
class SyncTask:
    id: str
    name: str
    source_path: str
    remote_path: str
    enabled: bool = True
    dry_run_first: bool = True
    max_delete: int = 20
    hard_delete: bool = False
    use_backup_dir: bool = False
    backup_dir: str = ""
    excludes: list[str] = field(default_factory=list)
    filter_rules: list[str] = field(default_factory=list)
    interval_minutes: int = 0
    interval_paused: bool = False
    scheduled_time: str = ""
    last_run_started_at: str = ""
    last_run_finished_at: str = ""
    last_status: str = "Не запускалась"
    last_mode: str = ""
    last_error: str = ""
    last_summary: str = ""
    last_dry_run_at: str = ""
    last_delete_candidates: int = 0
    last_change_candidates: int = 0
    last_change_details: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source_path: str,
        remote_path: str,
        enabled: bool = True,
        dry_run_first: bool = True,
        max_delete: int = 20,
        hard_delete: bool = False,
        use_backup_dir: bool = False,
        backup_dir: str = "",
        excludes: list[str] | None = None,
        filter_rules: list[str] | None = None,
        interval_minutes: int = 0,
        interval_paused: bool = False,
        scheduled_time: str = "",
    ) -> "SyncTask":
        return cls(
            id=uuid4().hex,
            name=name.strip(),
            source_path=source_path.strip(),
            remote_path=remote_path.strip(),
            enabled=enabled,
            dry_run_first=dry_run_first,
            max_delete=_normalize_max_delete(max_delete),
            hard_delete=hard_delete,
            use_backup_dir=use_backup_dir,
            backup_dir=backup_dir.strip(),
            excludes=_normalize_patterns(excludes or []),
            filter_rules=_normalize_filter_rules(filter_rules or []),
            interval_minutes=max(0, int(interval_minutes)),
            interval_paused=interval_paused,
            scheduled_time=_normalize_scheduled_time(scheduled_time),
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SyncTask":
        return cls(
            id=str(data.get("id") or uuid4().hex),
            name=str(data.get("name") or "").strip(),
            source_path=str(data.get("source_path") or "").strip(),
            remote_path=str(data.get("remote_path") or "").strip(),
            enabled=bool(data.get("enabled", True)),
            dry_run_first=bool(data.get("dry_run_first", True)),
            max_delete=_normalize_max_delete(data.get("max_delete", 20)),
            hard_delete=bool(data.get("hard_delete", False)),
            use_backup_dir=bool(data.get("use_backup_dir", False)),
            backup_dir=str(data.get("backup_dir") or "").strip(),
            excludes=_normalize_patterns(
                list(data.get("excludes") or [])  # type: ignore[arg-type]
            ),
            filter_rules=_normalize_filter_rules(
                list(data.get("filter_rules") or [])  # type: ignore[arg-type]
            ),
            interval_minutes=max(0, int(data.get("interval_minutes", 0) or 0)),
            interval_paused=bool(data.get("interval_paused", False)),
            scheduled_time=_normalize_scheduled_time(data.get("scheduled_time", "")),
            last_run_started_at=str(data.get("last_run_started_at") or ""),
            last_run_finished_at=str(data.get("last_run_finished_at") or ""),
            last_status=str(data.get("last_status") or "Не запускалась"),
            last_mode=str(data.get("last_mode") or ""),
            last_error=str(data.get("last_error") or ""),
            last_summary=str(data.get("last_summary") or ""),
            last_dry_run_at=str(data.get("last_dry_run_at") or ""),
            last_delete_candidates=max(
                0, int(data.get("last_delete_candidates", 0) or 0)
            ),
            last_change_candidates=max(
                0, int(data.get("last_change_candidates", 0) or 0)
            ),
            last_change_details=bounded_change_details(data.get("last_change_details")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "source_path": self.source_path,
            "remote_path": self.remote_path,
            "enabled": self.enabled,
            "dry_run_first": self.dry_run_first,
            "max_delete": self.max_delete,
            "hard_delete": self.hard_delete,
            "use_backup_dir": self.use_backup_dir,
            "backup_dir": self.backup_dir,
            "excludes": list(self.excludes),
            "filter_rules": list(self.filter_rules),
            "interval_minutes": self.interval_minutes,
            "interval_paused": self.interval_paused,
            "scheduled_time": self.scheduled_time,
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "last_status": self.last_status,
            "last_mode": self.last_mode,
            "last_error": self.last_error,
            "last_summary": self.last_summary,
            "last_dry_run_at": self.last_dry_run_at,
            "last_delete_candidates": self.last_delete_candidates,
            "last_change_candidates": self.last_change_candidates,
            "last_change_details": bounded_change_details(self.last_change_details),
        }

    def reset_runtime_state(self) -> None:
        self.last_run_started_at = ""
        self.last_run_finished_at = ""
        self.last_status = "Требуется проверка"
        self.last_mode = ""
        self.last_error = ""
        self.last_summary = ""
        self.last_dry_run_at = ""
        self.last_delete_candidates = 0
        self.last_change_candidates = 0
        self.last_change_details = []

    def needs_first_dry_run(self) -> bool:
        return self.dry_run_first and not self.last_dry_run_at

    def interval_label(self) -> str:
        if self.interval_minutes <= 0:
            return "Вручную"

        days, remainder = divmod(self.interval_minutes, 24 * 60)
        hours, minutes = divmod(remainder, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days} д.")
        if hours:
            parts.append(f"{hours} ч.")
        if minutes or not parts:
            parts.append(f"{minutes} мин.")
        label = "Каждые " + " ".join(parts)
        if self.interval_paused:
            return f"Отключен временно ({label})"
        if self.scheduled_time:
            return f"{label}, от {self.scheduled_time}"
        return label

    def last_run_label(self) -> str:
        return format_timestamp(self.last_run_finished_at or self.last_run_started_at)

    def _latest_schedule_basis(self) -> datetime | None:
        basis = self.last_run_finished_at or self.last_dry_run_at
        if not basis:
            return None
        try:
            return datetime.fromisoformat(basis)
        except ValueError:
            return None

    def due_run_at(self) -> datetime | None:
        if self.interval_minutes <= 0:
            return None
        basis = self._latest_schedule_basis()
        if not basis:
            return None

        interval = timedelta(minutes=self.interval_minutes)
        if self.scheduled_time:
            scheduled = _normalize_scheduled_time(self.scheduled_time)
            if scheduled:
                hour, minute = (int(part) for part in scheduled.split(":", 1))
                candidate = datetime.combine(basis.date(), time(hour, minute))
                while candidate <= basis:
                    candidate += interval
                return candidate

        return basis + interval

    def next_run_at(self, now: datetime | None = None) -> datetime | None:
        due_at = self.due_run_at()
        if due_at is None:
            return None
        now = now or datetime.now()
        if due_at > now or not self.scheduled_time:
            return due_at

        interval = timedelta(minutes=self.interval_minutes)
        next_at = due_at
        while next_at <= now:
            next_at += interval
        return next_at

    def next_run_label(self, now: datetime | None = None) -> str:
        if not self.enabled:
            return "Отключена"
        if self.interval_minutes <= 0:
            return "Вручную"
        if self.interval_paused:
            return "Пауза"
        if self.last_status == "Ожидает подтверждения":
            return "Ждёт подтверждения"
        if not self._latest_schedule_basis():
            return "После первой проверки"

        now = now or datetime.now()
        due_at = self.due_run_at()
        if due_at and due_at <= now:
            return "Сейчас"
        next_at = self.next_run_at(now)
        return next_at.strftime("%d.%m.%Y %H:%M") if next_at else "—"

    def mode_label(self) -> str:
        if self.last_mode == "dry-run":
            return "Проверка"
        if self.last_mode == "sync":
            return "Синхронизация"
        return "—"

    def operational_signature(self) -> tuple[object, ...]:
        return (
            self.name,
            self.source_path,
            self.remote_path,
            self.dry_run_first,
            self.max_delete,
            self.hard_delete,
            self.use_backup_dir,
            self.backup_dir,
            tuple(self.excludes),
            tuple(self.filter_rules),
            self.interval_minutes,
            self.scheduled_time,
        )
