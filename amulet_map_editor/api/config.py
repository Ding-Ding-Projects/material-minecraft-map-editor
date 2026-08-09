import os
import pickle
import gzip
from typing import Any

_last_config_env = os.environ.get("CONFIG_DIR")
_path = os.path.abspath(os.path.join(_last_config_env or "."))


def _config_path() -> str:
    """Resolve the active profile directory for each operation.

    Tests and multi-surface hosts intentionally switch temporary profiles
    within one Python process; caching the environment at import time makes
    one surface read another surface's settings.
    """
    global _last_config_env, _path
    current = os.environ.get("CONFIG_DIR")
    if current != _last_config_env:
        _path = os.path.abspath(os.path.join(current or "."))
        _last_config_env = current
    return _path


def get(identifier: str, default: Any = None) -> Any:
    """
    Get the config data for a given identifier. Use an identifier unique to your program.
    :param identifier: An identifier unique to your program
    :param default: The value to return if one could not be loaded
    :return: config data
    """
    path = os.path.join(_config_path(), identifier + ".config")
    if os.path.isfile(path):
        try:
            with gzip.open(path, "rb") as fp:
                val = pickle.load(fp)
            return val
        except:
            pass
    return default


def put(identifier: str, data: Any):
    """
    Add data to the config file and save to disk.
    :param identifier: An identifier unique to your program
    :param data: The data to be saved. Must be JSON serialisable
    :return:
    """
    path_root = _config_path()
    if not os.path.isdir(path_root):
        os.makedirs(path_root)
    path = os.path.join(path_root, identifier + ".config")
    with gzip.open(path, "wb") as fp:
        pickle.dump(data, fp)
