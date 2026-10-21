import json
import time

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from ollagi import webpush

# The worked example of RFC 8291, section 5 and appendix A: every key and the salt are fixed there,
# so the encrypted message must come out byte for byte the same as the RFC's.
RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "auth_secret": "BTBZMqHH6r4Tts7J_aSIgg",
    "body": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
            "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
            "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def test_encryption_matches_the_rfc_example_byte_for_byte():
    body = webpush.encrypt(
        RFC["plaintext"],
        webpush.unb64(RFC["ua_public"]),
        webpush.unb64(RFC["auth_secret"]),
        sender=webpush.private_key_from_bytes(webpush.unb64(RFC["as_private"])),
        salt=webpush.unb64(RFC["salt"]),
    )
    assert webpush.b64(body) == RFC["body"]


def test_a_fresh_message_can_be_read_back_by_the_receiver_only():
    # No fixed keys: a new sender key and salt every time, as in real use. The receiver's side is
    # written out here from the RFC, so this checks the sender against an independent reading.
    receiver = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    body = webpush.encrypt(b"needs you: Allow edit?", webpush.public_bytes(receiver.public_key()), auth)
    assert webpush.decrypt(body, receiver, auth) == b"needs you: Allow edit?"
    with pytest.raises(Exception):
        webpush.decrypt(body, ec.generate_private_key(ec.SECP256R1()), auth)
    with pytest.raises(Exception):
        webpush.decrypt(body, receiver, b"another secret!!")


def test_the_vapid_header_is_a_signed_token_for_the_push_service():
    key = ec.generate_private_key(ec.SECP256R1())
    now = 1_700_000_000
    header = webpush.vapid_authorization(key, "https://fcm.googleapis.com/fcm/send/abc:def", now)
    assert header.startswith("vapid t=")
    token, public = header.removeprefix("vapid t=").split(", k=")
    assert webpush.unb64(public) == webpush.public_bytes(key.public_key())

    head, claims, signature = token.split(".")
    assert json.loads(webpush.unb64(head)) == {"typ": "JWT", "alg": "ES256"}
    claims = json.loads(webpush.unb64(claims))
    assert claims["aud"] == "https://fcm.googleapis.com"  # the push service's origin, nothing more
    assert now < claims["exp"] <= now + 24 * 3600         # the push service refuses a longer one
    # ES256: the signature is r and s, 32 bytes each, over "header.claims".
    raw = webpush.unb64(signature)
    assert len(raw) == 64
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{token.split('.')[1]}".encode(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        key.public_key().verify(der, b"something else", ec.ECDSA(hashes.SHA256()))


def test_the_key_is_made_once_kept_private_and_read_back(tmp_path):
    path = tmp_path / "push" / "vapid.pem"
    first = webpush.load_or_create_key(path)
    assert path.stat().st_mode & 0o777 == 0o600
    again = webpush.load_or_create_key(path)
    assert webpush.public_bytes(first.public_key()) == webpush.public_bytes(again.public_key())


@pytest.mark.parametrize("url, allowed", [
    ("https://fcm.googleapis.com/fcm/send/abc", True),            # Chrome on Android
    ("https://updates.push.services.mozilla.com/wpush/v2/x", True),  # Firefox
    ("https://web.push.apple.com/QGx", True),                     # Safari
    ("http://fcm.googleapis.com/fcm/send/abc", False),            # not https
    ("https://127.0.0.1:8765/api/sessions/demo/stop", False),     # this server
    ("https://fcm.googleapis.com.evil.example/x", False),         # looks alike, is not
    ("https://example.com/push", False),
])
def test_only_known_push_services_are_sent_to(url, allowed):
    assert webpush.known_push_service(url) is allowed


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_send_posts_an_encrypted_body_with_the_right_headers():
    receiver = ec.generate_private_key(ec.SECP256R1())
    sub = webpush.Subscription("https://fcm.googleapis.com/fcm/send/x",
                               webpush.b64(webpush.public_bytes(receiver.public_key())), webpush.b64(b"0123456789abcdef"))
    seen = {}

    def opener(request, timeout):
        seen.update(url=request.full_url, headers=dict(request.header_items()), body=request.data, timeout=timeout)
        return FakeResponse(201)

    webpush.send(sub, {"title": "demo", "body": "needs you"}, ec.generate_private_key(ec.SECP256R1()),
                 now=time.time(), opener=opener)
    assert seen["url"] == sub.endpoint
    assert seen["headers"]["Content-encoding"] == "aes128gcm"
    assert seen["headers"]["Ttl"] == str(webpush.TTL_SECONDS)
    assert seen["headers"]["Urgency"] == "high"
    assert seen["headers"]["Authorization"].startswith("vapid t=")
    message = json.loads(webpush.decrypt(seen["body"], receiver, b"0123456789abcdef"))
    assert message == {"title": "demo", "body": "needs you"}


def test_a_subscription_the_push_service_has_forgotten_says_so():
    import urllib.error

    def gone(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 410, "Gone", {}, None)

    sub = webpush.Subscription("https://fcm.googleapis.com/fcm/send/x",
                               webpush.b64(webpush.public_bytes(ec.generate_private_key(ec.SECP256R1()).public_key())),
                               webpush.b64(b"0123456789abcdef"))
    with pytest.raises(webpush.Gone):
        webpush.send(sub, {"title": "t"}, ec.generate_private_key(ec.SECP256R1()), now=time.time(), opener=gone)


def test_send_refuses_an_unknown_address_before_any_request():
    sub = webpush.Subscription("https://127.0.0.1/x", "AA", "AA")
    with pytest.raises(ValueError):
        webpush.send(sub, {"title": "t"}, ec.generate_private_key(ec.SECP256R1()), now=time.time(),
                     opener=lambda *a, **k: pytest.fail("no request may be made"))
