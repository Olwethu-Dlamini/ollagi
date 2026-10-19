from ollagi import config


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
