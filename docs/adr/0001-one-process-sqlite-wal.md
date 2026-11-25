# One process, SQLite in WAL mode

## Context

handover runs on whatever the site already has: an Intel NUC under a desk, a Jetson in a cabinet, sometimes the PC that runs the warehouse management system. Nobody on site administers a database. The robots report 5 to 20 times a second each, and a site has somewhere between three and forty of them.

The obvious architecture for "ingest telemetry, detect events, serve a UI" is a broker, a time-series database, a rules service and an API. That is four things to install, upgrade, back up and debug at three in the morning over a remote session that drops every ten minutes.

## Decision

One Python process. Adapters, rules, geofence, recorder and API share an asyncio loop and talk through an in-process bus with a bounded queue per subscriber. The only other container is the MQTT broker, because VDA 5050 robots expect one.

Telemetry is never written to a database. It lives in a ring buffer per robot (see ADR 2). What does get written (incidents, zones, the audit trail of operator actions) is a few rows a minute, so SQLite in WAL mode is plenty: readers do not block the writer, and the database is one file in the data volume.

## Consequences

- Install is `docker compose up`. Backup is copying a directory.
- Memory is predictable: about 74 MB with three robots in the demo, growing with the number of robots times the ring length, not with uptime.
- Everything is lost on a crash except what was sealed. That is acceptable for live state and the reason incidents are written to disk the moment they are sealed.
- It does not scale out. Past a few dozen robots per site, adapters would move to their own processes and publish on the broker instead of the in-process bus; the bus interface was kept small so that is a swap, not a rewrite.
- TimescaleDB or DuckDB would make "show me this robot's battery over the last week" easy. Nobody on a site has asked for that; vendors keep it already.
