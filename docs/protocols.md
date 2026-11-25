# Protocols

Each adapter turns one protocol into `Telemetry` (position in site metres and radians, speed, battery 0 to 1, status, `blocked`, `estop`, a free-text note) and implements `pause`, `resume` and, where possible, `drive`.

| | VDA 5050 | ROS 2 | REST |
|---|---|---|---|
| Transport | MQTT, through the site broker | rosbridge JSON over WebSocket | HTTP both ways |
| Position | `state.agvPosition`, then `visualization` at 10 Hz | `/odom` (`nav_msgs/Odometry`), yaw from the quaternion | `POST /ingest/{robot}` body |
| Battery | `state.batteryState.batteryCharge` (0 to 100) | `/battery_state` `percentage` | `battery` |
| Blocked | `safetyState.fieldViolation` | a `/diagnostics` status of level ≥ 1 whose message contains "blocked" | `blocked` |
| E-stop | `safetyState.eStop` other than `NONE` | a `/diagnostics` status of level 2 named `*estop*` | `estop` |
| Pause | instant action `startPause` / `stopPause` | `std_msgs/Bool` on `handover/pause` | `{"cmd": "pause"}` / `{"cmd": "resume"}` |
| Drive | not in the protocol | `geometry_msgs/Twist` on `cmd_vel` | `{"cmd": "drive", "linear", "angular"}` |

## VDA 5050

Topics follow `{interface}/{major}/{manufacturer}/{serial}/{topic}`, `uagv/v2` by default. The spec asks robots to send `state` on change and at least every 30 seconds, which is too slow for a plan, so position is read from `visualization` and everything else from the last `state`. Instant actions are sent with QoS 1 and `blockingType: HARD`.

## ROS 2 through rosbridge

The core subscribes with throttles (100 ms for odometry, 250 ms for diagnostics, 1 s for battery) so a robot publishing odometry at 100 Hz does not flood the socket. Topics can be namespaced per robot with `namespace = "/g1"`. The pause topic is not a ROS convention; the robot side needs a node that maps it onto its navigation stack's pause, usually a few lines.

## REST

For robots whose vendor offers webhooks and a command endpoint and nothing else. The robot, or a small bridge next to its cloud connector, posts its state to `/ingest/{robot}`; commands go to the `command_url` in fleet.toml.

## Writing an adapter

Subclass `Adapter`, set `protocol`, implement `run` (own the connection, reconnect on failure, call `self.emit` with each `Telemetry`), `pause` and `resume`, set `can_drive = True` and implement `drive` if the robot accepts velocities. Register it in `adapters/__init__.py`. `tests/test_adapters.py` shows how the existing ones are tested without a robot: feed `_on` the messages a real one sends.
