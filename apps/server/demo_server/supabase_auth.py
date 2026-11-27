"""Supabase Auth sessions (AUTH_MODE=supabase): the server trusts an access token only after
checking its signature (project signing keys from JWKS, or the legacy HS256 secret), audience,
expiry and issuer. A refused token logs only the reason kind, never the token or the email."""

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt

log = logging.getLogger(__name__)
AUDIENCE = "authenticated"
ASYMMETRIC = ["ES256", "RS256", "EdDSA"]
JWKS_TTL = 600.0  # seconds; an unknown key id refetches at most once a minute
REFETCH_GAP = 60.0


class SessionError(Exception):
    """A refused session; `kind` is safe to log (no token, no email)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class Session:
    user_id: str
    email: str


def fetch_jwks(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "campus-safety-signal-server"})  # noqa: S310 (https project URL)
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        data: dict[str, Any] = json.load(response)
    return data


class Verifier:
    def __init__(
        self,
        project_url: str,
        hs256_secret: str | None = None,
        fetch: Callable[[str], dict[str, Any]] = fetch_jwks,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        base = project_url.rstrip("/")
        self.issuer = f"{base}/auth/v1"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._secret = hs256_secret or None
        self._fetch, self._clock = fetch, clock
        self._keys: dict[str, Any] = {}
        self._fetched_at = -1e12
        self._lock = threading.Lock()

    def _key(self, kid: str | None) -> Any:
        with self._lock:
            age = self._clock() - self._fetched_at
            stale = age > JWKS_TTL or (kid not in self._keys and age > REFETCH_GAP)
            if stale:
                try:
                    found = self._fetch(self.jwks_url).get("keys", [])
                except Exception as exc:  # network or JSON trouble: keep the old keys
                    log.warning("signing keys unavailable: %s", type(exc).__name__)
                else:
                    self._keys = {k.get("kid"): jwt.PyJWK(k).key for k in found if k.get("kid")}
                    self._fetched_at = self._clock()
            if kid not in self._keys:
                raise SessionError("unknown_key")
            return self._keys[kid]

    def verify(self, token: str) -> Session:
        try:
            return self._verify(token)
        except SessionError as exc:
            log.info("session refused: %s", exc.kind)
            raise

    def _verify(self, token: str) -> Session:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise SessionError("malformed") from None
        alg = header.get("alg")
        if alg == "HS256" and self._secret:
            key: Any = self._secret
        elif alg in ASYMMETRIC:
            key = self._key(header.get("kid"))
        else:
            raise SessionError("algorithm")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience=AUDIENCE,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
                leeway=30,
            )
        except jwt.ExpiredSignatureError:
            raise SessionError("expired") from None
        except jwt.InvalidAudienceError:
            raise SessionError("audience") from None
        except jwt.InvalidIssuerError:
            raise SessionError("issuer") from None
        except jwt.InvalidSignatureError:
            raise SessionError("signature") from None
        except jwt.PyJWTError:
            raise SessionError("invalid") from None
        email = str(claims.get("email") or "").strip().lower()
        if not email or claims.get("is_anonymous"):
            raise SessionError("no_email")
        return Session(user_id=str(claims["sub"]), email=email)


def delete_user(project_url: str, service_key: str, user_id: str) -> None:
    """Delete a Supabase Auth user (admin API, service key). Already gone counts as done."""
    url = f"{project_url.rstrip('/')}/auth/v1/admin/users/{urllib.parse.quote(user_id, safe='')}"
    request = urllib.request.Request(  # noqa: S310 (https project URL)
        url,
        method="DELETE",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "User-Agent": "campus-safety-signal-server",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10):  # noqa: S310
            return
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return
        raise RuntimeError(f"auth admin HTTP {exc.code}") from None


def retry_deletions(store: Any, project_url: str, service_key: str) -> int:
    """Try the Auth users still waiting; returns how many are still pending."""
    for user_id in store.auth_deletions():
        try:
            delete_user(project_url, service_key, user_id)
        except Exception as exc:
            store.auth_deletion_failed(user_id, type(exc).__name__)
            log.warning("auth user not deleted yet (%s)", type(exc).__name__)
        else:
            store.auth_deletion_done(user_id)
    return len(store.auth_deletions())
