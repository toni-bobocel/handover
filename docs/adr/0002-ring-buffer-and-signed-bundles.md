# A ring buffer in RAM, sealed into signed bundles

## Context

After a collision, three parties want the same minute of data: the site, the robot's vendor (for the warranty) and the insurer. They do not trust each other. The vendor will say the site edited the logs; the site will say the vendor's cloud lost them.

Recording everything continuously is cheap in bytes and expensive in SSD wear and in "which of these four terabytes is the incident". Recording nothing until something happens misses the part that matters: the seconds before.

## Decision

Each robot gets a ring buffer in memory holding the last 65 seconds of telemetry and events. When a rule fires (e-stop, battery under 10 %, three seconds of silence, blocked for fifteen, a human takeover, a zone stop, a dead-man stop), the recorder notes the time, waits thirty seconds, and writes the window from thirty before to thirty after as one `.rbox` file.

Inside, every record carries the SHA-256 of the record before it, so the telemetry is a hash chain. A manifest lists the hash of every file in the bundle and the head of the chain, and is signed with the site's Ed25519 key, generated on first start. The bundle also carries the public key for convenience, but `rbox-verify` is meant to be run with a copy obtained separately, which is what `--key` is for.

A second trigger on the same robot while a bundle is open joins it (`also` in incident.json) rather than opening another: a robot gets stuck, someone takes over, and that is one story.

## Consequences

- The disk sees a few kilobytes per incident, never a stream.
- An edited value breaks that record's hash; a deleted record breaks the chain; truncating the tail and fixing the manifest breaks the signature; re-signing with another key fails against the site's public key. All four are tested.
- The signature proves the bundle is what this site sealed. It cannot prove the robot reported the truth, and it is only as good as the custody of the private key. Moving the key into a TPM is on the list.
- Thirty seconds after the trigger is a guess. Long enough to capture a takeover and the robot moving off; not so long that the operator waits a minute for the file. Configurable per site.
- The seconds before the trigger are written at once as a partial bundle, signed like the final one, and replaced when the final one is sealed. If the process dies in between, the next start keeps the partial bundle as the incident's record. Two writes per incident instead of one; worth it for the part of the story that matters most.
