import os
import sys
import typing as tp  # type: ignore[unusedImport]

from pathlib import Path
from urllib.parse import urlparse

# Add src to path for imports
prj_dir = os.getenv('PRJ_DIR')
if not prj_dir:
    raise RuntimeError(
        "PRJ_DIR environment variable not set. "
        "Please run: . .init"
    )
sys.path.insert(0, str(Path(prj_dir) / 'src'))

from executor.config import ExecutorConfig

# Load executor configuration
config = ExecutorConfig()

# Parse server_url for binding
server_url_parsed = urlparse(config.server_url)
EXEC_LISTEN_HOST = server_url_parsed.hostname or '0.0.0.0'
EXEC_LISTEN_PORT = server_url_parsed.port or (28111 if server_url_parsed.scheme == 'https' else 28112)
EXEC_PATH_PREFIX = server_url_parsed.path.rstrip('/') if server_url_parsed.path else ''

# Client connection URL (for display in instructions and WebSocket connections)
CLIENT_CONNECTION_URL = config.client_url

