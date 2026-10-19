**Prod watch, 19 Oct 13:32 Paris**
(since Mon 09:35)

**Summary**
- 1 new, 2 escalated, 2 resolved, 7 still open

**New**
🔴 **[P2][svc-a][prod] Jobs availability slow burn**
Medium · now · since 13:12 · [monitor 1001](https://monitoring.example.test/monitors/1001)
- **Risk:** Jobs of service A fail above their availability budget and the sync reaches customers late.
- **Reason:** The monitor went to Alert at 13:12 Paris and is still in Alert (measured); A failing job type is the likely cause, since the dead-letter queue holds 2350 messages (inferred)
- **Mitigation:** Check the job error logs since 11:12Z; Inspect the dead-letter queue for the failing message type
- **Action:** Open the monitor and name the job that burns the budget.

**Escalated**
⬆️🟠 **Service B API latency fast burn**
High · within months · since 16 Oct 09:32 · [monitor 1002](https://monitoring.example.test/monitors/1002)
- **Risk:** Screens of service B load slowly.
- **Reason:** The monitor flipped 44 times between 09:35 and 13:41 Paris (measured)
- **Mitigation:** Check p95 latency by endpoint
- **Action:** Compare the monitor graph with the slow burn monitor.

⬆️🟡 **Service C queue depth (top queue)**
Medium · watch · since not recorded · [metric](https://monitoring.example.test/metric/explorer?query=max:queue.depth)
- **Action:** Page the owner of the queue.

**Resolved**
✅ **Service D database writer at 80 capacity units two hours in a row** · [metric](https://monitoring.example.test/metric/explorer?query=max:db.capacity{host:writer-1}.rollup%28max,%203600%29) · last value 2.533
✅ **Service E API latency slow burn** · [monitor 1003](https://monitoring.example.test/monitors/1003) · last value OK

**Still open (7)**
- Medium: Queue depth on service F, Service G write throttling, Service H messages in DLQ, +2
- Low: Service K job duration, Service L cold start rate

**Blind spots:** Service O replication lag no datapoints (1 run); gap-a no datapoints (13 runs); chat not read (credentials missing: TOKEN); sources-page not read (no reason recorded); metrics before Sat 09:00 not read
**Not shown:** 3 muted changes, 1 blind spot dropped
**Overrides:** Service M gateway high 4xx rate (Warn); Service N request latency (No Data)
