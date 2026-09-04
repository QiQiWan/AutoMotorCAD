MotorCAD Studio diagnostic logs

startup.log              Launcher / environment / dependency / server startup
studio.log               Human-readable combined runtime log
studio.jsonl             Complete structured runtime stream
http.jsonl               HTTP requests, operational endpoints and failures
preflight.jsonl          Runtime shallow/deep-check lifecycle and cleanup evidence
errors.log               Human-readable ERROR/CRITICAL records with references
errors.jsonl             Structured ERROR/CRITICAL records
frontend.jsonl           Browser-reported structured frontend events
audit.jsonl              Mutating/audited operations
native.jsonl             Motor-CAD/native runtime events
qualification.jsonl      Qualification evidence events
tasks/<task-id>.log      Per-task human-readable event stream
tasks/<task-id>.jsonl    Per-task structured event stream
cases/<case-id>.log      Per-case human-readable event stream
cases/<case-id>.jsonl    Per-case structured event stream
snapshots/preflight/     Per-run runtime-check result snapshots

These files are runtime evidence and are intentionally excluded from the immutable
package-content manifest. They can be zipped with the in-app diagnostics export.
