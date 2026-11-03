# Linux substrate

`linux.yaml` models one Linux host at the `runtime` level from the man pages (man7.org) and the
kernel documentation, cited per interface; there is no code snapshot. `scenarios.yaml` holds its
tests:

    go run ./internal/devtools/check -f substrates/linux/linux.yaml -f substrates/linux/scenarios.yaml

**Components.** `kernel` (child of `linux`) holds everything: `procs` (by pid), `fds`
(`<pid>:<fd>`), `objs` (open file descriptions: files, sockets, listeners, epoll instances, with
a reference count), `files`, futex `words`, and `oom_kills`.

**Calling convention.** Every syscall takes the calling `pid`. A failure's code is the errno name
(`EBADF`, `EAGAIN`, `EINTR`, `EMFILE`, `ECONNREFUSED`, `ETIMEDOUT`, ...) with `data.errno`. A
process killed inside a syscall never returns from it: the call fails `killed`. A syscall from a
pid that isn't a live process fails `ESRCH` (a model guard).

**Behavior.**
- Processes: `fork` (fd table duplicated, descriptions shared; dispositions, RLIMIT_NOFILE and
  oom_score_adj inherited), `execve` (ENOENT, EACCES; close-on-exec fds closed; handled signals
  reset, ignored kept; `run_ms`/`exit_code` make the program exit by itself), `exit`, `waitpid`
  (zombies until reaped, WNOHANG, ECHILD, EINTR and a restart after it; decoded status with
  `shell_status` 128+n).
  Orphans go to init; a parent ignoring SIGCHLD gets no zombies.
- Signals: `sigaction` (default, ignore, handle; EINVAL for SIGKILL/SIGSTOP), `kill` (ESRCH,
  EINVAL, signal 0; a zombie accepts signals). Default actions: terminate, or ignore for SIGCHLD,
  SIGURG, SIGWINCH. A handled signal interrupts a blocking syscall with EINTR. SIGCHLD goes to the
  parent at exit; SIGPIPE to a writer whose peer closed.
- Fds: lowest free fd first; EMFILE at RLIMIT_NOFILE (`setrlimit-nofile`), checked before
  ENOENT; `open` (O_CREAT, O_TRUNC, O_CLOEXEC), `read`/`write` at the description's offset,
  `close` (EBADF).
- Sockets (TCP on local ports): `socket`, `listen` (EADDRINUSE), `connect` (ECONNREFUSED with no
  listener; ETIMEDOUT after `linux-tcp-syn-timeout-ms` when the accept queue is full; EISCONN),
  `accept` (EAGAIN, EINTR, EMFILE leaves the connection queued), blocking or nonblocking `read`
  with SO_RCVTIMEO (EAGAIN), EOF after the peer's close, ECONNRESET for a connection queued on a
  closed listener, EPIPE.
- `epoll-create`, `epoll-ctl` (EPERM for regular files, EEXIST, ENOENT), `epoll-wait`
  (level-triggered EPOLLIN plus rdhup; timeout 0, N or -1; EINTR).
- `futex-wait` (EAGAIN when the word changed, ETIMEDOUT, EINTR), `futex-wake` (at most n, FIFO,
  returns the count), and `atomic-store` for the user-space word.
- `nanosleep` (EINTR with `remaining_ms`).
- Memory: `mem-touch`, `mem-release`, `oom-score-adj`. Past `linux-memory-limit-mb` the OOM
  killer SIGKILLs the highest badness (resident thousandths of the limit plus oom_score_adj;
  -1000 and init exempt) until memory fits; ENOMEM when nothing can be killed.

**Blocking.** A blocking syscall records `blocked: {on, obj, addr, seq}` on the process and
sleeps in a blocking `wait` (DESIGN §17 item 2) on the kernel's state: waitpid until a matching
child is a zombie (or none is left), read until data, EOF or a reset, accept until a connection
is queued, epoll_wait until an interest is readable, a futex wait until FUTEX_WAKE dequeues it
(clears its record, oldest first), nanosleep until its timeout. Every wait also ends when the
process dies (`killed`) or on the signal `sig:<pid>`, which a handled signal delivers (EINTR). A
signal that arrives while nothing sleeps is not remembered. Drive a blocking call from a scenario
step with `await: false` and its waker from a later step with `at_ms`, or make them in one call:
a fork, an exec whose program exits on a timer and a blocking waitpid work in one call tree
(`app.spawn-and-wait`; DESIGN §17 item 3). Processes are rows, not component instances, so a
`kill` step's `kill:<component>` signal doesn't reach them; use the `kill` syscall.

**Not modeled.** Threads sharing an fd table, SA_RESTART, signal masks, real-time signals, job
control, pipes, UDP, dup, permissions and directories, nonblocking connect, send buffers and
flow control (see the tcp-tls substrate), swap and overcommit.
