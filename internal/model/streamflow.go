package model

// Stream flow control (§16.4). A streaming call may declare window: N, the
// frames in flight (yielded but not yet handled by on_item) before the
// producer's next yield blocks, and stall_ms, the longest the producer may
// stay blocked: past it the stream fails with {code: stream_stalled}.
// Byte windows (§17 item 5): window_bytes bounds the bytes in flight, each
// frame counting its size field when it has one, else
// bytes(json(frame)). All go with stream: true; stall_ms needs a window,
// since a producer never blocks without one. relay: true (also with
// stream: true) applies the windows of the stream the calling behavior is
// itself producing to the inner producer.

// streamFlow checks a step's window, window_bytes, stall_ms and relay.
func (v *validator) streamFlow(p string, s Step) {
	hasWindow, hasBytes, hasStall := !s.Window.IsZero(), !s.WindowBytes.IsZero(), !s.StallMS.IsZero()
	if s.Relay && !s.Stream {
		v.errf(p+".relay", "relay goes with stream: true")
	}
	if !hasWindow && !hasBytes && !hasStall {
		return
	}
	if !s.Stream {
		v.errf(p, "window, window_bytes and stall_ms go with stream: true")
	}
	switch {
	case s.Window.IsExpr():
		v.intOrExpr(p+".window", s.Window)
	case hasWindow && (s.Window.N < 1 || !s.Window.IsWhole()):
		v.errf(p+".window", "a stream window is a whole number of at least 1")
	}
	switch {
	case s.WindowBytes.IsExpr():
		v.intOrExpr(p+".window_bytes", s.WindowBytes)
	case hasBytes && (s.WindowBytes.N < 1 || !s.WindowBytes.IsWhole()):
		v.errf(p+".window_bytes", "a byte window is a whole number of at least 1")
	}
	if hasStall {
		v.intOrExpr(p+".stall_ms", s.StallMS)
		if !hasWindow && !hasBytes {
			v.errf(p+".stall_ms", "stall_ms needs a window or window_bytes")
		}
		if !s.StallMS.IsExpr() && s.StallMS.US() <= 0 {
			v.errf(p+".stall_ms", "stall_ms must be positive")
		}
	}
}
