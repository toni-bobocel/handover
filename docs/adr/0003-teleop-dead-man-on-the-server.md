# Teleop: heartbeat and speed cap on the server, video apart

## Context

Remote driving from a browser fails in boring ways: the tab crashes while a key is held, the laptop goes to sleep, the site's wifi drops for two seconds. In every one of those the last command the robot received was "forward", and most robot stacks keep executing the last velocity until told otherwise, or until their own watchdog fires, which on some platforms is a full second.

Operators also make mistakes. A key held a moment too long at full speed next to a person is the kind of incident this tool is supposed to prevent, not cause.

## Decision

Control goes over a WebSocket per session. The browser sends a packet every 100 ms for as long as it holds control, keys down or not. The core sends the robot a zero velocity, once, when 250 ms pass without a packet, and checks every 20 ms. The robot stays stopped until packets resume or the operator hands it back.

Linear speed is capped at 0.5 m/s and turning at 0.8 rad/s in the core, whatever the browser asks for. The UI shows the cap but does not enforce it: the UI is the part most likely to be wrong, and the part someone might replace.

One operator per robot. A second one is refused until the first releases or disconnects. Taking over pauses the robot's own autonomy first; handing back sends a stop, then resume.

Video will not share this channel. Control packets are tiny and must not queue behind video frames; video needs a jitter buffer that control must not have. The plan is WebRTC through MediaMTX with host candidates only, so it works on a VLAN with no STUN or TURN server and nothing crosses the site boundary.

## Consequences

- The first end-to-end run stopped the robot after 312 ms of silence, with a 50 ms check interval plus the rosbridge round trip. The interval is now 20 ms; the remaining slack is the network to the robot, which no software on our side can remove.
- A browser in a background tab stops sending, so the robot stops. That is deliberate and occasionally annoying.
- VDA 5050 robots cannot be driven at all: the protocol has no velocity command. They can be paused, and the console says why the drive action is missing.
- The cap is per site, not per robot or zone. A slower cap near people would be a zone property; not built yet.
