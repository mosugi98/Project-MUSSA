import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tomllib
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import cagsyntax

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_this_is_mussa_version_two():
    assert cagsyntax.__version__ == "2.0.0"


def test_the_package_version_and_the_project_file_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == cagsyntax.__version__


def test_the_window_title_shows_the_version(qapp, tmp_path):
    from cagsyntax.app import MainWindow
    assert MainWindow(tmp_path / "data").windowTitle() == "MUSSA 2.0 - XA viewer"


def test_the_portable_zip_is_named_after_the_version():
    spec = importlib.util.spec_from_file_location("build_exe_v", ROOT / "tools" / "packaging" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ZIP_NAME == "MUSSA-2.0.0-portable.zip"


def test_the_changelog_explains_version_two_and_names_the_checkpoint():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 2.0.0" in text and "v1.0-checkpoint" in text and "data contract" in text.lower()
