"""Demo signing for band answers (v8). Each linked student device gets an HMAC-SHA256 key at link
time, sent once over the student's own authenticated socket and kept server side to verify answers.
A stand-in for device attestation (App Attest needs the paid program): labeled "demo signing"."""

import secrets

LABEL = "demo signing"


def new_key() -> tuple[str, str]:
    """(key_id, secret hex): a fresh 256-bit key."""
    return secrets.token_hex(8), secrets.token_hex(32)
