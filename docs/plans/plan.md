# API health endpoints

* Tag the versioned health route with `Health` and keep the path as `/api/v1/health` while the root
  `/health` route remains the liveness probe.
* Clarify readiness vs liveness semantics to align generated docs and monitoring expectations.
