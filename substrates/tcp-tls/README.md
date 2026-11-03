# TCP/TLS substrate

`tcp-tls.yaml` (`level: runtime`) models the Linux TCP stack through the socket API, and a TLS
library on top of it. It follows the RFCs (9293, 6298, 2525, 8446, 5280, 6125), the man7.org pages
(tcp(7), socket(7), connect(2), accept(2), shutdown(2), close(2)) and the TLS libraries' sources,
cited per interface. Tests:

    go run ./internal/devtools/check -f substrates/tcp-tls/tcp-tls.yaml -f substrates/tcp-tls/scenarios.yaml

**Components.** `tcp-stack` holds every host's listeners and sockets. Each connection is two
sockets, one per end, each naming its `peer`. Ids are `sock-1`, `sock-2`, and so on; the client
end comes first. `tls` holds the sessions, keyed by socket.

**Errors are errno names**: `ECONNREFUSED`, `ETIMEDOUT`, `EHOSTUNREACH`, `ECONNRESET`, `EPIPE`,
`EAGAIN`, `EADDRINUSE`, `EINVAL`, `EBADF`, `ENOTCONN`. TLS failures are alert names:
`certificate_expired` (45), `unknown_ca` (48), `bad_certificate` (42) and `handshake_failure` (40),
with `data.alert_code`. The peer sees `tls_alert`, and a truncated stream is `unexpected_eof`.

**Time.** `tcp-rtt-ms` (10 ms) is the round-trip time:
- `connect` returns one RTT after it starts, and `accept` gets the connection half an RTT later,
  when the ACK arrives.
- A segment arrives RTT/2 plus `bytes / tcp-bandwidth-bytes-per-ms` after it is sent.
- A TLS 1.3 handshake takes one RTT plus `tcp-tls-crypto-ms`; TLS 1.2 takes two RTTs.

Note that socket times such as `fin_at` and `rst_at` are absolute: they include the clock's epoch.

**Behavior.**
- **Establishment.** No listener: RST, then `ECONNREFUSED`. A full accept queue (`backlog`, capped
  by `tcp-somaxconn`) or a blackholed host drops the SYN. The SYN is retransmitted after 1, 2,
  4 ... s, and connect fails `ETIMEDOUT` at 127 s, or at the caller's `timeout_ms`.
- **Data transfer.** Bytes the peer's receive window (`rcvbuf`) admits go on the wire; the rest
  waits in the send buffer (`sndbuf`). A non-blocking `send` returns a partial count, or `EAGAIN`
  when nothing fits. A blocking one waits for the window update that the reader's `recv` sends,
  up to `timeout_ms` (SO_SNDTIMEO). A blocking `recv` waits for data, a FIN or an RST, up to its
  SO_RCVTIMEO (`EAGAIN`).
- **Bulk transfer as a stream.** `bulk-send` yields a transfer segment by segment, for callers
  that read it with `stream: true`, `window` (the receive buffer in segments) and `stall_ms`. A
  reader slower than `stall_ms` per segment fails the transfer with `stream_stalled`.
- **Teardown.**
  - `shutdown(SHUT_WR)` queues a FIN behind the data (a half-close). The peer reads the data,
    then EOF, and can still send back.
  - `close` sends a FIN. It sends an RST instead when there is unread data or `linger_zero`, or
    when data reaches a socket that is already closed.
  - When an RST arrives, the next call fails `ECONNRESET`. After that, writes fail `EPIPE` and
    reads return EOF.
- **Timeouts and dead peers.**
  - A listener's `idle_timeout_ms` makes the server close connections that have had no reads or
    writes for that long.
  - `host-crash` makes a host's sockets vanish silently. Their peers fail `ETIMEDOUT`, either
    after the keepalive time plus probes × interval (with `keepalive`), or `tcp-retries2-timeout-ms`
    after sending data that is never acknowledged.
- **TLS.**
  - `tls.handshake` (the client) validates the certificate the way crypto/x509 does: first the
    validity period, then the issuer against `tcp-tls-trusted-cas`, then the server name against
    the SANs (`*.` matches one label). On failure it sends the alert and closes the connection.
  - `tls.accept-handshake` (the server) waits for the client's verdict.
  - `tls.close` sends `close_notify` first. Without it, the peer's read at EOF fails
    `unexpected_eof`.

**Not modeled.** TIME_WAIT, Nagle and delayed ACKs, congestion control, packet loss and
retransmission of data (except against a crashed host), MSS segmentation (except in
`bulk-send`), TLS record overhead, session resumption, 0-RTT, client certificates, and ICMP
other than "host unreachable".

**Import example.** [../examples/tcp-client](../examples/tcp-client/) dials a TLS backend with a
connect timeout and retries on `ECONNREFUSED`. It verifies the certificate and reads the reply
with a read timeout.
