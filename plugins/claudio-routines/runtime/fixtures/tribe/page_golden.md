<callout icon="🗓️" color="gray_bg">
	- Run: 2026-03-12 08:30 UTC, window 2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC.
	- Previous run: <mention-page url="https://example.test/pages/previous-page-id"/>, written 2026-03-11 08:34 UTC.
	- Format: layout version 1. Run state: the last toggle of this page, never the state itself.
</callout>
<table_of_contents/>
## Since last run
- New: Queue latency above target, Medium, now.
- Resolved: Cache hit ratio below target, under every threshold for 2 runs.
- Moved: Primary volume filling up, severity from Low to Medium.
- Ticked: Check the retry policy of the importer.
- Worker pool at 94 of 100 slots, 3 pool-full alerts in 7 days
- Queue latency at 140 s, above the 120 s target [chat](https://example.com/threads/latency)
- Page edit ignored: warning row 4, no key marker.
## Decisions this week
<table header-row="true">
<tr>
<td>Decision</td>
<td>Deadline</td>
<td>Options, from the leads</td>
<td>Topic</td>
</tr>
<tr>
<td>Second worker pool for batch jobs</td>
<td>before the month-end</td>
<td>add the pool now, or cap nightly imports and wait one month</td>
<td>Capacity</td>
</tr>
<tr>
<td>Freeze window for the spring release</td>
<td>2026-03-20</td>
<td>freeze for 2 days, or release before the holiday</td>
<td>Release</td>
</tr>
</table>
## Warnings
<callout icon="📏" color="gray_bg">
	How to read the warnings
	- Severity is how bad it is if it happens: High, Medium or Low.
	- When is how soon it binds:
		- 🔴 now: at or above a limit today.
		- 🟠 within months: reaches a limit at the current trend.
		- 🟡 watch: moving the wrong way, no limit in sight yet.
	- Status sits under each warning name.
</callout>
### Focus
<table header-row="true">
<tr>
<td>Topic</td>
<td>Severity</td>
<td>When</td>
<td>Warnings</td>
</tr>
<tr>
<td>Capacity</td>
<td>High</td>
<td>🔴 now</td>
<td>2</td>
</tr>
<tr>
<td>Release</td>
<td>High</td>
<td>🟠 within months</td>
<td>1</td>
</tr>
<tr>
<td>Reliability</td>
<td>Medium</td>
<td>🔴 now</td>
<td>2</td>
</tr>
</table>
### Capacity
<table header-row="true">
<tr>
<td>Warning</td>
<td>Severity</td>
<td>Risk</td>
<td>Impact</td>
<td>Mitigation leads</td>
<td>Evidence</td>
</tr>
<tr>
<td>Worker pool near its ceiling<br>status: open<br><span color="gray">key: worker-pool-ceiling</span></td>
<td>High<br>🔴 now<br>runway: none at peak, 94 of 100 slots</td>
<td>jobs queue behind a full worker pool at peaks</td>
<td>  • batch exports finish late<br>  • interactive requests wait for a free slot</td>
<td>  • add a second pool for batch jobs<br>  • cap the concurrency of nightly imports<br>  • alert at 85 percent of the pool</td>
<td>confidence: measured<br>  • 94 of 100 worker slots busy at the daily peak<br>  • 3 pool-full alerts fired in 7 days [alerts](https://example.com/monitors/pool-full)</td>
</tr>
<tr>
<td>Primary volume filling up<br>status: in progress<br><span color="gray">key: disk-growth</span></td>
<td>Medium<br>🟠 within months<br>runway: about 5 months at +9 percent a month</td>
<td>the primary volume fills before the next resize</td>
<td>writes fail once the volume is full</td>
<td>plan a resize before the 80 percent mark</td>
<td>confidence: inferred<br>  • the volume grows 9 percent a month</td>
</tr>
</table>
### Release
<table header-row="true">
<tr>
<td>Warning</td>
<td>Severity</td>
<td>Risk</td>
<td>Impact</td>
<td>Mitigation leads</td>
<td>Evidence</td>
</tr>
<tr>
<td>Release freeze overlaps a holiday<br>status: open<br><span color="gray">key: freeze-overlap</span></td>
<td>High<br>🟠 within months<br>runway: freeze starts on 2026-03-26</td>
<td>  • the freeze starts when reviewers are away<br>  • no owner is named for hotfixes</td>
<td>  • the release slips by a week<br>  • hotfixes wait for a reviewer</td>
<td>  • move the freeze by 2 days<br>  • name a backup reviewer<br>  • release before the holiday</td>
<td>confidence: reported<br>  • the freeze overlaps a public holiday [chat](https://example.com/threads/freeze)<br>  • 2 reviewers are away that week</td>
</tr>
</table>
### Reliability
<table header-row="true">
<tr>
<td>Warning</td>
<td>Severity</td>
<td>Risk</td>
<td>Impact</td>
<td>Mitigation leads</td>
<td>Evidence</td>
</tr>
<tr>
<td>Queue latency above target<br>status: open<br><span color="gray">key: queue-latency</span></td>
<td>Medium<br>🔴 now<br>runway: none, 140 s of 120 s</td>
<td>jobs wait more than 120 s during the day</td>
<td>imports and emails run late</td>
<td>  • move long jobs to their own queue<br>  • spread out the nightly burst</td>
<td>confidence: measured<br>  • latest hourly max 140 s against a 120 s target</td>
</tr>
<tr>
<td>Backup restore never tested<br>status: open<br><span color="gray">key: restore-untested</span></td>
<td>Low<br>🟡 watch<br>runway: unknown</td>
<td>a backup that cannot be restored</td>
<td>recovery time is unknown</td>
<td>run one drill on a copy of last night's backup</td>
<td>confidence: reported<br>  • no restore drill is recorded this year [pages](https://example.com/pages/backups)</td>
</tr>
</table>
## What to check
### This week
- [ ] <span color="gray_bg">Capacity</span> Read the worker pool quota <span color="gray">read-pool-quota</span>
- [ ] <span color="gray_bg">Reliability</span> Find what moved the queue latency <span color="gray">trace-latency-step</span>
### Before the month-end
- [ ] <span color="gray_bg">Capacity</span> Plan the volume resize <span color="gray">plan-resize</span>
- [ ] <span color="gray_bg">Release</span> Confirm the freeze dates with the release manager <span color="gray">confirm-freeze-dates</span>
### Investigate
- [ ] <span color="gray_bg">Reliability</span> Run one restore drill from last night's backup <span color="gray">run-restore-drill</span>
## Details
### Capacity
- Pool usage peaked at 94 of 100 slots on 2026-03-11 [metrics](https://example.com/metrics/pool)
### Reliability
- The importer retry policy was checked and left unchanged
## Blind spots
- alerts-feed: alerts feed returned no data since 2026-03-09 (runs: 3).
- metrics-trend: metrics trend read failed (runs: 1).
- More gaps not listed: 1.
- Mobile app: Not read, no connector is configured for it.
- Issue tracker: A rule names it and the features hold no record of it.
## Corrections to earlier numbers
- Was: 21 failed imports in 7 days. Now: 19 failed imports in 7 days, after removing 2 duplicate runs.
## Sources
<table header-row="true">
<tr>
<td>Source</td>
<td>Role</td>
<td>Read</td>
<td>Window</td>
</tr>
<tr>
<td>alerts</td>
<td>observability</td>
<td>yes</td>
<td>2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC</td>
</tr>
<tr>
<td>tickets</td>
<td>issue tracker</td>
<td>yes</td>
<td>2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC</td>
</tr>
<tr>
<td>pages</td>
<td>document store</td>
<td>no, connector signed out</td>
<td>none</td>
</tr>
</table>
## How this digest is built {toggle="true"}
	- Format, key and rules: the digest template of the routine.
	- Sources: the routine's source list, read through the collectors.
## Run state {toggle="true"}
	- Window: 2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC.
	- Pages: previous previous-page-id; the id of this page is saved in the state once it is created.
	- State: state/sample.json on the claude/state branch, read by the next run instead of this page.
