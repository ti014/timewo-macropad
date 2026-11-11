"""Keep patched dependencies and the packaged flasher stub available."""

import tomllib
from pathlib import Path

from esptool.loader import StubFlasher
from packaging.version import Version


def test_lock_excludes_ecdsa_and_contains_patched_setuptools():
    lock = tomllib.loads((Path(__file__).parents[1] / "uv.lock").read_text(encoding="utf-8"))
    versions = {package["name"]: package["version"] for package in lock["package"]}
    assert "ecdsa" not in versions  # CVE-2024-23342 has no upstream fix.
    assert Version(versions["esptool"]) >= Version("5.0.0")
    assert Version(versions["setuptools"]) >= Version("84.1.0")  # GHSA-xmj3-9gf7-h52w
    StubFlasher("ESP32-C3")
