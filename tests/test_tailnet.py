import json

from ollagi.tailnet import Tailnet, parse_status

# The parts of `tailscale status --json` that ollagi reads (other fields trimmed).
STATUS = json.dumps({
    "Self": {"HostName": "omarchy", "DNSName": "omarchy.tail653118.ts.net.", "UserID": 42},
    "User": {"42": {"LoginName": "me@example.com"}, "7": {"LoginName": "someone@else.com"}},
})


def test_host_and_owner_login_are_read_and_the_final_dot_dropped():
    assert parse_status(STATUS) == Tailnet(host="omarchy.tail653118.ts.net", login="me@example.com")


def test_urls():
    t = Tailnet(host="omarchy.tail653118.ts.net", login="me@example.com")
    assert t.url() == "http://omarchy.tail653118.ts.net"
    assert t.url(https=True) == "https://omarchy.tail653118.ts.net"
    assert t.url(port=8765) == "http://omarchy.tail653118.ts.net:8765"


def test_without_config_only_the_tailnet_owner_and_name_are_allowed():
    from ollagi.config import Config
    from ollagi.serve import with_tailnet_defaults

    t = Tailnet(host="omarchy.tail653118.ts.net", login="me@example.com")
    settings = with_tailnet_defaults(Config(), t)
    assert settings.allowed_hosts == ("omarchy.tail653118.ts.net",)
    assert settings.allowed_login == "me@example.com"


def test_config_values_win_over_tailnet_defaults():
    from ollagi.config import Config
    from ollagi.serve import with_tailnet_defaults

    t = Tailnet(host="omarchy.tail653118.ts.net", login="me@example.com")
    settings = with_tailnet_defaults(Config(allowed_login="other@example.com", allowed_hosts=("x.ts.net",)), t)
    assert settings.allowed_login == "other@example.com"
    assert settings.allowed_hosts == ("x.ts.net",)
