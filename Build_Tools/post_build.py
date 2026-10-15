# -*- coding: utf-8 -*-
"""Post-build шаг для релизной папки Rclone Mega."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Rclone Mega"
EXE_NAME = f"{APP_NAME}.exe"

FILES_TO_COPY: list[tuple[str, str]] = [
    ("VERSION", "VERSION"),
    ("LICENSE", "LICENSE"),
    ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
    ("licenses", "licenses"),
    ("logo.ico", "logo.ico"),
    ("settings.json", "settings.json"),
]

REQUIRED_ITEMS = (
    EXE_NAME,
    "_internal",
    "VERSION",
    "LICENSE",
    "logo.ico",
    "_internal/vendor/rclone/rclone.exe",
)


def _configure_stdout() -> None:
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def safe_copy(src: Path, dst: Path, label: str) -> None:
    if not src.exists():
        print(f"[SKIP] {label} не найден: {src}")
        return

    try:
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        print(f"[OK] Скопировано: {label}")
    except Exception as exc:
        print(f"[ERROR] Не удалось скопировать {label}: {exc}")


def find_dist_app_dir(script_dir: Path, project_root: Path) -> Path | None:
    if override := os.environ.get("RCLONE_DIST_DIR"):
        candidate = Path(override) / APP_NAME
        return candidate if candidate.is_dir() else None
    candidates = (
        script_dir / "dist" / APP_NAME,
        project_root / "dist" / APP_NAME,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def cleanup_temp_dirs(script_dir: Path, project_root: Path, final_app_dir: Path) -> None:
    print("\n[СОХРАНЕНИЕ] Кеши и рабочие каталоги сборки оставлены владельцу.")


def verify_release_dir(final_app_dir: Path) -> int:
    missing = [name for name in REQUIRED_ITEMS if not (final_app_dir / name).exists()]
    if missing:
        print("[ERROR] Итоговая папка сборки неполная.")
        for item in missing:
            print(f"  - отсутствует: {item}")
        return 1
    return 0


def main() -> int:
    _configure_stdout()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    final_app_dir = project_root / APP_NAME

    print("\n" + "=" * 60)
    print(f"POST-BUILD: {APP_NAME}")
    print("=" * 60)

    dist_app_dir = find_dist_app_dir(script_dir, project_root)
    if dist_app_dir is None:
        print(
            f"[ERROR] Не найдена папка dist/{APP_NAME} ни в {script_dir}, ни в {project_root}."
        )
        return 1

    try:
        if final_app_dir.exists():
            shutil.rmtree(final_app_dir)
            print(f"[OK] Удалена старая папка релиза: {final_app_dir}")
        shutil.move(str(dist_app_dir), str(final_app_dir))
        print(f"[OK] Перемещено в корень проекта: {final_app_dir}")
    except Exception as exc:
        print(f"[ERROR] Не удалось подготовить итоговую папку релиза: {exc}")
        return 1

    cleanup_temp_dirs(script_dir, project_root, final_app_dir)

    print("\n[КОПИРОВАНИЕ] Добавляем внешние файлы проекта...")
    for src_rel, dst_rel in FILES_TO_COPY:
        safe_copy(project_root / src_rel, final_app_dir / dst_rel, src_rel)

    result = verify_release_dir(final_app_dir)
    if result != 0:
        return result

    print("\n" + "=" * 60)
    print(f"ГОТОВО: {final_app_dir}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
