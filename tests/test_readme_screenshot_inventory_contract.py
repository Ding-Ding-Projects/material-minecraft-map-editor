from pathlib import Path


README = Path("README.md").read_text(encoding="utf-8")


def test_readme_reports_all_tracked_runtime_and_historical_captures():
    assert "Eleven genuine images inspected" in README
    assert "four 2026 runtime baselines" in README
    assert "Baseline only: four current wx runtime captures are tracked" in README
    for name in (
        "preferences-runtime-baseline-20260809.png",
        "preferences-appearance-runtime-baseline-20260809.png",
        "notification-history-runtime-baseline-20260809.png",
        "main-frame-runtime-baseline-20260809.png",
    ):
        assert f"resource/img/{name}" in README
