# Third-party software

The MIT license in `LICENSE` covers Rclone Mega's own code. Bundled dependencies
retain their own licenses and copyright notices.

- **rclone**: MIT; see `_internal/vendor/rclone/LICENSE.txt` in the application,
  or `vendor/rclone/LICENSE.txt` in the source repository. Source: https://github.com/rclone/rclone.
- **Qt / PySide6 / Shiboken6 6.11.0**: the open-source distribution uses LGPLv3
  and applicable Qt license exceptions. License texts are in `licenses/`.
  Qt licensing details: https://doc.qt.io/qtforpython-6/licenses.html.
  Corresponding sources: https://github.com/qt/qtbase/tree/v6.11.0 and
  https://github.com/pyside/pyside-setup/tree/v6.11.0.
  Qt libraries remain separate DLLs in `_internal` and may be replaced with
  compatible modified libraries. Reverse engineering for debugging modifications
  to these libraries is permitted under their applicable licenses.
- **Python 3.12**: Python Software Foundation license; see `licenses/Python.txt`.
  Source: https://www.python.org/downloads/source/.
- **PyInstaller**: GPL with an exception allowing distribution of bundled
  applications under their own licenses. https://pyinstaller.org/en/stable/license.html.
- **Microsoft Visual C++ runtime**: redistributed with Qt; Microsoft licensing
  terms apply. It is not covered by this application's MIT license.
