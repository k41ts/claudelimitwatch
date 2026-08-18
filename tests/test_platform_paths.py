"""Where files live on each platform.

Windows behaviour must not drift (existing installs would lose their settings),
and Linux must follow the XDG base directory spec.
"""

import importlib

import pytest

from climitwatch import config


@pytest.fixture()
def reload_config():
    yield
    importlib.reload(config)


def test_windows_keeps_everything_under_localappdata(monkeypatch, tmp_path, reload_config):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    assert config.app_dir() == tmp_path / "Local" / "ClimitWatch"
    assert config.config_dir() == config.app_dir()
    assert config.settings_path().parent == config.app_dir()
    assert config.accounts_path().name == "accounts.dat"


def test_linux_follows_xdg(monkeypatch, tmp_path, reload_config):
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    assert config.app_dir() == tmp_path / "data" / "climitwatch"
    assert config.config_dir() == tmp_path / "cfg" / "climitwatch"
    assert config.settings_path() == tmp_path / "cfg" / "climitwatch" / "settings.json"
    assert config.cache_path() == tmp_path / "data" / "climitwatch" / "snapshots.json"


def test_linux_defaults_without_xdg_vars(monkeypatch, tmp_path, reload_config):
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))

    assert config.app_dir() == tmp_path / ".local" / "share" / "climitwatch"
    assert config.config_dir() == tmp_path / ".config" / "climitwatch"


def test_directories_are_created(monkeypatch, tmp_path, reload_config):
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    assert config.app_dir().is_dir()
    assert config.config_dir().is_dir()


def test_settings_round_trip_on_linux_paths(monkeypatch, tmp_path, reload_config):
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    settings = config.Settings()
    settings.poll_seconds = 420
    settings.save()

    assert config.settings_path().exists()
    assert config.Settings.load().poll_seconds == 420
