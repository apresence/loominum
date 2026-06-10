"""Tests for conventional config discovery and env overrides (config.py)."""

import json
import os
from pathlib import Path

import pytest

from loominum.config import LumConf, discover_config


# Env vars that influence discovery / overrides -- cleared before each test so a
# stray value in the runner's environment can't leak in.
_RELEVANT_ENV = [
    'LOOMINUM_CONFIG', 'PRJ_DIR', 'XDG_CONFIG_HOME',
    'LOOMINUM_SERVER_URL', 'LOOMINUM_CLIENT_URL', 'LOOMINUM_LOG_FILE',
    'LOOMINUM_CERT_SANS', 'LOOMINUM_VERBOSE',
]

DEFAULT_SERVER_URL = "http://127.0.0.1:7773"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for key in _RELEVANT_ENV:
        monkeypatch.delenv(key, raising=False)
    # Run inside an empty cwd so on-disk ./loominum.json etc. don't interfere.
    monkeypatch.chdir(tmp_path)
    yield


def _write_config(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


# --- discover_config precedence -------------------------------------------

def test_nothing_found_returns_none():
    assert discover_config() is None


def test_explicit_env_path_wins(monkeypatch, tmp_path):
    target = _write_config(tmp_path / 'custom.json', {'server_url': 'http://explicit:1'})
    monkeypatch.setenv('LOOMINUM_CONFIG', str(target))
    assert discover_config() == target


def test_explicit_env_path_returned_even_if_missing(monkeypatch, tmp_path):
    missing = tmp_path / 'nope.json'
    monkeypatch.setenv('LOOMINUM_CONFIG', str(missing))
    # Returned as-is so the caller raises a clear error.
    assert discover_config() == missing


def test_cwd_loominum_json_discovered(tmp_path):
    target = _write_config(tmp_path / 'loominum.json', {'server_url': 'http://cwd:1'})
    assert discover_config() == target


def test_cwd_data_dir_discovered(tmp_path):
    target = _write_config(tmp_path / 'data' / 'loominum' / 'config.json',
                           {'server_url': 'http://cwddata:1'})
    assert discover_config() == target


def test_xdg_discovered(monkeypatch, tmp_path):
    xdg = tmp_path / 'xdg'
    target = _write_config(xdg / 'loominum' / 'config.json', {'server_url': 'http://xdg:1'})
    monkeypatch.setenv('XDG_CONFIG_HOME', str(xdg))
    assert discover_config() == target


def test_prj_dir_back_compat(monkeypatch, tmp_path):
    prj = tmp_path / 'prj'
    target = _write_config(prj / 'data' / 'loominum' / 'config.json',
                           {'server_url': 'http://prj:1'})
    monkeypatch.setenv('PRJ_DIR', str(prj))
    assert discover_config() == target


def test_cwd_beats_prj_dir(monkeypatch, tmp_path):
    cwd_cfg = _write_config(tmp_path / 'loominum.json', {'server_url': 'http://cwd:1'})
    prj = tmp_path / 'prj'
    _write_config(prj / 'data' / 'loominum' / 'config.json', {'server_url': 'http://prj:1'})
    monkeypatch.setenv('PRJ_DIR', str(prj))
    assert discover_config() == cwd_cfg


# --- LumConf.auto: discover + load + defaults ------------------------------

def test_auto_defaults_when_nothing_found():
    conf = LumConf.auto()
    assert conf.server_url == DEFAULT_SERVER_URL  # no raise, sane default


def test_auto_loads_discovered_file(tmp_path):
    _write_config(tmp_path / 'loominum.json', {'server_url': 'http://loaded:2'})
    assert LumConf.auto().server_url == 'http://loaded:2'


def test_auto_explicit_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        LumConf.auto(config_path=tmp_path / 'absent.json')


# --- env overrides ---------------------------------------------------------

def test_env_override_without_file(monkeypatch):
    monkeypatch.setenv('LOOMINUM_SERVER_URL', 'http://envonly:3')
    assert LumConf.auto().server_url == 'http://envonly:3'


def test_env_override_beats_file(monkeypatch, tmp_path):
    _write_config(tmp_path / 'loominum.json', {'server_url': 'http://file:4'})
    monkeypatch.setenv('LOOMINUM_SERVER_URL', 'http://env:4')
    assert LumConf.auto().server_url == 'http://env:4'


def test_env_verbose_coerced_to_bool(monkeypatch):
    monkeypatch.setenv('LOOMINUM_VERBOSE', 'true')
    assert LumConf.auto().verbose is True
    monkeypatch.setenv('LOOMINUM_VERBOSE', 'off')
    assert LumConf.auto().verbose is False
