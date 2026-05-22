"""
UnBilliCord — remote JavaScript execution for browser automation.

Provides WebSocket-based server and client for executing JavaScript
in an authenticated browser context.
"""

from .client import UBCClient
from .server import RemoteUBC, ubc, start_server, example_usage

__all__ = [
    'UBCClient',
    'RemoteUBC',
    'ubc',
    'start_server',
    'example_usage'
]
