"""Windows packaging must use the OS ICU API instead of a foreign tool's ICU."""

import importlib.util
import os
from pathlib import Path

import pytest


@pytest.fixture
def build_module():
    path = Path(__file__).resolve().parents[2] / "scripts/build_exe.py"
    spec = importlib.util.spec_from_file_location("focuslab_build_exe_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_apis_and_python_tls_resolve_before_foreign_path_tools(build_module, tmp_path):
    python_dlls = tmp_path / "python/DLLs"
    system32 = tmp_path / "Windows/System32"
    foreign = str(tmp_path / "poppler/bin")
    paths = build_module.windows_dll_path(foreign, python_dlls, system32).split(os.pathsep)
    assert paths.index(str(python_dlls)) < paths.index(foreign)
    assert paths.index(str(system32)) < paths.index(foreign)


@pytest.mark.parametrize("bundled", (None, b"windows API", b"foreign versioned API"))
def test_rejects_foreign_icu_but_accepts_the_os_or_no_bundled_icu(build_module, tmp_path, bundled):
    internal, system32 = tmp_path / "bundle", tmp_path / "System32"
    internal.mkdir()
    system32.mkdir()
    (system32 / "icuuc.dll").write_bytes(b"windows API")
    if bundled is not None:
        (internal / "icuuc.dll").write_bytes(bundled)
    if bundled == b"foreign versioned API":
        with pytest.raises(SystemExit, match="foreign icuuc.dll"):
            build_module.verify_system_icu(internal, system32)
    else:
        build_module.verify_system_icu(internal, system32)
