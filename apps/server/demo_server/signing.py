"""Demo signing for band answers (v8). Each linked student device gets an HMAC-SHA256 key at link
time, sent once over the student's own authenticated socket and kept server side to verify answers.
A stand-in for device attestation (App Attest needs the paid program): labeled "demo signing"."""

import hmac
import secrets
from datetime import datetime, timedelta

LABEL = "demo signing"


def new_key() -> tuple[str, str]:
    """(key_id, secret hex): a fresh 256-bit key."""
    return secrets.token_hex(8), secrets.token_hex(32)


BANDS = frozenset({"inside", "nearby", "away"})
WINDOW = timedelta(minutes=2)


def payload(request_id: str, band: str, answered_at: str) -> bytes:
    return f"{request_id}|{band}|{answered_at}".encode()


def sign(secret: str, request_id: str, band: str, answered_at: str) -> str:
    """HMAC-SHA256 hex of the answer; the phone computes the same with its copy of the key."""
    return hmac.new(
        bytes.fromhex(secret), payload(request_id, band, answered_at), "sha256"
    ).hexdigest()


class Verifier:
    """Accepts each signed answer once: right key, unaltered, a known band, answered within the
    window, and a request id not seen within the window. Seen ids live in memory only."""

    def __init__(self, window: timedelta = WINDOW) -> None:
        self.window = window
        self._seen: dict[str, datetime] = {}

    def seen(self, now: datetime) -> set[str]:
        self._seen = {r: at for r, at in self._seen.items() if now - at <= self.window}
        return set(self._seen)

    def check(
        self,
        secret: str,
        request_id: str,
        band: str,
        answered_at: str,
        signature: str,
        now: datetime,
    ) -> bool:
        if request_id in self.seen(now) or band not in BANDS:
            return False
        try:
            answered = datetime.fromisoformat(answered_at)
        except ValueError:
            return False
        if answered.tzinfo is None or abs(now - answered) > self.window:
            return False
        if not hmac.compare_digest(sign(secret, request_id, band, answered_at), signature):
            return False
        self._seen[request_id] = now
        return True
