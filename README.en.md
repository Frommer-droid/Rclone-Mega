<p align="center"><img src="logo.png" width="128" alt="Rclone Mega"></p>
<h1 align="center">Rclone Mega</h1>
<p align="center">A Windows desktop app for safe, confirmed mirroring of local folders to MEGA with rclone.</p>
<p align="center"><a href="README.md">Русский</a> · <a href="README.en.md">English</a> · <a href="https://github.com/Frommer-droid/Rclone-Mega/releases/latest">Download / Скачать</a></p>

Rclone Mega provides a graphical interface for `rclone sync`: it manages MEGA
remotes and sync tasks, always shows a dry run first, and starts a real mirror
only after confirmation. The regular installation already includes rclone.

## Highlights

- A consistent One Dark interface, compact row actions, and a tabbed task editor.
- Adaptive scaling for the whole interface, with a saved 50–150% adjustment in settings.
- Drag column borders within the current width, or use Autofit to fit columns to contents and resize the window to the table; proportions persist.
- Per-task run history with persistent reports and `.md` / `.log` export.
- A global setting and per-task option to close applications before mirroring and restart them afterwards.

![Task sorting](docs/screenshots/task-overview.png)

- Sort tasks by name, account, last run, mode, next attempt, or status. Click a header again to reverse the order; dates follow chronological order.

![Task settings (Russian interface)](docs/screenshots/task-settings.png)

- Opt-in permanent MEGA deletion for each task.
- Built-in exclusions for Python caches and common temporary files.

- Import one or more MEGA remotes from a local INI credentials file.
- Keep `rclone.conf` next to the application instead of relying on a global
  rclone profile.
- View all accounts in one task table, with an account column and optional
  filtering by remote.
- Mirror all enabled tasks: one dry-run batch, one shared confirmation, then
  sequential mirroring grouped by account.
- Check the selected remote and display its cloud quota.
- Review changes in a required dry run before mirroring.
- Mirror without deletion count or size limits and optionally preserve deleted files with
  `backup-dir`.
- Schedule checks by interval or time of day; use the Windows tray and
  autostart when needed.

The history icon at the right of each task row opens separate reports for checks and syncs. Reports live in `run-history` next to the settings. Enable the global application-closing checkbox or the option in an individual task to close applications from its source folder before real synchronization. Applications outside that folder are not detected; an abrupt Rclone Mega crash prevents automatic restart.

![Per-task run history](docs/screenshots/run-history.png)

## Quick start

1. Download the installer from the [latest release](https://github.com/Frommer-droid/Rclone-Mega/releases/latest) and install it.
2. Start `Rclone Mega.exe`.
3. Select **Add** in the account panel and choose a local MEGA credentials INI file.
4. Select **Check selected** to verify the remote.
5. Create a task such as `D:\Docs` → `my-mega:PC/Docs`.
6. Select the check icon in the task row. If the dry run is correct, select its sync icon.

Select **All accounts** and **Mirror all** to process all enabled tasks without
switching accounts. Review the shared confirmation after the checks finish.
Selecting an individual account limits the batch to that account.

Drag a column border to resize within the current table width, or select **Autofit**.
Autofit measures column contents and resizes the window width to match the table,
keeping its height and staying within the screen.
Use **Settings → Interface scale** to adjust the entire interface; the choice is saved.

## Requirements

- Windows 10 or 11, x64.
- A MEGA account.
- Python 3.12 only when running or building from source.
- Inno Setup 6 only when creating an installer.

## Safety model

`rclone sync` creates a mirror, so it can delete files from the cloud
destination that no longer exist locally. Rclone Mega first runs
`rclone sync --dry-run --combined -`, presents the planned changes, and asks
for confirmation. Deletion count and size are unlimited. Use `backup-dir`
to retain deleted cloud files separately.

MEGA passwords are not written to `settings.json`. They are provided to
`rclone obscure` through standard input and stored only in the local
`rclone.conf` in rclone's obscured form.

## Run from source

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe .\rclone_mega.py
```

Use `.venv\Scripts\python.exe` as the VS Code interpreter.

After installing dependencies, open `Rclone Mega-run.cmd` in the project root.

## Build and portable copy

```powershell
.\.venv\Scripts\python.exe -m PyInstaller ".\Build_Tools\Rclone Mega.spec" --workpath C:\Build\Rclone-Mega\build --distpath C:\Build\Rclone-Mega\dist
$env:RCLONE_DIST_DIR = 'C:\Build\Rclone-Mega\dist'
.\.venv\Scripts\python.exe .\Build_Tools\post_build.py
```

The onedir build is created as `Rclone Mega\`. `00_CrRel.pyw` creates the
versioned installer on the Windows Desktop and omits runtime settings,
`rclone.conf`, and logs from the installer staging area.

`00_Move.pyw` copies the portable build to `C:\Portable\Rclone Mega` by
default. Set `RCLONE_MEGA_PORTABLE_DIR` locally to choose another parent folder.

## Limitations

- This application uses `rclone sync`, not `bisync`.
- It does not call the MEGA API directly.
- Credentials and runtime configuration stay local; include them in your own
  private backup if you move to another computer.

## License

The project's own source code is licensed under [MIT](LICENSE). The bundled
rclone notice remains in `vendor/rclone/LICENSE.txt`.

## Exclusions and deletion

Python caches (`__pycache__`, `*.pyc`, `*.pyo`, `.pytest_cache`, `.ruff_cache`,
`.mypy_cache`) and common temporary files (`Thumbs.db`, `.DS_Store`, `*.tmp`,
`*.temp`, `*.swp`, `~$*`) are excluded automatically, before custom include filters.
Already excluded files in the cloud are retained.

Permanent MEGA deletion is off by default. Enable it per task to bypass the
MEGA rubbish bin. With `backup-dir`, files move to the backup directory instead.
The mandatory dry run and confirmation still apply.

Tasks can use different MEGA remotes in one window and run sequentially.

Check selected tasks checks enabled tasks for the selected account in the displayed table order. The order is captured on click; errors do not interrupt remaining checks. Queue status, progress and a final summary are displayed.
