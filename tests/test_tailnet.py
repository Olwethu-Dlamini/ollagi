import json

from ollagi.tailnet import Tailnet, parse_serve_status, parse_status

# The parts of `tailscale status --json` that ollagi reads (other fields trimmed).
STATUS = json.dumps({
    "Self": {"HostName": "laptop", "DNSName": "laptop.example-tailnet.ts.net.", "UserID": 42},
    "User": {"42": {"LoginName": "me@example.com"}, "7": {"LoginName": "someone@else.com"}},
})


def test_host_and_owner_login_are_read_and_the_final_dot_dropped():
    assert parse_status(STATUS) == Tailnet(host="laptop.example-tailnet.ts.net", login="me@example.com")


def test_urls():
    t = Tailnet(host="laptop.example-tailnet.ts.net", login="me@example.com")
    assert t.url() == "http://laptop.example-tailnet.ts.net"
    assert t.url(https=True) == "https://laptop.example-tailnet.ts.net"
    assert t.url(port=8765) == "http://laptop.example-tailnet.ts.net:8765"


def test_without_config_only_the_tailnet_owner_and_name_are_allowed():
    from ollagi.config import Config
    from ollagi.serve import with_tailnet_defaults

    t = Tailnet(host="laptop.example-tailnet.ts.net", login="me@example.com")
    settings = with_tailnet_defaults(Config(), t)
    assert settings.allowed_hosts == ("laptop.example-tailnet.ts.net",)
    assert settings.allowed_login == "me@example.com"


def test_config_values_win_over_tailnet_defaults():
    from ollagi.config import Config
    from ollagi.serve import with_tailnet_defaults

    t = Tailnet(host="laptop.example-tailnet.ts.net", login="me@example.com")
    settings = with_tailnet_defaults(Config(allowed_login="other@example.com", allowed_hosts=("x.ts.net",)), t)
    assert settings.allowed_login == "other@example.com"
    assert settings.allowed_hosts == ("x.ts.net",)


# `tailscale serve status --json` on this laptop once HTTPS was on (2026-10-21), name replaced.
SERVING_HTTPS = json.dumps({
    "TCP": {"443": {"HTTPS": True}},
    "Web": {"laptop.example-tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}},
})
SERVING_HTTP = json.dumps({
    "TCP": {"80": {"HTTP": True}},
    "Web": {"laptop.example-tailnet.ts.net:80": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}},
})


def test_the_phone_address_is_https_once_tailscale_serves_https():
    assert parse_serve_status(SERVING_HTTPS) is True
    assert parse_serve_status(SERVING_HTTP) is False
    assert parse_serve_status("{}") is False  # nothing served
    assert parse_serve_status("not json") is False


def test_the_url_follows_what_is_served():
    t = Tailnet(host="laptop.example-tailnet.ts.net", login="me@example.com", https=True)
    assert t.url() == "https://laptop.example-tailnet.ts.net"
    assert t.url(https=False) == "http://laptop.example-tailnet.ts.net"
