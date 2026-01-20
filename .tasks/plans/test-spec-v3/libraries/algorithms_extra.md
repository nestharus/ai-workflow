# Algorithms Extra Library

Extra algorithms for high-volume processing.

---

### Algorithm 4 - Batch Processing ([=Algorithm 4])

For high throughput:
1. Collect events into batches
2. Process batch through Algorithm 1
3. Route batch through Algorithm 2
4. Deliver batch through Algorithm 3

Requires (@[+Algorithm 1]), (@[+Algorithm 2]), (@[+Algorithm 3]).

---

### Algorithm 5 - Error Recovery ([=Algorithm 5])

When delivery fails:
1. Check retry count against D5
2. If under limit, requeue
3. If over limit, move to dead letter

Requires (@[+Algorithm 3]), (@[+D5]).

---
