"""The demo stack, end to end, against `docker compose --profile demo up`.

Every robot reports through its own protocol, a pallet blocks the humanoid,
it asks for help, and the sealed bundle must hold its camera and verify.
Run by CI; locally: docker compose --profile demo up -d && python scripts/e2e.py
"""

import io
import json
import subprocess
import sys
import time
import zipfile

import httpx

CORE = "http://localhost:8080"
ROBOT = "Humanoid-Inspect-02"


def wait(what, check, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            got = check()
            if got:
                print(f"ok    {what}")
                return got
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        time.sleep(1)
    print(f"FAIL  {what}")
    subprocess.run(["docker", "compose", "logs", "--tail", "40"], check=False)
    sys.exit(1)


def main():
    c = httpx.Client(base_url=CORE, timeout=5)
    wait("core answers", lambda: c.get("/api/site").status_code == 200)

    def everyone():
        robots = c.get("/api/site").json()["robots"]
        return all(r["last"] for r in robots) and {r["protocol"] for r in robots}
    protocols = wait("all three robots report, MQTT included", everyone)
    assert protocols == {"vda5050", "ros2", "rest"}, protocols

    # MediaMTX writes the camera into the shared RAM volume the core reads
    rec = "docker compose exec -T core ls /recordings/cam-humanoid".split()
    def recording():
        return subprocess.run(rec, capture_output=True, text=True).stdout.count(".mp4") >= 3
    wait("the camera is being recorded", recording)

    c.post(f"/api/demo/{ROBOT}/obstacle").raise_for_status()

    def sealed():
        return next((i for i in c.get("/api/incidents").json() if i["robot"] == ROBOT and i["bundle"]
                     and not i["bundle"].endswith(".partial.rbox")), None)
    inc = wait("the incident is sealed", sealed, timeout=60)

    body = c.get(f"/api/incidents/{inc['id']}/bundle").content
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        videos = [n for n in z.namelist() if n.endswith(".mp4")]
        incident = json.loads(z.read("incident.json"))
    print(f"ok    bundle holds {len(videos)} video segments, kind {incident['kind']}")
    assert videos, "no video in the bundle"
    assert incident["kind"] == "needs_assistance"

    open("e2e.rbox", "wb").write(body)
    open("e2e.pub", "wb").write(c.get("/api/site.pub").content)
    out = subprocess.run(["rbox-verify", "e2e.rbox", "--key", "e2e.pub"], capture_output=True, text=True)
    print(out.stdout.strip())
    sys.exit(out.returncode)


if __name__ == "__main__":
    main()
