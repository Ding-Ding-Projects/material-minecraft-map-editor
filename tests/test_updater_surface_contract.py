"""Keep the app on the non-blocking Squirrel updater surface."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI_SMOKE = (ROOT / "scripts/smoke_squirrel_cli_output.ps1").read_text(encoding="utf-8")


def test_startup_does_not_wire_the_legacy_modal_update_dialog():
    app = (ROOT / "amulet_map_editor/api/framework/app.py").read_text(encoding="utf-8")
    ui = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "update_check" not in app
    assert "UpdateDialog" not in app
    assert "_check_for_updates_async" in ui
    assert "_stage_update_async" in ui
    assert "_restart_to_install_update" in ui
    assert "_open_update_release_notes" in ui


def test_restart_uses_the_official_guarded_squirrel_handoff():
    ui = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    restart = ui[
        ui.index("    def _restart_to_install_update") : ui.index(
            "    def _on_app_close"
        )
    ]
    assert '"--restart"' not in restart
    assert "build_restart_command(updater)" in restart
    assert "begin_preapproved_app_close(generation)" in restart
    assert "time.sleep(0.5)" in restart
    assert "exit_code = process.poll()" in restart
    assert "if exit_code is not None:" in restart
    assert "Update.exe exited during the" in restart
    assert "self._update_restart_generation = generation" in restart
    assert "self._update_state is not ready_state" in restart
    assert "self._hide_update_banner()" not in restart

    close = ui[
        ui.index("    def _on_app_close") : ui.index("    def _update_primary_action")
    ]
    assert "preapproved_generation=generation" in close
    assert "the update remains ready" in close


def test_real_squirrel_cli_smoke_locks_output_and_cleanup_bounds():
    assert "-Version 2.0.1" in CLI_SMOKE
    assert "--checkForUpdate=" in CLI_SMOKE
    assert "CreateNoWindow = $true" in CLI_SMOKE
    assert "blankLineCount" in CLI_SMOKE
    assert "currentVersion" in CLI_SMOKE
    assert "futureVersion" in CLI_SMOKE
    assert "releasesToApply" in CLI_SMOKE
    assert "ReadToEndAsync()" in CLI_SMOKE
    assert ".ReadToEnd()" not in CLI_SMOKE
    async_read = CLI_SMOKE.index(
        "$stdoutTask = $process.StandardOutput.ReadToEndAsync()"
    )
    exit_wait = CLI_SMOKE.index("$process.WaitForExit($TimeoutMilliseconds)")
    kill = CLI_SMOKE.index("$process.Kill($true)", exit_wait)
    bounded_read_wait = CLI_SMOKE.index("[Threading.Tasks.Task]::WaitAll", kill)
    collect = CLI_SMOKE.index("$stdoutTask.GetAwaiter().GetResult()", bounded_read_wait)
    assert async_read < exit_wait < kill < bounded_read_wait < collect
    assert "MaximumStreamBytes = 65536" in CLI_SMOKE
    assert "amulet-squirrel-cli-probe-*" in CLI_SMOKE
    assert "Remove-Item -LiteralPath $resolvedProbe -Recurse -Force" in CLI_SMOKE


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is unavailable")
def test_real_cli_smoke_lifecycle_self_test_kills_hung_child():
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "smoke_squirrel_cli_output.ps1"),
            "-LifecycleSelfTest",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["lifecycle"] == "hung-child-killed"
    assert 0 < payload["elapsed_ms"] < 10_000
