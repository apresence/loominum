"""
Configuration for Loominum.
"""

import json
import os
import typing as tp

from pathlib import Path


# Settings overridable individually via environment, mapped to their config key.
_ENV_OVERRIDES: tp.Dict[str, str] = {
    'LOOMINUM_SERVER_URL': 'server_url',
    'LOOMINUM_CLIENT_URL': 'client_url',
    'LOOMINUM_LOG_FILE': 'log_file',
    'LOOMINUM_CERT_SANS': 'cert_sans',
    'LOOMINUM_VERBOSE': 'verbose',
}

# Relative location of the config file under a project / data root.
_CONFIG_RELPATH = Path('data') / 'loominum' / 'config.json'


def _env_truthy(val: str) -> bool:
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def discover_config() -> tp.Optional[Path]:
    """Find a config file by convention, returning the first that exists.

    Precedence (high to low):
      1. ``$LOOMINUM_CONFIG``           -- explicit full path to a config file
      2. ``./loominum.json`` or ``./data/loominum/config.json`` (cwd)
      3. ``$XDG_CONFIG_HOME/loominum/config.json`` (or ``~/.config/...``)
      4. ``$PRJ_DIR/data/loominum/config.json`` (legacy / back-compat)

    Returns ``None`` when nothing is found -- callers should then fall back to
    built-in defaults rather than fail. An explicit ``$LOOMINUM_CONFIG`` that
    points at a missing file is returned as-is so the caller raises a clear
    "you asked for this file and it's not there" error.
    """
    explicit = os.getenv('LOOMINUM_CONFIG')
    if explicit:
        return Path(explicit)

    candidates: tp.List[Path] = [
        Path.cwd() / 'loominum.json',
        Path.cwd() / _CONFIG_RELPATH,
    ]

    xdg = os.getenv('XDG_CONFIG_HOME')
    xdg_base = Path(xdg) if xdg else Path.home() / '.config'
    candidates.append(xdg_base / 'loominum' / 'config.json')

    prj_dir = os.getenv('PRJ_DIR')
    if prj_dir:
        candidates.append(Path(prj_dir) / _CONFIG_RELPATH)

    for path in candidates:
        if path.is_file():
            return path
    return None


class LumConf:
    """Loominum configuration — construct with kwargs or load from a JSON file."""

    def __init__(self, *,
                 config_path: tp.Optional[tp.Union[str, Path]] = None,
                 server_url: str = "http://127.0.0.1:7773",
                 client_url: str = "http://127.0.0.1:7773",
                 log_file: str = "log/lum.log",
                 verbose: bool = False,
                 cert_sans: tp.Optional[str] = None,
                 data_dir: tp.Optional[tp.Union[str, Path]] = None):
        self._data: tp.Dict[str, tp.Any] = {
            'server_url': server_url,
            'client_url': client_url,
            'log_file': log_file,
            'verbose': verbose,
            'cert_sans': cert_sans,
        }

        self.config_path: tp.Optional[Path] = None
        if config_path is not None:
            self.config_path = Path(config_path)
            if not self.config_path.exists():
                raise FileNotFoundError(f"Config not found: {self.config_path}")
            with open(self.config_path, 'r') as f:
                self._data.update(json.load(f))

        self.data_dir: tp.Optional[Path] = (
            Path(data_dir) if data_dir
            else self.config_path.parent if self.config_path
            else None
        )

        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Let individual ``LOOMINUM_*`` env vars override loaded/default values.

        Highest precedence of all -- an env var wins over both the config file
        and the built-in default, so an operator can tweak one setting without
        editing or even having a config file.
        """
        for env_key, conf_key in _ENV_OVERRIDES.items():
            val = os.getenv(env_key)
            if val is None:
                continue
            self._data[conf_key] = _env_truthy(val) if conf_key == 'verbose' else val

    @classmethod
    def auto(cls, config_path: tp.Optional[tp.Union[str, Path]] = None,
             **overrides: tp.Any) -> "LumConf":
        """Build config by convention: discover a file, load it, apply env vars.

        Pass ``config_path`` to force a specific file (missing -> raises).
        Otherwise :func:`discover_config` looks in the conventional locations
        and, finding nothing, returns a defaults-only config. ``**overrides``
        are forwarded to ``__init__`` (e.g. CLI-supplied values).
        """
        if config_path is None:
            config_path = discover_config()
        return cls(config_path=config_path, **overrides)

    @property
    def server_url(self) -> str:
        return self._data['server_url']

    @property
    def client_url(self) -> str:
        return self._data['client_url']

    @property
    def cert_sans(self) -> tp.Optional[str]:
        return self._data.get('cert_sans')

    @property
    def verbose(self) -> bool:
        return self._data.get('verbose', False)

    @property
    def log_file(self) -> str:
        return self._data.get('log_file', 'log/lum.log')

    def get(self, key: str, default: tp.Any = None) -> tp.Any:
        return self._data.get(key, default)

    def set(self, key: str, value: tp.Any) -> None:
        self._data[key] = value

    def save(self) -> None:
        if self.config_path is None:
            raise RuntimeError("No config_path — cannot save")
        with open(self.config_path, 'w') as f:
            json.dump(self._data, f, indent=2)
