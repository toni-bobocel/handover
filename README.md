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
```

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
- **The black box** keeps a ring buffer per robot in RAM and writes nothing until a rule fires. Then it waits thirty seconds and writes a `.rbox`: a zip with the telemetry as hash-chained JSON lines, the incident, a printable report and a manifest signed with the site's Ed25519 key. `rbox-verify incident.rbox --key site.pub` tells whoever receives it whether a line was edited, removed or the whole thing re-signed. [ADR 2](docs/adr/0002-ring-buffer-and-signed-bundles.md).
- **Teleop** caps speed at 0.5 m/s on the server and stops the robot if 250 ms pass without a packet from the browser. The browser sends one every 100 ms whether a key is down or not, so a crashed tab or a dropped wifi link stops the robot instead of leaving it on its last command. [ADR 3](docs/adr/0003-teleop-dead-man-on-the-server.md).
- **Zones** are polygons, optionally limited to hours of the day. A robot within a metre of one, looking 0.6 s ahead, is paused. One being driven by a person gets a warning instead: taking control away from an operator mid-manoeuvre is worse than the near miss.
- **Storage** is SQLite in WAL mode for incidents, zones and the audit trail. Telemetry never touches it. [ADR 1](docs/adr/0001-one-process-sqlite-wal.md).

The UI is TypeScript without a framework: a site page with GSAP for the motion and a console that draws the floor plan on a canvas. When the console cannot reach a core, as on GitHub Pages, it runs the same rules against a simulation in the tab, which is what the demo on the site is.

With the simulator streaming three robots, the core sits at about 74 MB of RAM on my laptop. The compose file caps it at 300.

## Trade-offs and what is missing

- **No video yet.** The black box records telemetry and events, not the camera. The plan is MediaMTX as a sidecar, WebRTC with host candidates only so nothing leaves the LAN, and the ring buffer keeping the last sixty seconds of encoded frames rather than decoded ones. ADR 3 explains why control and video travel separately.
- **One process means one machine.** Ring buffers and teleop sessions live in memory. For a site with a few dozen robots that is the point; for two hundred I would split the adapters into their own processes behind a broker and keep the recorder next to them.
- **The signature proves the bundle was not changed after the site sealed it.** It does not prove the robot told the truth, and anyone with the site's private key can sign anything. The key lives in the data volume; a real deployment should put it in a TPM or at least on a separate mount.
- **No authentication.** Anyone on the VLAN can open the console and take over a robot. On a real site it goes behind the plant's reverse proxy and SSO, and teleop gets a second factor: a physical enable switch, ideally.
- **The ROS 2 adapter talks to rosbridge**, not DDS. It means no ROS installation next to the core and one WebSocket per robot, at the cost of JSON on the wire. Fine at 10 Hz; not for point clouds.

## What I would do with a real customer

Start with their worst week: which robot stopped where, how long it took someone to get there, what they had to send the vendor afterwards. Then wire the two protocols they actually run, write rules from that week rather than from my list, and measure the walking it saves before adding anything else.

## Licence

MIT.
