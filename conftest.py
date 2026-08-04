"""Root pytest configuration.

Ensures subprocesses spawned by tests (e.g. ``src/novel_cli.py``, the
short-form entry scripts) inherit a UTF-8 stdout/stderr encoding, so
``pytest tests/ -q`` produces a stable green baseline on Chinese Windows
where the default console codepage is cp936/GBK.
"""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
