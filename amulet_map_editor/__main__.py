#!/usr/bin/env python3


def _log_error(e) -> None:
    """Code to handle errors"""
    try:
        import traceback
        import sys
        import os

    except ImportError as e:
        # Something has gone seriously wrong
        print(e)
        print("Failed to import requirements. Check that you extracted correctly.")
    else:
        msg_lines = [traceback.format_exc()]
        if isinstance(e, ImportError):
            msg_lines.append(
                "Failed to import requirements. Check that you extracted correctly."
            )
        msg_lines.append(str(e))
        err = "\n".join(msg_lines)
        # A windowed build has no standard streams, so printing straight to
        # stdout would replace the real failure with a stream error.
        if sys.stdout is not None:
            try:
                sys.stdout.write(err + "\n")
                sys.stdout.flush()
            except (ValueError, OSError):
                pass
        try:
            with open("crash.log", "w") as f:
                f.write(err)
        except OSError:
            pass


try:
    import sys

    if sys.version_info[:2] < (3, 7):
        raise Exception("Must be using Python 3.7+")
    import logging
    import os
    import re
    import tempfile
    import traceback
    import time
    import platformdirs
    from typing import Any, List, NoReturn, Optional, Tuple, Type
    from types import TracebackType
    import threading
    import faulthandler
    import subprocess
    import multiprocessing
except Exception as e_:
    _log_error(e_)
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("Press ENTER to continue.")
    except (AttributeError, EOFError, OSError, RuntimeError):
        pass
    sys.exit(1)


_APP_LOG_NAME = re.compile(r"amulet_\d+\.log(\.\d+)?\Z")
_LOG_RETENTION_SECONDS = 3600 * 24 * 7
_EARLY_DIAGNOSTIC_LIMIT = 512
_LOG_DIR_CHANNEL_LIMIT = 4096
#: A running session writes to one file at a time, capped at a few megabytes,
#: and keeps a handful of rotated predecessors -- so a machine left running
#: for weeks accumulates a bounded amount of log data per process rather than
#: one file that grows without limit.
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 4


def _early_diagnostic(message: str, error: Optional[BaseException] = None) -> None:
    """Emit a bounded best-effort diagnostic before logging is configured."""
    if error is not None:
        message = f"{message}: {error}"
    try:
        print(message[:_EARLY_DIAGNOSTIC_LIMIT], file=sys.stderr)
    except (AttributeError, OSError):
        pass


def _clean_stale_app_logs(logs_path: str) -> None:
    """Remove only stale application log files from an app-owned log directory."""
    cutoff = time.time() - _LOG_RETENTION_SECONDS
    try:
        entries = os.scandir(logs_path)
    except OSError as e:
        _early_diagnostic("Unable to inspect stale application logs", e)
        return

    try:
        with entries:
            for entry in entries:
                if not _APP_LOG_NAME.fullmatch(entry.name):
                    continue
                try:
                    if (
                        entry.is_file(follow_symlinks=False)
                        and entry.stat(follow_symlinks=False).st_mtime < cutoff
                    ):
                        os.remove(entry.path)
                except OSError as e:
                    # Another process may remove or lock a log between inspection and deletion.
                    _early_diagnostic(
                        f"Unable to remove stale application log {entry.name}", e
                    )
    except OSError as e:
        _early_diagnostic("Unable to iterate stale application logs", e)


def _open_log_file(logs_path: str) -> Tuple[Optional[str], Optional[Any], bool]:
    """Open a rotating application log, falling back to a temp dir if needed.

    The handler caps itself at :data:`_LOG_MAX_BYTES` per file and keeps
    :data:`_LOG_BACKUP_COUNT` rotated predecessors (``amulet_<pid>.log``,
    ``amulet_<pid>.log.1``, ...), so a session left running for a long time
    cannot grow one file without bound.
    """
    import logging.handlers

    candidates = [(logs_path, False)]
    try:
        fallback_path = os.path.join(tempfile.gettempdir(), "AmuletMapEditor", "Logs")
    except OSError as e:
        _early_diagnostic("Unable to determine a fallback log directory", e)
    else:
        if fallback_path != logs_path:
            candidates.append((fallback_path, True))

    for candidate, is_fallback in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(candidate, f"amulet_{os.getpid()}.log"),
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            return candidate, handler, is_fallback
        except OSError as e:
            _early_diagnostic(f"Unable to use log directory {candidate!r}", e)

    _early_diagnostic("Logging to files is unavailable; continuing with stderr only")
    return None, None, False


def _init_log(*, clean_stale_logs: bool = False) -> logging.Logger:
    logs_path = os.environ.get("LOG_DIR")
    if logs_path is None:
        logs_path = platformdirs.user_log_dir("AmuletMapEditor", "AmuletTeam")
        os.environ["LOG_DIR"] = logs_path

    effective_logs_path, file_handler, using_fallback = _open_log_file(logs_path)
    if effective_logs_path is not None:
        os.environ["LOG_DIR"] = effective_logs_path
        if clean_stale_logs or using_fallback:
            _clean_stale_app_logs(effective_logs_path)

        log_dir_path = os.environ.get("AMULET_LOG_DIR_PATH")
        if log_dir_path:
            try:
                if len(effective_logs_path) > _LOG_DIR_CHANNEL_LIMIT:
                    raise OSError("Effective log directory path is too long to report")
                with open(log_dir_path, "w", encoding="utf-8") as f:
                    f.write(effective_logs_path)
            except OSError as e:
                _early_diagnostic("Unable to report the effective log directory", e)

    debug = "debug" in os.path.basename(sys.executable) or "--amulet-debug" in sys.argv

    handlers: List[logging.Handler] = []
    if file_handler is not None:
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
        )
        handlers.append(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(
            "%(levelname)s - %(name)s - %(message)s"
            if debug
            else "%(levelname)s - %(message)s"
        )
    )
    handlers.append(console_handler)

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=handlers,
        force=True,
    )

    log = logging.getLogger(__name__)

    def error_handler(
        exc_type: Type[BaseException],
        exc_value: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if exc_value is None:
            return
        log.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = error_handler

    # threading.excepthook and ExceptHookArgs were added in Python 3.8.
    # Keep the declared Python 3.7 compatibility while using the hook when present.
    if hasattr(threading, "excepthook"):

        def thread_error_handler(args: Any) -> None:
            error_handler(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = thread_error_handler

    if "--enable-py-faulthandler" in sys.argv:
        # When running via pythonw stderr can be unavailable, so use the application log.
        if (
            file_handler is not None
            and getattr(file_handler, "stream", None) is not None
        ):
            faulthandler.enable(file_handler.stream)
        else:
            log.warning(
                "Unable to enable faulthandler because no writable log file is available."
            )

    if "--enable-amulet-faulthandler" in sys.argv:
        if effective_logs_path is None:
            log.warning(
                "Unable to enable amulet_faulthandler because no writable log directory is available."
            )
        else:
            try:
                import amulet_faulthandler

                amulet_faulthandler.install(
                    os.path.join(effective_logs_path, f"amulet_{os.getpid()}.dmp"),
                    debug,
                )
            except (ImportError, OSError):
                log.warning(
                    "Unable to enable amulet_faulthandler; continuing without it.",
                    exc_info=True,
                )
    if sys.platform == "win32":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            try:
                os.makedirs(
                    os.path.join(
                        local_app_data,
                        "AmuletTeam",
                        "AmuletMapEditor",
                        "Logs",
                        "crash",
                    ),
                    exist_ok=True,
                )
            except OSError:
                log.warning(
                    "Unable to create the Windows crash-dump directory; continuing without it.",
                    exc_info=True,
                )
        else:
            log.warning(
                "LOCALAPPDATA is unavailable; skipping Windows crash-dump directory setup."
            )

    return log


def _app_main() -> int:
    if sys.platform == "linux":
        # bug 247
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

    # Initialise default paths.
    data_dir = platformdirs.user_data_dir("AmuletMapEditor", "AmuletTeam")
    os.environ.setdefault("DATA_DIR", data_dir)
    config_dir = platformdirs.user_config_dir("AmuletMapEditor", "AmuletTeam")
    if config_dir == data_dir:
        config_dir = os.path.join(data_dir, "Config")
    os.environ.setdefault("CONFIG_DIR", config_dir)
    os.environ.setdefault(
        "CACHE_DIR", platformdirs.user_cache_dir("AmuletMapEditor", "AmuletTeam")
    )
    external_log_dir = "LOG_DIR" in os.environ
    os.environ.setdefault(
        "LOG_DIR", platformdirs.user_log_dir("AmuletMapEditor", "AmuletTeam")
    )

    log = _init_log(clean_stale_logs=not external_log_dir)

    try:
        log.debug("Importing numpy")
        import numpy

        log.debug("Importing amulet_nbt")
        import amulet_nbt

        log.debug("Importing leveldb")
        import leveldb

        log.debug("Importing PyMCTranslate and amulet")
        import PyMCTranslate
        import amulet

        log.debug("Importing minecraft_model_reader")
        import minecraft_model_reader

        log.debug("Importing amulet_map_editor")
        from amulet_map_editor.api.framework import AmuletApp

        log.debug("Finished importing")

        # Before the first window exists, and before wx reads the display.
        # Windows fixes a process's DPI awareness the first time it is asked
        # for, so this cannot be moved later or repaired afterwards.
        from amulet_map_editor.api import dpi as _dpi

        log.debug("DPI awareness: %s", _dpi.declare_awareness())

        app = AmuletApp(0)
        app.MainLoop()
    except Exception as e:
        log.critical(
            f"Amulet Crashed. Please report it to a developer. \n{traceback.format_exc()}"
        )
        return 1
    return 0


def _launcher_python() -> str:
    """Return the interpreter that starts the child without a console.

    A source checkout normally runs under ``python.exe``, which owns a console
    window.  Re-launching through the matching ``pythonw.exe`` keeps the child
    windowed even when the parent was started from a terminal, which is what
    makes ``py -3 -m amulet_map_editor`` behave like the packaged application.
    """
    executable = sys.executable
    if os.name != "nt" or getattr(sys, "frozen", False):
        return executable
    directory, name = os.path.split(executable)
    if name.lower() == "python.exe":
        windowed = os.path.join(directory, "pythonw.exe")
        if os.path.isfile(windowed):
            return windowed
    return executable


def main() -> NoReturn:
    is_launcher = False
    try:
        multiprocessing.freeze_support()
        is_launcher = "--amulet-main" not in sys.argv
        if is_launcher:
            # Amulet is a windowed application: the relaunched child must not
            # allocate a console of its own, and on a source checkout that means
            # handing the work to pythonw rather than python.
            from amulet_map_editor.api import process as _process

            launcher = _launcher_python()
            log_dir_channel_path = None
            child_env = os.environ.copy()
            child_env.pop("AMULET_LOG_DIR_PATH", None)
            try:
                with tempfile.NamedTemporaryFile(
                    prefix="amulet-log-dir-", suffix=".txt", delete=False
                ) as log_dir_channel:
                    log_dir_channel_path = log_dir_channel.name
                child_env["AMULET_LOG_DIR_PATH"] = log_dir_channel_path
            except OSError as e:
                _early_diagnostic(
                    "Unable to create the effective log directory channel", e
                )

            try:
                if getattr(sys, "frozen", False):
                    args = [sys.executable, "--amulet-main"] + sys.argv[1:]
                else:
                    args = [launcher, __file__, "--amulet-main"] + sys.argv[1:]
                exit_code = _process.run(args, env=child_env).returncode
                if log_dir_channel_path is not None:
                    try:
                        with open(
                            log_dir_channel_path, "r", encoding="utf-8"
                        ) as log_dir_channel:
                            effective_log_dir = log_dir_channel.read(
                                _LOG_DIR_CHANNEL_LIMIT + 1
                            )
                        if 0 < len(effective_log_dir) <= _LOG_DIR_CHANNEL_LIMIT:
                            os.environ["LOG_DIR"] = effective_log_dir
                        elif len(effective_log_dir) > _LOG_DIR_CHANNEL_LIMIT:
                            _early_diagnostic(
                                "Child reported an oversized effective log directory"
                            )
                    except (OSError, UnicodeError) as e:
                        _early_diagnostic(
                            "Unable to read the effective log directory", e
                        )
            finally:
                if log_dir_channel_path is not None:
                    try:
                        os.remove(log_dir_channel_path)
                    except OSError:
                        pass
        else:
            exit_code = _app_main()
    except Exception as e:
        _log_error(e)
        exit_code = 1

    if is_launcher and exit_code:
        from amulet_map_editor.api import process as _process

        report = (
            f"Application crashed with exit code {exit_code} (0x{exit_code:0X})\n"
            "Please report this issue to a developer.\n"
            "Attach the logs in the opened directory with your report."
        )
        _process.write_console(report)
        log_dir = os.environ.get("LOG_DIR") or platformdirs.user_log_dir(
            "AmuletMapEditor", "AmuletTeam"
        )
        try:
            if sys.platform == "win32":
                os.startfile(log_dir)
            elif sys.platform == "darwin":
                _process.run(["open", log_dir], check=False)
            else:
                _process.run(["xdg-open", log_dir], check=False)
        except OSError as e:
            _process.write_console(f"Unable to open the log directory {log_dir!r}: {e}")
        # ``input`` needs a real console; a windowed build has none, so opening
        # the log directory above is the whole report there.
        if getattr(sys, "frozen", False) and _process.has_console():
            try:
                input("Press ENTER to continue.")
            except (EOFError, OSError):
                pass
    sys.exit(bool(exit_code))


if __name__ == "__main__":
    main()
