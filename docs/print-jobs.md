# Print jobs

One CatLabel process owns the database and printer connections. Hardware admission
allows one transfer per canonical device address; a competing transfer is rejected
before scanning or connecting. Run one authoritative process for a data directory.

## Submission and uncertainty

A successful response reports `submitted`, a label count and
`physical_completion: unverified`. That confirms data submission, not that every
physical label emerged. Connection failures or lost responses can leave delivery
uncertain. Check the output before deliberately retrying; another transfer can
print duplicates. CatLabel never automatically replays uncertain delivery.

The editor prepares pages without replacing the canvas. Progress appears on the
print controls and in Status. Preparation can be cancelled before submission;
this does not stop a transfer already in progress. Superseded and duplicate render
callbacks cannot submit the same local preparation again.

## Durable MCP jobs

MCP previews and plans have immutable identities. A plan freezes the preview,
printer identity, settings, selected pages and copies. `catlabel_print_start`
requires the exact plan hash and an idempotency key. Repeating the same request
with that key returns the same persisted job, including across restarts; using the
key for another request fails.

Use `catlabel_job_get` or `catlabel_jobs_list` for status. Cancellation is permitted
before delivery starts. If the app stops after that boundary, recovery marks the
job `delivery_uncertain` instead of sending again. A deliberate retry needs a new
key and a check of the physical printer.

Unstarted plans expire after 15 minutes. Receipts and key reservations remain for
90 days; uncertain delivery sources remain for seven days. See the [MCP guide](mcp.md)
for the complete workflow and artifact boundaries.
