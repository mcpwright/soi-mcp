# soi-mcp — working agreement

`soi-mcp` is a server in the **mcpwright** suite (`github.com/mcpwright`): polished,
public MCP servers that bring a real-world data source into any agent. Every server in
the suite meets the **same engineering bar**, set by the reference server **edgar-mcp**.

> **Source of truth: `edgar-mcp`.** When a convention here is unclear, copy edgar
> (`~/github-personal/edgar-mcp`). The full written rubric is
> `~/my-notes/professional-self-improvement/mcpwright/mcp-standards.md`.
> To scaffold/extend to standard, use the `new-mcpwright-server` skill.

## Non-negotiable policies

- **Lots of unit tests.** Every tool and every parser/formatter has tests. **Mock all
  external I/O** (`respx` for HTTP; a seeded temp SQLite store for the local data). A new
  tool ships with its tests **in the same PR**. `pytest -v` must be green before a PR opens.
- **Use the latest patterns.** Official `mcp` Python SDK via `mcp.server.fastmcp` (NOT the
  standalone `fastmcp` package). Python 3.12+ idioms, `from __future__ import annotations`,
  pydantic v2 models with a `Field(description=...)` on **every** field, `uv` for deps +
  build, async `httpx`. Tools return typed pydantic models (structured output) and are
  annotated `readOnlyHint=True` with a `title`.
- **PR per change, CI-gated.** Standard flow:
  **feature branch → code → code-review subagent → fold in findings → PR → CI green → squash-merge.**
  - *Code-review subagent:* before opening the PR, review the diff (`git diff main...HEAD`) with
    the **`code-reviewer`** subagent (`.claude/agents/code-reviewer.md`) — or just run
    **`/review-pr`**. It runs in a **fresh context with no memory of the coding session** and
    returns severity-tagged findings (**Blocker / High / Medium / Low**). Address Blocker/High
    (and add a regression test for any real bug) before the PR.
  - *Merge:* the `Code Quality & Tests` check green and branch up to date → squash-merge with a
    `(#N)` suffix. `main` is branch-protected; **no direct pushes** (the seed commit is the one
    exception — every change after is a PR).
  - *Commits:* imperative subject + a short body, ending with the dual trailer
    (`Co-authored-by: Devender …` + `Co-authored-by: Claude …`).
  - One focused change per PR — keep process/docs changes (like this one) out of feature PRs.
- **Green locally before pushing:**
  ```bash
  uv run ruff check src/ && uv run ruff format --check src/ && uv run mypy && uv run pytest -v
  ```
  `uv run pre-commit run --all-files` mirrors CI (ruff, ruff-format, mypy, detect-secrets, hygiene).

## Layout (mirrors edgar)

```
src/soi_mcp/
  __init__.py        # from .server import main
  soi_client.py      # async httpx client: IRS file host, latest-year probe, stream + retry
  fields.py          # SOI field crosswalk + agi_stub map + CSV parse + thousands→USD scale
  store.py           # local SQLite store + bulk loader      ← soi-specific
  states.py          # USPS code / state-name resolution (for get_state_totals)
  formatting.py      # stored bracket-rows → model helpers + derived metrics (shares, averages)
  models.py          # pydantic tool RETURN types (Field(description=...) on every field)
  server.py          # FastMCP app: instructions + lifespan + @mcp.tool(readOnlyHint, title)
tests/               # respx-mocked download + seeded temp SQLite; one file per module/tool group
```
Errors users/agents see are actionable `ValueError`s with a next step.

## What soi-mcp does differently from edgar (data layer ONLY)

Everything above is identical to edgar. SOI legitimately differs in *how it gets data*:
- **Bulk-download-once → local SQLite** (`store.py`), not live-per-request calls + a TTL
  cache. The ~200 MB `<yy>zpallagi.csv` is streamed to disk once, parsed into SQLite under
  the OS cache dir, and every lookup is served locally and offline.
- **Zero-config — NO API key** (the data is public-domain; this differs from census, which
  *requires* a key). The only network access is the one-time `setup` / `refresh` download.
- **`setup` / `refresh [year]` console commands** download / re-pull; an optional 4-digit
  year loads a *specific* older tax year (IRS keeps every year at a stable URL).
- One source row is a (state, ZIP, AGI bracket) cell; all six brackets per ZIP are kept so
  the distribution survives. Amounts are normalized thousands→USD at load; suppressed/blank
  cells → None; the reserved `00000` (state total) and `99999` (other) rollups are handled
  deliberately (00000 reachable only via `get_state_totals`).
- **Never** put StartEngine's private scoring (accreditation model, evidence weights) in
  here — public IRS facts + simple derived percentages/averages only. See `soi-mcp-plan.md`.

## Publishing & the website

- Publish (PyPI `mcpwright-soi` + the MCP Registry `io.github.mcpwright/soi-mcp`):
  use the **`publish-mcp-server`** skill.
- The server's page is **mcpwright.com/soi**, in the `mcpwright.github.io` repo, using the
  suite typography (**Fraunces** serif + **JetBrains Mono**): use the
  **`add-mcpwright-site-page`** skill.
