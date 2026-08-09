from pathlib import Path
import struct

README = Path("README.md").read_text(encoding="utf-8")


def test_readme_reports_all_tracked_runtime_and_historical_captures():
    assert "Twelve genuine images inspected" in README
    assert "four earlier wxPython runtime baselines" in README
    assert "one exact-commit Material shell capture" in README
    for name in (
        "preferences-runtime-baseline-20260809.png",
        "preferences-appearance-runtime-baseline-20260809.png",
        "notification-history-runtime-baseline-20260809.png",
        "main-frame-runtime-baseline-20260809.png",
        "main-frame-material-shell-b3cbec1c-20260809.png",
    ):
        assert f"resource/img/{name}" in README


def test_exact_commit_material_shell_capture_is_a_real_png():
    path = Path("resource/img/main-frame-material-shell-b3cbec1c-20260809.png")
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (2250, 1395)
    assert "b3cbec1c4b1035dd0c2ebdc9a545266f49c257ef" in README
