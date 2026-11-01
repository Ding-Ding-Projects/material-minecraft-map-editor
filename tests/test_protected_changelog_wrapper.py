"""Protected input is piped, never forwarded through arguments or child environment."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_protected_changelog as wrapper


def test_private_pipe_and_exit_status(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv(wrapper.KEY, "SYNTHETIC_PAYLOAD")
    monkeypatch.setenv("UNRELATED_CREDENTIAL", "SYNTHETIC_OTHER")
    calls = []
    def child(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(wrapper.subprocess, "run", child)
    assert wrapper.main() == 7
    argv, kwargs = calls[0]
    assert "SYNTHETIC_PAYLOAD" not in repr(argv)
    assert argv[1:3] == ["-I", "-S"]
    assert kwargs["input"] == b"SYNTHETIC_PAYLOAD"
    assert wrapper.KEY not in kwargs["env"]
    assert "UNRELATED_CREDENTIAL" not in kwargs["env"]
    assert kwargs["shell"] is False
    assert capsys.readouterr().out == ""


def test_missing_input_never_launches(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv(wrapper.KEY, raising=False)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected child")))
    assert wrapper.main() == 2


def test_local_environment_is_not_an_input_route(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv(wrapper.KEY, "SYNTHETIC_PAYLOAD")
    assert wrapper.main() == 2
