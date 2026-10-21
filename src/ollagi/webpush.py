"""Web Push: send a notification to a phone through its browser's push service (docs/decisions/0024).

How a notification travels:

1. The page asks the browser to subscribe. The browser answers with an *endpoint* (an https address
   at its push service: Google's for Chrome on Android) and two keys of the phone's own: `p256dh`,
   a public key, and `auth`, a 16-byte secret. The page gives these to this server.
2. To notify, this server encrypts the message to the phone's keys (RFC 8291) and POSTs it to the
   endpoint. The push service cannot read it; it only sees how big it is and when it was sent.
3. The push service wakes the phone's browser, which decrypts the message and hands it to our
   service worker (static/sw.js), which shows it.

The push service also wants to know who is sending, so a stranger who learned the endpoint cannot
use it: each request carries a short token signed with this server's own key (VAPID, RFC 8292).
The page subscribes with that key's public half, and the push service checks the two match.

The encryption, step by step (RFC 8291 section 3, and RFC 8188 for the message layout):

- ECDH: a fresh key pair for this one message, combined with the phone's public key, gives a
  secret that only this server and the phone can compute.
- HKDF (HMAC-SHA-256, written out below with the standard library) mixes that secret with the
  phone's `auth` secret and a random salt into a 16-byte AES key and a 12-byte nonce.
- AES-128-GCM encrypts the message and adds a tag, so any change on the way is detected.

Only ECDH and AES-GCM come from the `cryptography` package; Python's standard library has neither.
"""

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_SIZE = 4096
# The phone keeps a message this long while it is off or out of reach; an older one is stale.
TTL_SECONDS = 6 * 3600
# Push services accept 4096 bytes; the header (86) and AES-GCM's tag (16) and padding (1) take some.
MAX_MESSAGE = 3900
# Where real browsers' push services live. A subscription may only point at one of these, so a
# made-up subscription cannot turn this server into something that sends requests anywhere else.
# jmt17.google.com is where Chromium builds without Google's API keys subscribe (Arch's, for one);
# Chrome itself, on Android too, uses fcm.googleapis.com.
PUSH_SERVICES = ("fcm.googleapis.com", "jmt17.google.com", "push.services.mozilla.com", "push.apple.com",
                 "notify.windows.com")


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str  # the phone's public key, base64url
    auth: str    # the phone's 16-byte secret, base64url


class Gone(Exception):
    """The push service no longer knows this subscription (the app was uninstalled, or it expired)."""


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    text = "".join(text.split())
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    """A P-256 public key as 65 bytes: 0x04, then x and y (the "uncompressed point")."""
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def private_key_from_bytes(raw: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _keys(shared: bytes, auth: bytes, ua_public: bytes, as_public: bytes, salt: bytes) -> tuple[bytes, bytes]:
    """HKDF twice: first the phone's auth secret is mixed in, then the salt gives the key and nonce.
    Each HKDF here needs one 32-byte block, which is HMAC(prk, info + 0x01), cut to length."""
    prk_key = _hmac(auth, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    return cek, nonce


def encrypt(plaintext: bytes, ua_public: bytes, auth: bytes, sender=None, salt: bytes | None = None) -> bytes:
    """The body of a push message. `sender` and `salt` are only passed by tests; real messages get
    fresh ones every time, so no two messages are encrypted alike."""
    if len(plaintext) > MAX_MESSAGE:
        raise ValueError(f"a push message holds at most {MAX_MESSAGE} bytes")
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = public_bytes(sender.public_key())
    shared = sender.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    cek, nonce = _keys(shared, auth, ua_public, as_public, salt)
    # 0x02 marks the last (here: only) record; it comes before any padding.
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


def decrypt(body: bytes, receiver: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
    """The phone's side, for tests: what a browser does with a message it receives."""
    salt, id_length = body[:16], body[20]
    as_public, ciphertext = body[21:21 + id_length], body[21 + id_length:]
    shared = receiver.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    cek, nonce = _keys(shared, auth, public_bytes(receiver.public_key()), as_public, salt)
    padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return padded.rstrip(b"\x00")[:-1]


def vapid_authorization(key: ec.EllipticCurvePrivateKey, endpoint: str, now: float) -> str:
    """The Authorization header that says this server sent the message (RFC 8292).

    A JSON Web Token: header and claims as base64url JSON, joined by a dot, then signed with ES256
    (ECDSA on P-256 with SHA-256). `aud` is the push service's origin; `exp` may be at most 24 hours
    ahead. The token goes with the public key, so the push service can check it against the key
    the page subscribed with."""
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(now) + 12 * 3600}
    signing_input = ".".join(b64(json.dumps(p, separators=(",", ":")).encode())
                             for p in ({"typ": "JWT", "alg": "ES256"}, claims))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = f"{signing_input}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={b64(public_bytes(key.public_key()))}"


def load_or_create_key(path: Path) -> ec.EllipticCurvePrivateKey:
    """This server's VAPID key. Made once; if it changed, every phone would have to subscribe again."""
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Created readable by my user only, before anything is written into it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(pem)
    return key


def known_push_service(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (parts.scheme == "https" and parts.port in (None, 443)
            and any(host == s or host.endswith("." + s) for s in PUSH_SERVICES))


def send(sub: Subscription, message: dict, key: ec.EllipticCurvePrivateKey, now: float,
         opener=urllib.request.urlopen) -> None:
    """Encrypt `message` (JSON) to the phone and hand it to its push service."""
    if not known_push_service(sub.endpoint):
        raise ValueError(f"not a known push service: {sub.endpoint}")
    body = encrypt(json.dumps(message).encode(), unb64(sub.p256dh), unb64(sub.auth))
    request = urllib.request.Request(sub.endpoint, data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDS),
        "Urgency": "high",  # deliver now, even when the phone is saving battery
        "Authorization": vapid_authorization(key, sub.endpoint, now),
    })
    try:
        with opener(request, timeout=10):
            pass
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):
            raise Gone(sub.endpoint) from error
        raise RuntimeError(f"push service answered {error.code} {error.reason}") from error
