# Errors

Command failures and integration errors.

---

- 2026-08-09: PowerShell runner failed before execution with Windows CreateProcessAsUserW error 1920; switched to Node REPL filesystem access.
- 2026-08-09: Runtime import smoke test reached existing media.cache dependency and failed because the environment lacks mutagen; py_compile remains successful.
- 2026-08-09: First mock-client check script used invalid JavaScript triple-quote syntax; no repository files were changed.
- 2026-08-09: Frontend bundle build could not start because npm is not installed in the execution environment (spawn npm ENOENT).

- 2026-08-09: `functions.shell_command` failed twice with Windows runner error 1920 while launching PowerShell in the workspace; switched to Node REPL filesystem and child-process execution.
- 2026-08-09: `npm view` compatibility check could not run because npm is unavailable (`spawn npm ENOENT`); FontAwesome imports were limited to known v5-compatible icons and JavaScript syntax checks passed.
- 2026-08-09: Direct fetch to unpkg for FontAwesome export verification failed in the execution environment; no repository files were changed by the check.
