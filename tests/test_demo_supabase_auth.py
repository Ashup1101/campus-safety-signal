"""Supabase session checks with locally generated keys: no network, no real project."""

import logging
import secrets
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from demo_server.supabase_auth import Session, SessionError, Verifier

PROJECT = "https://example-project.supabase.test"
ISSUER = f"{PROJECT}/auth/v1"
EMAIL = "Pat@Example.test"


def _key_pair(kid: str) -> tuple[Any, dict[str, Any]]:
    private = ec.generate_private_key(ec.SECP256R1())
    public: dict[str, Any] = ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    return private, {**public, "kid": kid, "alg": "ES256", "use": "sig"}


PRIVATE, JWK = _key_pair("k1")


def _token(key: Any = PRIVATE, kid: str = "k1", alg: str = "ES256", **claims: Any) -> str:
    body = {
        "sub": "user-1",
        "email": EMAIL,
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "role": "authenticated",
    } | claims
    return jwt.encode(body, key, algorithm=alg, headers={"kid": kid})


class Keys:
    def __init__(self, *jwks: dict[str, Any]) -> None:
        self.jwks, self.calls = list(jwks), 0

    def __call__(self, url: str) -> dict[str, Any]:
        assert url == f"{ISSUER}/.well-known/jwks.json"
        self.calls += 1
        return {"keys": self.jwks}


def test_a_valid_token_gives_the_lower_cased_email() -> None:
    verifier = Verifier(PROJECT, fetch=Keys(JWK))
    assert verifier.verify(_token()) == Session("user-1", "pat@example.test")


@pytest.mark.parametrize(
    ("token", "kind"),
    [
        (lambda: _token(exp=int(time.time()) - 120), "expired"),
        (lambda: _token(aud="anon"), "audience"),
        (lambda: _token(iss="https://other.supabase.test/auth/v1"), "issuer"),
        (lambda: _token(key=_key_pair("k1")[0]), "signature"),  # forged: another key, same kid
        (lambda: _token(kid="k9"), "unknown_key"),
        (lambda: _token(email=""), "no_email"),
        (lambda: _token(is_anonymous=True), "no_email"),
        (lambda: _token(key=secrets.token_urlsafe(32), alg="HS256"), "algorithm"),
        (lambda: "not.a.token", "malformed"),
    ],
)
def test_bad_tokens_are_refused_with_a_reason_kind_only(
    token: Any, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    raw = token()
    with pytest.raises(SessionError) as found:
        Verifier(PROJECT, fetch=Keys(JWK)).verify(raw)
    assert found.value.kind == kind
    assert raw not in caplog.text and "pat@example" not in caplog.text.lower()


def test_legacy_hs256_secret_is_supported() -> None:
    secret = secrets.token_urlsafe(32)  # made up per run
    verifier = Verifier(PROJECT, hs256_secret=secret, fetch=Keys())
    assert verifier.verify(_token(key=secret, alg="HS256")).email == "pat@example.test"
    with pytest.raises(SessionError, match="signature"):
        verifier.verify(_token(key=secrets.token_urlsafe(32), alg="HS256"))


def test_keys_are_cached_and_a_new_key_id_refetches_after_a_minute() -> None:
    now = [0.0]
    second_private, second = _key_pair("k2")
    keys = Keys(JWK)
    verifier = Verifier(PROJECT, fetch=keys, clock=lambda: now[0])
    for _ in range(5):
        verifier.verify(_token())
    assert keys.calls == 1
    keys.jwks.append(second)  # the project rotates in a new signing key
    now[0] = 30.0
    with pytest.raises(SessionError, match="unknown_key"):
        verifier.verify(_token(key=second_private, kid="k2"))  # too soon to refetch
    now[0] = 90.0
    assert verifier.verify(_token(key=second_private, kid="k2")).user_id == "user-1"
    assert keys.calls == 2


def test_an_unreachable_key_endpoint_refuses_without_crashing() -> None:
    def down(url: str) -> dict[str, Any]:
        raise OSError("network down")

    with pytest.raises(SessionError, match="unknown_key"):
        Verifier(PROJECT, fetch=down).verify(_token())


def test_auth_check_names_settings_without_values() -> None:
    from demo_server.supabase_auth import check

    env = {
        "AUTH_MODE": "supabase",
        "EMAIL_MODE": "smtp",
        "SUPABASE_URL": PROJECT,
        "SUPABASE_SERVICE_ROLE_KEY": "value-that-must-not-print",
        "SMTP_HOST": "smtp.example.test",
    }
    ok, lines = check(env, fetch=Keys(JWK))
    text = "\n".join(lines)
    assert not ok and "auth-check: FAILED" in text
    assert "SMTP_PASSWORD: missing" in text and "SUPABASE_SERVICE_ROLE_KEY: set" in text
    assert "signing keys: 1 found" in text
    assert "value-that-must-not-print" not in text and "smtp.example.test" not in text


def test_auth_check_passes_in_demo_modes_and_reports_unreachable_keys() -> None:
    from demo_server.supabase_auth import check

    assert check({})[0] is True

    def down(url: str) -> dict[str, Any]:
        raise OSError("offline")

    ok, lines = check(
        {"AUTH_MODE": "supabase", "SUPABASE_URL": PROJECT, "SUPABASE_SERVICE_ROLE_KEY": "x"}, down
    )
    assert not ok and "signing keys: unreachable (OSError)" in lines
