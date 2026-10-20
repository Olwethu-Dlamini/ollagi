from ollagi.access import check

TAILNET = ("laptop.example-tailnet.ts.net",)
ME = "me@example.com"


def test_the_laptops_own_browser_may_read_and_change():
    assert check("GET", {"host": "127.0.0.1:8765"}, ME, TAILNET).allowed
    assert check("POST", {"host": "localhost:8765", "x-ollagi": "1"}, ME, TAILNET).allowed


def test_my_phone_through_tailscale_serve_is_allowed():
    headers = {"host": "laptop.example-tailnet.ts.net", "tailscale-user-login": ME, "x-ollagi": "1"}
    assert check("POST", headers, ME, TAILNET).allowed


def test_someone_else_on_the_tailnet_is_refused():
    headers = {"host": "laptop.example-tailnet.ts.net", "tailscale-user-login": "guest@example.com"}
    decision = check("GET", headers, ME, TAILNET)
    assert not decision.allowed
    assert "guest@example.com" in decision.reason


def test_a_rebinding_website_is_refused_by_its_host_name():
    decision = check("GET", {"host": "evil.example:8765"}, ME, TAILNET)
    assert not decision.allowed
    assert "unknown host" in decision.reason


def test_a_change_without_the_ollagi_header_is_refused():
    decision = check("POST", {"host": "127.0.0.1:8765"}, ME, TAILNET)
    assert not decision.allowed
    assert "X-Ollagi" in decision.reason


def test_host_names_are_compared_without_case():
    assert check("GET", {"host": "LAPTOP.example-tailnet.ts.net"}, ME, TAILNET).allowed


# A terminal is opened over a WebSocket (docs/decisions/0018). Browsers send no preflight for
# WebSockets, so the X-Ollagi header proves nothing there; the Origin header is checked instead.

from ollagi.access import check_terminal


def test_the_page_may_open_a_terminal_from_its_own_address():
    assert check_terminal({"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}, ME, TAILNET).allowed
    headers = {"host": "laptop.example-tailnet.ts.net", "origin": "https://laptop.example-tailnet.ts.net",
               "tailscale-user-login": ME}
    assert check_terminal(headers, ME, TAILNET).allowed


def test_another_website_cannot_open_a_terminal_through_my_browser():
    decision = check_terminal({"host": "127.0.0.1:8765", "origin": "https://evil.example"}, ME, TAILNET)
    assert not decision.allowed
    assert "evil.example" in decision.reason


def test_a_terminal_without_an_origin_is_refused():
    decision = check_terminal({"host": "127.0.0.1:8765"}, ME, TAILNET)
    assert not decision.allowed
    assert "origin" in decision.reason


def test_a_terminal_follows_the_host_and_tailscale_rules_too():
    assert not check_terminal({"host": "evil.example", "origin": "http://evil.example"}, ME, TAILNET).allowed
    headers = {"host": "laptop.example-tailnet.ts.net", "origin": "https://laptop.example-tailnet.ts.net",
               "tailscale-user-login": "guest@example.com"}
    assert not check_terminal(headers, ME, TAILNET).allowed
