# ProjectOS Phase 4-A Source Collection

Status: `SIMULATED`. This procedure does not authorize inspection of another machine.

Install the deterministic ProjectOS wheel into an isolated Python 3.11+ environment. Create canonical intake JSON matching the Phase 4 specification with a generated source-machine ID, the absolute Looker repository and separate output directory, safe Google/GAS identifiers, declared scripts and scheduler definitions, fixed validation commands, and credential references only.

Run `python -m projectos.looker_host preflight --intake intake.json` first. After separate read-only source-machine authorization, run `collect` with a new archive path and the verified wheel SHA-256. Use `verify --archive` before transfer. `recover --intake` removes only collector temporary archives; it never changes repository or legacy state.

The collector rejects elevation, links, overlapping roots, shell syntax, secrets, repository changes during collection, noncanonical archives, private identifiers, and unknown members. It never authenticates Google or changes Git, Sheets, GAS, scripts, or schedulers.
