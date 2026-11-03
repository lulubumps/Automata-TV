"""Evita que la versión, el CHANGELOG y la imagen de Docker se desincronicen al publicar."""
import re
from pathlib import Path

from app import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_changelog_has_entry_for_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in changelog


def test_dockerfile_version_matches():
    assert f"ARG VERSION={__version__}" in (ROOT / "Dockerfile").read_text(encoding="utf-8")
