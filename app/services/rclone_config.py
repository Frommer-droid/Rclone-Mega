# -*- coding: utf-8 -*-
"""Настройка rclone remote для MEGA."""

from __future__ import annotations

import configparser
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


REMOTE_NAME = "mega"
REMOTE_TYPE = "mega"
REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class RcloneConfigResult:
    success: bool
    summary: str
    output: str


@dataclass(frozen=True)
class RcloneBatchConfigResult:
    success: bool
    configured_remote_names: list[str]
    failed_remote_names: list[str]
    summary: str


@dataclass(frozen=True)
class MegaCredentials:
    remote_name: str
    email: str
    password: str
    twofa: str = ""


def normalize_remote_name(value: str) -> str:
    return value.strip().removesuffix(":").strip()


def is_valid_remote_name(value: str) -> bool:
    return bool(REMOTE_NAME_RE.fullmatch(normalize_remote_name(value)))


def remote_prefix(value: str) -> str:
    name = normalize_remote_name(value)
    return f"{name}:" if name else ""


def remote_name_from_path(value: str) -> str:
    text = value.strip()
    if ":" not in text:
        return ""
    return normalize_remote_name(text.split(":", 1)[0])


def is_valid_remote_path(value: str) -> bool:
    return is_valid_remote_name(remote_name_from_path(value))


def build_remote_path(remote_name: str, remote_subpath: str = "") -> str:
    return f"{remote_prefix(remote_name)}{remote_subpath.strip()}"


def remote_name_from_email(email: str) -> str:
    text = email.strip().lower()
    local, _, _domain = text.partition("@")
    base = local or text
    sanitized = re.sub(r"[^a-z0-9._-]+", "_", base).strip("._-")
    if not sanitized:
        sanitized = "mega"
    if not sanitized[0].isalnum():
        sanitized = f"mega_{sanitized}"
    return sanitized[:64].rstrip("._-") or "mega"


def build_mega_config_args(
    remote_name: str,
    email: str,
    obscured_password: str,
    twofa: str = "",
    *,
    update: bool = False,
) -> list[str]:
    normalized_remote = normalize_remote_name(remote_name)
    args = [
        "config",
        "update" if update else "create",
        normalized_remote,
    ]
    if update:
        args.extend(["type", REMOTE_TYPE])
    else:
        args.append(REMOTE_TYPE)
    args.extend(
        [
            "user",
            email.strip(),
            "pass",
            obscured_password,
            "--non-interactive",
        ]
    )
    if twofa.strip():
        args.extend(["2fa", twofa.strip()])
    return args


def read_mega_credentials_file(path: Path) -> list[MegaCredentials]:
    if not path.exists():
        raise ValueError(f"Файл учетных данных не найден: {path}")

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8-sig")
    except (configparser.Error, OSError) as exc:
        raise ValueError(f"Не удалось прочитать файл учетных данных: {exc}") from exc
    credentials: list[MegaCredentials] = []
    remote_sources: dict[str, str] = {}

    for section in parser.sections():
        values = parser[section]
        email = (
            values.get("email") or values.get("user") or values.get("login") or ""
        ).strip()
        if "@" in section and not email:
            email = section.strip()
        default_remote = (
            remote_name_from_email(section)
            if "@" in section
            else section if is_valid_remote_name(section) else remote_name_from_email(email)
        )
        remote_name = normalize_remote_name(
            values.get("remote") or default_remote
        )
        password = (values.get("password") or values.get("pass") or "").strip()
        twofa = (
            values.get("2fa") or values.get("twofa") or values.get("otp") or ""
        ).strip()

        if not is_valid_remote_name(remote_name):
            raise ValueError(
                f"Некорректное имя remote в секции [{section}]: {remote_name}"
            )
        if not email:
            raise ValueError(f"В секции [{section}] не указан email/user.")
        if not password:
            raise ValueError(f"В секции [{section}] не указан password/pass.")
        if remote_name in remote_sources:
            raise ValueError(
                f"Remote `{remote_name}` повторяется в секциях "
                f"[{remote_sources[remote_name]}] и [{section}]. "
                "Укажите разным аккаунтам явные строки `remote = ...`."
            )
        remote_sources[remote_name] = section

        credentials.append(
            MegaCredentials(
                remote_name=remote_name,
                email=email,
                password=password,
                twofa=twofa,
            )
        )

    if not credentials:
        raise ValueError("Файл учетных данных не содержит секций [remote_name].")

    return credentials


def obscure_password(rclone_path: str, password: str) -> RcloneConfigResult:
    return _run_rclone(
        rclone_path,
        ["obscure", "-"],
        safe_summary="Подготовка пароля для rclone config.",
        redact_output=False,
        stdin_text=password,
    )


def configure_mega_remote(
    *,
    rclone_path: str,
    config_path: Path,
    remote_name: str = REMOTE_NAME,
    email: str,
    password: str,
    twofa: str = "",
) -> RcloneConfigResult:
    normalized_remote = normalize_remote_name(remote_name)
    if not is_valid_remote_name(normalized_remote):
        return RcloneConfigResult(
            False,
            "Имя remote может содержать латинские буквы, цифры, "
            "точку, дефис и подчёркивание.",
            "",
        )
    if not email.strip():
        return RcloneConfigResult(False, "Укажите email MEGA.", "")
    if not password:
        return RcloneConfigResult(False, "Укажите пароль MEGA.", "")

    obscure_result = obscure_password(rclone_path, password)
    if not obscure_result.success:
        return obscure_result

    obscured_password = obscure_result.output.strip().splitlines()[-1].strip()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    update_existing = remote_exists_in_config(config_path, normalized_remote)
    args = [
        "--config",
        str(config_path),
        *build_mega_config_args(
            normalized_remote,
            email,
            obscured_password,
            twofa,
            update=update_existing,
        ),
    ]
    action = "обновлён" if update_existing else "настроен"
    return _run_rclone(
        rclone_path,
        args,
        safe_summary=f"MEGA remote `{normalized_remote}:` {action}.",
        redact_output=False,
    )


def configure_mega_remotes(
    *,
    rclone_path: str,
    config_path: Path,
    credentials: list[MegaCredentials],
) -> RcloneBatchConfigResult:
    configured: list[str] = []
    failed: list[str] = []

    if not credentials:
        return RcloneBatchConfigResult(
            False,
            [],
            [],
            "Файл учетных данных не содержит аккаунтов MEGA.",
        )

    for item in credentials:
        result = configure_mega_remote(
            rclone_path=rclone_path,
            config_path=config_path,
            remote_name=item.remote_name,
            email=item.email,
            password=item.password,
            twofa=item.twofa,
        )
        if result.success:
            configured.append(item.remote_name)
        else:
            failed.append(item.remote_name)

    summary = (
        f"Настроено remote: {len(configured)}."
        if configured
        else "Не удалось настроить ни один remote."
    )
    if failed:
        summary += f" Ошибки: {', '.join(failed)}."

    return RcloneBatchConfigResult(
        not failed and bool(configured),
        configured,
        failed,
        summary,
    )


def remote_exists_in_config(config_path: Path, remote_name: str) -> bool:
    if not config_path.exists():
        return False
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path, encoding="utf-8-sig")
    return parser.has_section(normalize_remote_name(remote_name))


def list_configured_remotes(rclone_path: str, config_path: Path) -> RcloneConfigResult:
    return _run_rclone(
        rclone_path,
        ["--config", str(config_path), "listremotes"],
        safe_summary="Список remote обновлён.",
        redact_output=False,
    )


def parse_remote_list(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        name = normalize_remote_name(line.strip())
        if is_valid_remote_name(name) and name not in names:
            names.append(name)
    return names


def _run_rclone(
    rclone_path: str,
    args: list[str],
    *,
    safe_summary: str,
    redact_output: bool,
    stdin_text: str | None = None,
) -> RcloneConfigResult:
    try:
        result = subprocess.run(
            [rclone_path, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=stdin_text,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return RcloneConfigResult(False, f"Не удалось запустить rclone: {exc}", "")

    output = "" if redact_output else result.stdout.strip()
    if result.returncode == 0:
        return RcloneConfigResult(True, safe_summary, output)

    message = result.stdout.strip() or f"rclone завершился с кодом {result.returncode}."
    return RcloneConfigResult(False, message, output)
