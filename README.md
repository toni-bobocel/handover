# handover

A console for a warehouse or factory running robots from several vendors. It runs on the site PC, needs no internet, and does three things:

- shows every robot on one floor plan, whatever brand and protocol;
- lets an operator take over a robot that is stuck, drive it round the problem from a browser, and hand it back;
- keeps the last minute of every robot in memory and, when something goes wrong, seals the thirty seconds before and after into a signed file that nobody can edit without it showing.

Site and live demo: https://toni-bobocel.github.io/handover/ (the robots there are simulated in your browser).

## The problem

An integrator who installs an AMR from one vendor, a cleaning robot from another and a humanoid from a third ends up with three dashboards, three cloud accounts and no common record of what happened when one of them hits something. When a robot stops in an aisle, someone walks over to it. When a pallet gets knocked over, the vendor's logs are in the vendor's cloud, if the site was allowed to connect to it at all.

Most sites I have seen are not: the robots sit on a VLAN with no route out, and the plant's IT will not open one for a dashboard. So handover assumes no internet. It installs from one compose file, keeps its data on the machine it runs on, and loads nothing from outside, fonts included.

## Running it

```sh
docker compose --profile demo up
```

Then open http://localhost:8080. The demo profile adds a simulator with three robots: an AMR speaking VDA 5050 over MQTT, a humanoid exposing ROS 2 through rosbridge, and a floor scrubber that only speaks REST. Make one fail from the panel on the right; after six seconds blocked it asks for help, and the space bar takes the wheel.

For a real site, write a `fleet.toml` describing your robots and zones (`deploy/demo/fleet.toml` is the example) and point the compose file at it:

```sh
HANDOVER_FLEET=/etc/handover/site.toml docker compose up -d
docker compose exec core handover --config /etc/handover/fleet.toml users add ana --role admin
```

Accounts have one of four roles: a viewer sees the floor and the incidents, an operator also pauses and resumes robots and downloads bundles, a driver takes the wheel, an admin edits zones. Passwords are scrypt hashes in `users.toml` in the data volume; sessions are signed cookies that last twelve hours, and removing an account ends its sessions at once. REST robots can be given a token each (`token = "…"` in fleet.toml) so nothing else on the network can post positions in their name. The demo sets `[auth] open = true` and has no accounts.

The floor plan comes from the site's drawings. `handover plan drawing.dxf --scale 0.001 --layer WALLS` imports the lines and closed polylines of an architect's DXF, in metres, with y flipped to match the plan; a scan works too, with `image = "hall-b.png"` and `image_box = [x, y, width, height]` in metres under `[plan]`, shown inverted so a white drawing sits quietly under the robots.

Bundles are kept a year or up to 5 GB by default (`[blackbox] keep_days`, `max_mb`). Give `export = "/mnt/nas/handover"` and every sealed bundle is also copied there; retention never deletes one that has not been copied. `key = "/run/secrets/site.key"` keeps the signing key off the data volume, and the core refuses a key file other users can read. If the core dies while an incident is open, the seconds before the trigger were already written and are kept as a partial bundle on the next start.

On a site, `tls = true` in fleet.toml serves the console over HTTPS. With no certificate from the plant's IT in `data/tls/`, the core makes a self-signed one on first start for the names in `tls_names` and logs its SHA-256 fingerprint, to be checked once when the browsers are set up. `deploy/site/` has a broker config that refuses anonymous clients and listens on TLS only, and a fleet.toml to start from; set `HANDOVER_MQTT=./deploy/site` to use it.

Without Docker:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e "core[dev]" -e simulator
handover --config fleet.toml            # http://localhost:8080
python -m handover_sim --config fleet.toml
pytest core && ruff check core simulator

cd ui && pnpm install && pnpm dev       # http://localhost:5179, proxies /api to the core
```

The simulator's AMR needs an MQTT broker on localhost:1883; the other two work without one.

## How it is built

One Python process, asyncio throughout. Adapters translate each protocol into the same `Telemetry` and publish it on an in-process bus; everything else subscribes to the bus.

```
 robots ─┬─ VDA 5050 / MQTT ──┐
         ├─ ROS 2 / rosbridge ┼─▶ adapters ─▶ bus ─┬─▶ rules       (stuck, e-stop, battery, silent)
         └─ REST / webhooks ──┘                    ├─▶ geofence    (pause a metre short of a zone)
                                                   ├─▶ recorder    (60 s ring per robot, sealed bundles)
                                                   ├─▶ audit       (SQLite, WAL)
                                                   └─▶ browsers    (WebSocket)
 operator ── WebSocket, 10 Hz heartbeat ─▶ teleop (speed cap, dead-man) ─▶ adapter
```

- **Adapters** (`core/handover/adapters/`) are one class each with four methods: `run`, `pause`, `resume` and, where the protocol allows it, `drive`. VDA 5050 has no velocity command, by design, so the AMR can be paused but not driven, and the console says so. Adding a vendor means adding a class. [docs/protocols.md](docs/protocols.md) has the mapping for each protocol.
- **The black box** keeps a ring buffer per robot in RAM and writes nothing until a rule fires. Then it waits thirty seconds and writes a `.rbox`: a zip with the telemetry as hash-chained JSON lines, the incident, a report as HTML and PDF, and a manifest signed with the site's Ed25519 key. `rbox-verify incident.rbox --key site.pub` tells whoever receives it whether a line was edited, removed or the whole thing re-signed. [ADR 2](docs/adr/0002-ring-buffer-and-signed-bundles.md).
- **Teleop** caps speed at 0.5 m/s on the server and stops the robot if 250 ms pass without a packet from the browser. The browser sends one every 100 ms whether a key is down or not, so a crashed tab or a dropped wifi link stops the robot instead of leaving it on its last command. [ADR 3](docs/adr/0003-teleop-dead-man-on-the-server.md).
- **Zones** are polygons, optionally limited to hours of the day. A robot within a metre of one, looking 0.6 s ahead, is paused. One being driven by a person gets a warning instead: taking control away from an operator mid-manoeuvre is worse than the near miss.
- **Storage** is SQLite in WAL mode for incidents, zones and the audit trail. Telemetry never touches it. [ADR 1](docs/adr/0001-one-process-sqlite-wal.md).

The UI is TypeScript without a framework: a site page with GSAP for the motion and a console that draws the floor plan on a canvas. When the console cannot reach a core, as on GitHub Pages, it runs the same rules against a simulation in the tab, which is what the demo on the site is.

With the simulator streaming three robots, the core sits at about 74 MB of RAM on my laptop. The compose file caps it at 300.

## Trade-offs and what is missing

- **Video goes through MediaMTX.** Robots publish their camera to it (or it pulls them); the console plays it over WebRTC with no ICE servers, the core relays the WHEP offer so cameras follow the same accounts, and MediaMTX records every camera in 2 s segments to a RAM volume that keeps 75 s. Sealing an incident copies the overlapping segments into the bundle, hashed and signed like the rest. The segment selection and bundling are tested; the WebRTC path itself has only been checked by building the images, not yet watched end to end on a site network. ADR 3 explains why control and video travel separately.
- **One process means one machine.** Ring buffers and teleop sessions live in memory. For a site with a few dozen robots that is the point; for two hundred I would split the adapters into their own processes behind a broker and keep the recorder next to them.
- **The signature proves the bundle was not changed after the site sealed it.** It does not prove the robot told the truth, and anyone with the site's private key can sign anything. The key can sit on its own mount; a TPM would be better and is not done.
- **Accounts are local.** A plant with SSO would want it behind its identity provider; the session check is one function to swap. Teleop would also deserve a second factor, ideally a physical enable switch next to the operator's screen.
- **The ROS 2 adapter talks to rosbridge**, not DDS. It means no ROS installation next to the core and one WebSocket per robot, at the cost of JSON on the wire. Fine at 10 Hz; not for point clouds.

## What I would do with a real customer

Start with their worst week: which robot stopped where, how long it took someone to get there, what they had to send the vendor afterwards. Then wire the two protocols they actually run, write rules from that week rather than from my list, and measure the walking it saves before adding anything else.

## Licence

MIT.
