"""Operators, roles and sessions.

Accounts live in a TOML file next to the database, managed with
`handover users`. Passwords are scrypt hashes; the session is a signed
cookie carrying only the name, and the role is read from the file on every
request, so removing someone or changing their role takes effect at once.
"""

import base64
import hashlib
import hmac
import secrets
import time
import tomllib
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


class Role(IntEnum):
    viewer = 1  # sees the floor and the incidents
    operator = 2  # pauses and resumes robots, downloads bundles
    driver = 3  # takes the wheel
    admin = 4  # zones and everything above


@dataclass(frozen=True)
class User:
    name: str
    role: Role


SESSION_HOURS = 12
N, R, P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return f"scrypt${N}${R}${P}${salt.hex()}${dk.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), dk)


class Users:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        raw = tomllib.loads(self.path.read_text(encoding="utf-8"))
        return {u["name"]: u for u in raw.get("user", [])}

    def _save(self, users: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(
            f'[[user]]\nname = "{u["name"]}"\nrole = "{u["role"]}"\nhash = "{u["hash"]}"\n\n' for u in users.values()
        )
        self.path.write_text("# managed by `handover users`\n\n" + body, encoding="utf-8")
        self.path.chmod(0o600)

    def add(self, name: str, role: str, password: str) -> None:
        if not name.replace("-", "").replace(".", "").isalnum():
            raise ValueError("names are letters, digits, dots and dashes")
        Role[role]
        users = self._load()
        users[name] = {"name": name, "role": role, "hash": hash_password(password)}
        self._save(users)

    def remove(self, name: str) -> bool:
        users = self._load()
        gone = users.pop(name, None)
        self._save(users)
        return gone is not None

    def get(self, name: str) -> User | None:
        u = self._load().get(name)
        return User(name, Role[u["role"]]) if u else None

    def all(self) -> list[User]:
        return [User(u["name"], Role[u["role"]]) for u in self._load().values()]

    def login(self, name: str, password: str) -> User | None:
        u = self._load().get(name)
        # hash anyway when the name is unknown, so timing does not tell which names exist
        stored = u["hash"] if u else hash_password("x")
        if check_password(password, stored) and u:
            return User(name, Role[u["role"]])
        return None


class Sessions:
    def __init__(self, key_path: Path):
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_bytes(secrets.token_bytes(32))
            key_path.chmod(0o600)
        self.key = key_path.read_bytes()

    def _sign(self, body: str) -> str:
        return base64.urlsafe_b64encode(hmac.digest(self.key, body.encode(), "sha256")).decode().rstrip("=")

    def issue(self, name: str) -> str:
        body = f"{name}|{int(time.time()) + SESSION_HOURS * 3600}"
        return f"{base64.urlsafe_b64encode(body.encode()).decode()}.{self._sign(body)}"

    def read(self, token: str | None) -> str | None:
        """The name in a valid, unexpired token."""
        if not token or "." not in token:
            return None
        packed, sig = token.rsplit(".", 1)
        try:
            body = base64.urlsafe_b64decode(packed.encode()).decode()
            name, exp = body.split("|")
        except ValueError:
            return None
        if not hmac.compare_digest(sig, self._sign(body)) or int(exp) < time.time():
            return None
        return name


class Throttle:
    """Slows down password guessing from one address: ten misses lock it for a minute."""

    def __init__(self, limit: int = 10, window: float = 60):
        self.limit, self.window = limit, window
        self.misses: dict[str, list[float]] = {}

    def blocked(self, who: str) -> bool:
        now = time.time()
        recent = [t for t in self.misses.get(who, []) if now - t < self.window]
        self.misses[who] = recent
        return len(recent) >= self.limit

    def miss(self, who: str) -> None:
        self.misses.setdefault(who, []).append(time.time())
