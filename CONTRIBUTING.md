# Contributing

This is a monorepo with two language peers and shared documentation:

```
.
├── haskell/      idea playground (low ceremony)
├── python/       production system (Phase 0+)
└── docs/         math.tex, ADRs, PHASES.md, ARCHITECTURE.md
```

`mise` is the entry point for every developer task. The repo's
`mise.toml` defines the task graph; per-language `mise.toml` files
pin tools.

## Setup (once per fresh checkout)

```bash
git clone <repo>
cd categorical-insurance
mise trust              # one-time: trust the mise.toml files
mise install            # installs pinned tools (python, uv, hx, ...)
mise run build:python   # uv sync the Python venv
mise run setup          # installs the pre-commit git hook
mise run test           # smoke: both languages green end-to-end
```

Optional: install `fourmolu` for Haskell formatting
(`cabal install fourmolu` or via the `hx` CLI). The pre-commit
fourmolu hook is configured for the *manual* stage so its absence
does not block commits.

## Daily tasks

Every command is `mise run <task>`. Use `mise tasks` to list.

| Task | What |
|---|---|
| `mise run build`    | Build everything across languages |
| `mise run test`     | Run all tests (`test:haskell` + `test:python`) |
| `mise run lint`     | Lint everything (currently `lint:python`) |
| `mise run fmt`      | Format everything (currently `fmt:python`) |
| `mise run repl:haskell` | Open `cabal repl` in `haskell/` |
| `mise run demo:risk`    | Run `Examples.RiskScore.demoRisk` |
| `mise run demo:insurance` | Run `Examples.Insurance.demo` |
| `mise run docs:math` | Build `docs/math.tex` to PDF |
| `mise run pre-commit:run` | Run every pre-commit hook against every file |

The `*:haskell` and `*:python` variants are also callable
explicitly when you want to scope.

## Conventions

These differ between the two language trees because the trees have
different roles.

### Haskell (`haskell/`) — idea playground

Low ceremony. Add modules under `haskell/src/Examples/` to prototype
ideas; rename freely; break the world if it helps you think. The
sketch is not a production target. The math companion at
`docs/math.tex` is the reference if you're checking that an
implementation matches the formal development.

### Python (`python/`) — production target

Production conventions are enforced because the system grows here:

- **`__all__` discipline.** Every `__init__.py` lists the public
  symbols. Names beginning with `_` are private; direct imports of
  underscored names are review-blocking. Python has no language-level
  privacy, so the categorical guarantee around `Contract` becomes a
  social contract here.
- **Reproducibility seeds.** Every stochastic operation accepts and
  propagates a seed; no reliance on default RNG.
- **Categorical correspondence annotations.** Every public function
  under the framework modules carries a `# math:` comment pointing at
  the corresponding `docs/math.tex` definition or theorem, e.g.
  `# math: Definition 12 (Decision)`. A pre-commit / CI check
  enforces presence (planned; not yet wired up).
- **Test-as-documentation.** Every example module exposes a
  `demo()` function that is both a runnable tutorial and a CI
  smoke test, mirroring the Haskell `Examples.RiskScore.demoRisk`
  pattern.
- **Test directory structure.** `tests/{unit,property,correctness,integration}/`
  per `docs/PHASES.md`. Hypothesis strategies live in
  `tests/strategies.py`; ad-hoc per-test generation is review-blocking.
- **Type checking.** `mypy --strict` on `src/catins/`, looser on
  tests. CI enforces both.

## Adding an ADR

Architecture decisions go under `docs/adr/NNN-short-title.md`,
numbered sequentially. The five existing ADRs (001–005) follow a
consistent format: Status, Context, Options Considered, Decision,
Category Model Fidelity (where relevant), Consequences. Match that
shape.

When in doubt about whether something needs an ADR, consider:

- Does it commit the project to a tool, framework, or library?
- Does it constrain how future code is written or organised?
- Will an engineer joining six months from now need to understand
  *why* this was chosen over alternatives?

If yes to any, write the ADR.

## Pull requests and commits

- One topic per PR; one logical change per commit. The migration
  plan in `docs/PHASES.md` is itself organised this way.
- Commit messages: imperative subject under 72 chars; body
  explaining *why*, not *what*.
- The Co-Authored-By line for Claude collaboration is welcome but
  not required; if used, name the model and version.

## References

- `README.md` — project overview.
- `docs/math.tex` — formal mathematical companion.
- `docs/adr/` — architecture decisions 001–005.
- `docs/PHASES.md` — phased rollout plan; `mise run` tasks track it.
- `docs/ARCHITECTURE.md` — production system architecture.
- `haskell/README.md`, `python/README.md` — per-language entry points.
