"""
Remote JavaScript Executor for browser automation.

Provides WebSocket-based server and client for executing JavaScript
in an authenticated browser context.
"""

from .client import ExecutorClient
from .server import RemoteExecutor, executor, start_server, example_usage

__all__ = [
    'ExecutorClient',
    'RemoteExecutor',
    'executor',
    'start_server',
    'example_usage'
]
