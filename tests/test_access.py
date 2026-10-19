from ollagi.access import check

TAILNET = ("omarchy.tail653118.ts.net",)
ME = "me@example.com"


def test_the_laptops_own_browser_may_read_and_change():
    assert check("GET", {"host": "127.0.0.1:8765"}, ME, TAILNET).allowed
    assert check("POST", {"host": "localhost:8765", "x-ollagi": "1"}, ME, TAILNET).allowed


def test_my_phone_through_tailscale_serve_is_allowed():
    headers = {"host": "omarchy.tail653118.ts.net", "tailscale-user-login": ME, "x-ollagi": "1"}
    assert check("POST", headers, ME, TAILNET).allowed


def test_someone_else_on_the_tailnet_is_refused():
    headers = {"host": "omarchy.tail653118.ts.net", "tailscale-user-login": "guest@example.com"}
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
    assert check("GET", {"host": "OMARCHY.tail653118.ts.net"}, ME, TAILNET).allowed
