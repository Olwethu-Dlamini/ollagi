import pytest

from ollagi import config
from ollagi.watcher import GIB


def test_no_file_means_defaults(tmp_path):
    loaded = config.load(tmp_path / "missing.toml")
    assert loaded.port == 8765
    assert loaded.allowed_login is None
    assert loaded.projects == ()


def test_projects_and_access_settings_are_read():
    loaded = config.parse(
        """
        port = 9000
        allowed_login = "me@example.com"
        allowed_hosts = ["box.tail1.ts.net"]

        [[projects]]
        name = "simedia"
        directory = "/work/DATA!"

        [[projects]]
        name = "ollagi"
        directory = "/work/ollagi"
        """
    )
    assert loaded.port == 9000
    assert loaded.allowed_login == "me@example.com"
    assert loaded.allowed_hosts == ("box.tail1.ts.net",)
    assert [p.name for p in loaded.projects] == ["simedia", "ollagi"]
    assert loaded.projects[0].directory == "/work/DATA!"


def test_watcher_settings_default_to_freeze_and_can_be_changed():
    assert config.parse("").watcher.action == "freeze"
    # Fractions must survive: 0.75 GiB is 805306368 bytes, not 0.
    assert config.parse("").watcher.red_free == int(0.75 * GIB)
    assert config.parse("[watcher]\nred_free_gib = 0.5\n").watcher.red_free == GIB // 2
    custom = config.parse('[watcher]\naction = "warn"\nred_free_gib = 1.0\nred_seconds = 30\n').watcher
    assert (custom.action, custom.red_free, custom.red_seconds) == ("warn", GIB, 30.0)
    with pytest.raises(ValueError):
        config.parse('[watcher]\naction = "explode"\n')
