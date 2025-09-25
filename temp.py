Time ─────────────────────────▶
Req A: [work][DB wait.......][Redis wait.....][done]
Req B:                               [work][DB wait.......][Redis wait.....][done]
Req C:                                                           [work][DB wait.......][Redis wait.....][done]


Time ─────────────────────────▶
Req A: [work][DB wait......][Redis wait.....][done]
Req B:     [work][DB wait......][Redis wait.....][done]
Req C:         [work][DB wait......][Redis wait.....][done]

One request alone → async has a tiny bit more overhead than sync.

Many concurrent requests → sync I/O blocks the event loop → everyone waits in line.

Async I/O → while one request is waiting on the network (DB, Redis, HTTP), the event loop keeps serving other requests → much higher throughput under load.

Blocking sync calls → one slow DB/HTTP call holds up the entire event loop.

Async I/O → other requests keep moving while one request is waiting.

Result: lower latency under load and higher max concurrency (measured in requests/sec per worker).

Even though a single call may be ~1–2 ms slower, the system as a whole handles spikes much better.