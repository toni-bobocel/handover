import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from handover.app import create
from handover.auth import Sessions, Users, check_password, hash_password

FLEET = """
[site]
name = "test"
data = "{data}"

[[robot]]
id = "bot"
protocol = "rest"
command_url = "http://127.0.0.1:9/commands"
token = "robot-secret"
"""


@pytest.fixture
def site(tmp_path):
    cfg = tmp_path / "fleet.toml"
    cfg.write_text(FLEET.format(data=(tmp_path / "data").as_posix()), encoding="utf-8")
    users = Users(tmp_path / "data" / "users.toml")
    users.add("ana", "driver", "correct horse battery")
    users.add("ben", "viewer", "another long password")
    with TestClient(create(cfg)) as client:
        yield client, users


def login(client, name, password):
    return client.post("/api/login", json={"name": name, "password": password})


def test_hashes_are_salted_and_checked():
    a, b = hash_password("same"), hash_password("same")
    assert a != b
    assert check_password("same", a) and not check_password("other", a)


def test_nothing_without_a_session(site):
    client, _ = site
    assert client.get("/api/site").status_code == 401
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("/api/stream") as ws:
        ws.receive_text()
    assert e.value.code == 4401


def test_roles_are_enforced(site):
    client, _ = site
    assert login(client, "ben", "another long password").status_code == 200
    assert client.get("/api/site").status_code == 200
    assert client.post("/api/robots/bot/pause").status_code == 403
    assert client.put("/api/zones/z", json={"name": "z", "polygon": [[0, 0], [1, 0], [1, 1]]}).status_code == 403
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("/api/teleop/bot") as ws:
        ws.receive_text()
    assert e.value.code == 4403


def test_removing_a_user_ends_their_session(site):
    client, users = site
    login(client, "ben", "another long password")
    assert client.get("/api/me").json()["role"] == "viewer"
    users.remove("ben")
    assert client.get("/api/me").status_code == 401


def test_guessing_is_throttled(site):
    client, _ = site
    for _ in range(10):
        assert login(client, "ana", "wrong").status_code == 401
    assert login(client, "ana", "correct horse battery").status_code == 429


def test_robots_need_their_token(site):
    client, _ = site
    body = {"x": 1, "y": 2}
    assert client.post("/ingest/bot", json=body).status_code == 401
    assert client.post("/ingest/bot", json=body, headers={"authorization": "Bearer robot-secret"}).status_code == 200


def test_tampered_or_expired_tokens_are_refused(tmp_path, monkeypatch):
    s = Sessions(tmp_path / "k")
    t = s.issue("ana")
    assert s.read(t) == "ana"
    assert s.read(t[:-2] + "xx") is None
    monkeypatch.setattr("handover.auth.time.time", lambda: 10**10)
    assert s.read(t) is None
