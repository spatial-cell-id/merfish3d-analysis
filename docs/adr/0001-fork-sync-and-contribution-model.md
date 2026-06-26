# Fork sync and contribution model

`origin` (`spatial-cell-id/merfish3d-analysis`) is a fork of upstream
`QI2lab/merfish3d-analysis`. We keep `origin/main` as a **read-only mirror** of
`upstream/main` (no IGFL commits ever land on it) and run the pipeline from
`origin/igfl-main`, where IGFL-specific code lives (`cli/igfl_microscopes/`,
`examples/igfl/`). Fixes and general features to shared code are **PR'd upstream
first**, then flow back via `upstream/main` → `origin/main` → `igfl-main`, rather
than being committed directly to `igfl-main`.

We chose this heavier path over committing directly to the running branch to avoid
diverging from upstream and to keep shared-code changes validated by Douglas
Shepherd — at the cost of slower turnaround on local fixes. The trade-off is
acceptable because it lets us both contribute upstream and keep benefiting from
upstream development without accumulating merge debt.
