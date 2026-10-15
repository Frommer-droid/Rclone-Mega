"""Корректное закрытие portable-приложений и восстановление их запуска."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


@dataclass(frozen=True)
class ApplicationProcess:
    pid: int
    parent_pid: int
    executable: str
    command_line: str
    started: int

    @property
    def label(self) -> str:
        return f"{Path(self.executable).name} — {Path(self.executable).parent}"


def _kernel32():
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    dll.OpenProcess.restype = wintypes.HANDLE
    dll.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)
    ] * 4
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    dll.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    dll.ProcessIdToSessionId.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    ]
    return dll


def process_started(pid: int) -> int | None:
    """PID + FILETIME защищают от обращения к повторно использованному PID."""
    dll = _kernel32()
    handle = dll.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: процесс уже завершился.
            return None
        raise OSError(error, f"Нет доступа к процессу {pid}")
    try:
        exit_code = wintypes.DWORD()
        if not dll.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if exit_code.value != 259:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not dll.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        dll.CloseHandle(handle)


def snapshot_processes() -> list[ApplicationProcess]:
    if sys.platform != "win32":
        raise RuntimeError("Закрытие приложений поддерживается только в Windows.")
    session = wintypes.DWORD()
    if not _kernel32().ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    script = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        "@(Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.SessionId -eq {session.value} }} | "
        "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine) "
        "| ConvertTo-Json -Compress"
    )
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError("Не удалось получить список приложений Windows.")
    rows = json.loads(result.stdout.strip() or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    processes = []
    for row in rows:
        # Системные/чужие процессы без доступного пути не являются кандидатами.
        if not row.get("ExecutablePath"):
            continue
        processes.append(ApplicationProcess(
            int(row["ProcessId"]), int(row["ParentProcessId"]),
            str(row["ExecutablePath"]), str(row.get("CommandLine") or ""), 0,
        ))
    return processes


def _inside(executable: str, folder: Path) -> bool:
    return Path(executable).resolve().is_relative_to(folder.resolve())


def select_applications(
    processes: list[ApplicationProcess], source: Path, own_root: Path,
    rclone_path: Path, current_pid: int,
) -> list[ApplicationProcess]:
    by_pid = {p.pid: p for p in processes}
    protected = {current_pid}
    protected_children = {current_pid}
    parent = by_pid.get(current_pid)
    while parent and parent.parent_pid not in protected:
        protected.add(parent.parent_pid)
        parent = by_pid.get(parent.parent_pid)
    for process in processes:
        if (
            _inside(process.executable, own_root)
            or Path(process.executable).resolve() == rclone_path.resolve()
            or Path(process.executable).name.casefold() in {
                "rclone.exe", "rclone mega.exe"
            }
        ):
            protected.add(process.pid)
            protected_children.add(process.pid)
    # Не закрывать вспомогательные процессы самой программы/защищённых приложений.
    while True:
        children = {p.pid for p in processes if p.parent_pid in protected_children}
        if children.issubset(protected_children):
            break
        protected_children.update(children)
    protected.update(protected_children)
    return [p for p in processes if p.pid not in protected
            and _inside(p.executable, source)]


def root_applications(processes: list[ApplicationProcess]) -> list[ApplicationProcess]:
    ids = {p.pid for p in processes}
    return [p for p in processes if p.parent_pid not in ids]


def command_arguments(command_line: str) -> tuple[str, ...]:
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel = _kernel32()
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    args = shell.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not args:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return tuple(args[index] for index in range(count.value))
    finally:
        kernel.LocalFree(args)


def launch_executable(process: ApplicationProcess) -> str:
    # Некоторые launchers (например, Python venv) запускают другой реальный exe.
    # При повторном запуске нужен исходный launcher из argv[0], а не его runtime.
    args = command_arguments(process.command_line)
    first = Path(args[0]) if args else Path()
    if first.is_absolute() and first.is_file():
        return str(first)
    return process.executable


def graceful_shutdown(processes: list[ApplicationProcess]) -> None:
    """Restart Manager без RmForceShutdown: никаких kill/TerminateProcess."""
    if not processes:
        return

    class UniqueProcess(ctypes.Structure):
        _fields_ = [("pid", wintypes.DWORD), ("started", wintypes.FILETIME)]

    dll = ctypes.WinDLL("rstrtmgr", use_last_error=True)
    dll.RmStartSession.argtypes = [
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR
    ]
    dll.RmRegisterResources.argtypes = [
        wintypes.DWORD, wintypes.UINT, ctypes.c_void_p,
        wintypes.UINT, ctypes.POINTER(UniqueProcess),
        wintypes.UINT, ctypes.c_void_p,
    ]
    dll.RmShutdown.argtypes = [wintypes.DWORD, wintypes.ULONG, ctypes.c_void_p]
    dll.RmEndSession.argtypes = [wintypes.DWORD]
    for name in ("RmStartSession", "RmRegisterResources", "RmShutdown", "RmEndSession"):
        getattr(dll, name).restype = wintypes.DWORD
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(33)
    error = dll.RmStartSession(ctypes.byref(session), 0, key)
    if error:
        raise OSError(error, "Не удалось запросить закрытие приложений")
    try:
        records = (UniqueProcess * len(processes))(*[
            UniqueProcess(p.pid, wintypes.FILETIME(
                p.started & 0xFFFFFFFF, p.started >> 32
            )) for p in processes
        ])
        error = dll.RmRegisterResources(session, 0, None, len(records), records, 0, None)
        if error:
            raise OSError(error, "Не удалось зарегистрировать приложения")
        # Частичное закрытие допустимо: вызывающий код проверит оставшиеся процессы.
        error = dll.RmShutdown(session, 0, None)
        if error not in (0, 350, 351, 1223):
            raise OSError(error, "Не удалось корректно закрыть приложения")
    finally:
        dll.RmEndSession(session)


class ProcessPauseSession:
    def __init__(self, source: str, own_root: Path, rclone_path: str) -> None:
        self.source = Path(source)
        self.own_root = own_root
        self.rclone_path = Path(rclone_path)
        self.processes: list[ApplicationProcess] = []
        self.roots: list[ApplicationProcess] = []
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def _candidates(self) -> list[ApplicationProcess]:
        return select_applications(
            snapshot_processes(), self.source, self.own_root,
            self.rclone_path, os.getpid(),
        )

    def prepare(self) -> list[str]:
        candidates = self._candidates()
        captured = []
        for p in candidates:
            if not p.command_line:
                raise RuntimeError(f"Не удалось сохранить параметры запуска: {p.label}")
            started = process_started(p.pid)
            if started is not None:
                captured.append(ApplicationProcess(
                    p.pid, p.parent_pid, p.executable, p.command_line, started
                ))
        self.processes = captured
        self.roots = root_applications(captured)
        # Один неподдерживаемый фоновой процесс не должен мешать закрытию остальных.
        # Дочерние helpers завершает основное приложение; их выход тоже проверяется.
        for process in self.roots:
            if self._cancelled.is_set():
                break
            try:
                graceful_shutdown([process])
            except OSError:
                # Ошибка запроса закрытия не разрешает sync: remaining() потребует
                # ручного завершения конкретного приложения.
                pass
        return self.remaining()

    def remaining(self) -> list[str]:
        # Повторная проверка учитывает и приложения, запущенные после начала ожидания.
        candidates = self._candidates()
        return list(dict.fromkeys(p.label for p in candidates))

    def restore(self) -> list[str]:
        errors = []
        for process in self.roots:
            try:
                if process_started(process.pid) == process.started:
                    continue
                current = snapshot_processes()
                if any(
                    Path(p.executable).resolve() == Path(process.executable).resolve()
                    and command_arguments(p.command_line)[1:]
                    == command_arguments(process.command_line)[1:]
                    for p in current if p.command_line
                ):
                    continue
                launcher = launch_executable(process)
                child = subprocess.Popen(
                    process.command_line, executable=launcher,
                    cwd=str(Path(launcher).parent),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                # Ранний отказ запуска виден; успешный старт не обещает восстановление окон.
                time.sleep(0.25)
                if child.poll() not in (None, 0):
                    raise RuntimeError(f"код {child.returncode}")
            except Exception as exc:
                errors.append(f"Не удалось запустить {process.label}: {exc}")
        return errors
