# Lenses

Run each lens over what the PR adds or worsens. Skip a lens with nothing specific to say.

| Lens | Ask | Signals in code |
| --- | --- | --- |
| Volumetry | • What is N per call, per tenant, in total?<br>• How fast does it grow?<br>• How long is it kept? | • unbounded load into memory<br>• per-tenant fan-out<br>• new table with no retention |
| Scalability | • What breaks first at 10x: CPU, memory, connections, a lock, a hot key, a downstream limit?<br>• Does it scale out? | • in-process state or cache<br>• per-instance pacing or rate limit, which does not bound the total across instances<br>• global lock<br>• single partition key<br>• one job looping over all tenants |
| Performance | • Is it on a user-facing path?<br>• What is its latency budget?<br>• Could the work be async? | • sync remote call in a request<br>• serial calls that could run together<br>• heavy work in a hot loop |
| Monitoring | • How will we know it works?<br>• How fast will we know it breaks?<br>• Which alert fires, and who gets paged? | • new job, endpoint, or consumer with no metric<br>• errors logged but not counted<br>• dead-letter queue with no alarm |
| Failure modes | • What happens when a dependency is slow, down, or wrong?<br>• What happens when every client retries or reconnects at once?<br>• Is a retry safe?<br>• What is the blast radius? | • no timeout<br>• retry with no backoff or cap<br>• non-idempotent write on an at-least-once consumer<br>• partial write with no compensation |
| Data lifecycle | • Does the migration lock a large table?<br>• Who backfills?<br>• Can it roll back without data loss?<br>• Do old and new code share the schema during deploy? | • column renamed in one step<br>• NOT NULL added on a large table<br>• destructive migration<br>• no purge |
| Cost | • What does one call cost?<br>• What does it cost at 10x? | • paid API call per item<br>• log line per item on a hot path<br>• high-cardinality metric tag<br>• unbounded storage growth |
| Alternatives | • Is there a simpler or better-placed design at this volume? | • rebuilds an existing component<br>• sync call where an event fits<br>• logic in the wrong service |
