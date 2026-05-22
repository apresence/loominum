"""
Configuration management for the UnBilliCord server.

Loads settings from data/unbillicord/config.json using $PRJ_DIR environment variable.
"""

import os
import json
import typing as tp  # type: ignore[unusedImport]

from pathlib import Path


class UBCConfig:
    """UnBilliCord server configuration loaded from data/unbillicord/config.json."""
    
    def __init__(self, config_path: tp.Optional[Path] = None):
        """
        Load configuration from file.
        
        Args:
            config_path: Path to config file. If None, uses $PRJ_DIR/data/unbillicord/config.json
        
        Raises:
            RuntimeError: If PRJ_DIR environment variable is not set
            FileNotFoundError: If config file doesn't exist
        """
        if config_path is None:
            prj_dir = os.getenv('PRJ_DIR')
            if not prj_dir:
                raise RuntimeError(
                    "PRJ_DIR environment variable not set. "
                    "Please run: . .init"
                )
            config_path = Path(prj_dir) / 'data' / 'unbillicord' / 'config.json'
        
        self.config_path = Path(config_path)
        
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"UnBilliCord config not found: {self.config_path}\n"
                f"Expected location: $PRJ_DIR/data/unbillicord/config.json"
            )
        
        with open(self.config_path, 'r') as f:
            self._data: tp.Dict[str, tp.Any] = json.load(f)
    
    @property
    def server_url(self) -> str:
        """
        Server URL for binding (scheme://host:port/path).
        
        Examples:
            - 'https://0.0.0.0:7993' (bind all interfaces on port 7993, SSL)
            - 'http://127.0.0.1:7993/ubc' (localhost on port 7993, path /ubc)
        
        Raises:
            KeyError: If server_url not configured
        """
        if 'server_url' not in self._data:
            raise KeyError("server_url must be configured in data/unbillicord/config.json")
        return self._data['server_url']
    
    @property
    def client_url(self) -> str:
        """
        Client connection URL (what clients use to connect).
        
        May differ from server_url (e.g., server binds 0.0.0.0 but clients connect to hostname).
        
        Examples:
            - 'https://tau:7993' (client connects to hostname 'tau')
            - 'https://192.168.1.100:7993/ubc' (client connects via IP + path)
        
        Raises:
            KeyError: If client_url not configured
        """
        if 'client_url' not in self._data:
            raise KeyError("client_url must be configured in data/unbillicord/config.json")
        return self._data['client_url']
    
    @property
    def cert_sans(self) -> tp.Optional[str]:
        """
        Certificate Subject Alternative Names (comma-separated).
        
        If present, enables SSL/TLS. If None, server runs without SSL.
        
        Examples:
            - 'tau,myhost.local' (hostnames)
            - 'tau,192.168.1.100' (hostname + IP)
            - 'tau,myhost.local,192.168.1.100' (multiple)
        
        Returns:
            Comma-separated list of SANs, or None if SSL disabled
        """
        return self._data.get('cert_sans')
    
    @property
    def verbose(self) -> bool:
        """Verbose logging enabled."""
        return self._data.get('verbose', False)
    
    @property
    def log_file(self) -> str:
        """Log file path (relative to project root)."""
        return self._data.get('log_file', 'log/ubc.log')
    
    def get(self, key: str, default: tp.Any = None) -> tp.Any:
        """Get raw config value."""
        return self._data.get(key, default)
    
    def set(self, key: str, value: tp.Any) -> None:
        """Set config value (runtime only, not saved)."""
        self._data[key] = value
    
    def save(self) -> None:
        """Save current configuration to file."""
        with open(self.config_path, 'w') as f:
            json.dump(self._data, f, indent=2)
