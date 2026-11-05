# Working on Stories

Read [the vision](docs/VISION.md) for product intent and [the contracts](contracts/)
for caller-facing requirements and internal execution obligations.

## Develop from this checkout

```sh
uv sync --extra dev
uv run stories --help
uv run stories manifest
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Python 3.12+ and Pango are required for artifact/rendering tests (on macOS,
`brew install pango`). No browser download or LibreOffice is required. The
Amplifier Agent dependency pins the supported revision in `pyproject.toml`;
`uv.lock` records the same revision. Advance the declaration and lock together,
then validate installation and runtime compatibility. Agent 0.23 uses a different
package layout and API; moving to it requires an explicit migration rather than
resolving its moving main branch during installation.

## Code structure

- Put the Python library in `src/amplifier_smart_tool_stories/`.
- Keep the `stories` CLI thin: argument parsing and I/O call library functions.
- Package prompts, styles and templates as resources; do not depend on a checkout.
- Use `amplifier-agent` for story reasoning. Speech synthesis uses direct provider
  APIs with separate bounded authority. Keep both integrations behind the library
  boundary and off import, help and deterministic code paths.
- Put executable checks and fixtures in `tests/`.

## Changes

- Keep tracked files focused on deliverables and durable contributor guidance.
  Put deliberations, research notes, scratch scripts, intermediate work products and
  local review materials in the gitignored `.work/` directory. Create it as needed;
  do not force-add its contents or depend on them for installation, tests or usage.
- Preserve source references and uncertainty through research, generation and conversion.
- Test library behavior as well as the CLI, including missing credentials, invalid
  inputs and incomplete artifacts.
- Check installation from an unrelated directory without relying on developer state.
- Keep generated outputs, credentials and private source material out of the repository.
- Preserve upstream licenses and attribution when reusing code or assets.
- Keep work items and their acceptance criteria in Work Tracker, not planning documents.
- Keep this file to durable contributor guidance; do not add session status or deliberation.

## Documentation ownership

- README is for people: purpose, an agent-assisted quick start, review/export flow,
  prerequisites and honest limits. Do not put checkout setup or API inventories there.
- AGENTS.md is contributor guidance. Agent callers use installed `stories --help`
  and subcommand help; `docs/USAGE.md` is the supporting caller guide.
- Update packaged `SMART_TOOL.md`, `help.py`, usage documentation and affected
  contracts together when public behavior changes. Top-level and subcommand help
  must remain provider-free operating skills. Keep examples valid against public
  signatures; callbacks are library-only.
- Keep source classification, calculation verification, revision disclosures and
  human acceptance distinct from semantic truth and model review. New revisions
  do not inherit acceptance. Continuations retain question context and require
  explicit bounded authority; retries must not repeat work.
- For MCP review changes, test lost acknowledgements after grant consumption and
  provider-disabled user submissions; neither path may silently replenish or burn allowance.

## Validation and delivery

Build with `uv build --out-dir .work/dist`. Install the wheel in a separate test
environment and exercise its CLI/library from outside the checkout. Verify packaged
help, prompts and other resources without repository imports or developer state.

Run `python <spec-checkout>/conformance/run.py <distribution-root>` using the
Smart Tools conformance kit. `smart-tool.json` expects `.venv/bin/stories`; provide
an installed environment at that location in the tested distribution. When the
checkout contains ignored test installations with additional manifests, use an
extracted source distribution so those copies do not pollute manifest discovery.
Report failures and skips accurately. Conformance is not an output-quality test.

Live evaluations require explicitly authorized provider use, prepared runtime and
fresh bounded stores. They are separate from ordinary tests:

```sh
uv run python tests/evaluate_quality.py --allow-model --provider openai \
  --store .work/evaluation --run-id unique-run
uv run python tests/evaluate_storytelling.py --allow-model --case case-study \
  --provider anthropic --model claude-sonnet-5 --store .work/case-study \
  --request-id case-study-1 --report .work/case-study-report.json
```

Read each script's help first. Trials spend tokens and may take several minutes.
Use fresh request IDs for new intent. Record failed candidates as well as successes;
inspect semantics, provenance and rendered output rather than treating model review
as independent proof. Keep reports, stores and screenshots in `.work/`. For UI changes,
exercise the actual browser flow and verify that material, draft and revision context
survive. Stop owned trial services when finished.

Report changes, relevant checks and remaining limits. Commit/push when requested.
