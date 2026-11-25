// WebRTC playback through WHEP, the one-request handshake MediaMTX speaks.
// No ICE servers: browser and camera server are on the same LAN, and the
// whole point is that nothing goes looking for a route outside it.

const base = import.meta.env.BASE_URL.replace(/\/$/, '')

export async function watch(robot: string, video: HTMLVideoElement): Promise<() => void> {
  const pc = new RTCPeerConnection({ iceServers: [] })
  pc.addTransceiver('video', { direction: 'recvonly' })
  pc.ontrack = e => {
    video.srcObject = e.streams[0] ?? new MediaStream([e.track])
  }
  await pc.setLocalDescription(await pc.createOffer())
  // send the offer with every candidate in it, so there is no trickle round trip to proxy
  await new Promise<void>(resolve => {
    if (pc.iceGatheringState === 'complete') return resolve()
    const done = () => pc.iceGatheringState === 'complete' && resolve()
    pc.addEventListener('icegatheringstatechange', done)
    setTimeout(resolve, 1500)
  })
  const r = await fetch(`${base}/api/video/${encodeURIComponent(robot)}/whep`, {
    method: 'POST',
    headers: { 'content-type': 'application/sdp' },
    body: pc.localDescription!.sdp,
  })
  if (!r.ok) {
    pc.close()
    throw new Error((await r.json().catch(() => null))?.detail ?? 'camera unavailable')
  }
  await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() })
  return () => {
    pc.close()
    video.srcObject = null
  }
}
