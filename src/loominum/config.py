"""
Configuration for Loominum.
"""

import json
import typing as tp

from pathlib import Path


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
