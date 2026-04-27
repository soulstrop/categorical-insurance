# Python production system

This directory holds the production-target implementation of the
categorical insurance framework. It is currently a **Phase 0
skeleton** (per `../docs/PHASES.md`); the engineering substrate
is in place but no framework code has been written yet.

The Haskell sketch in `../haskell/` is the exploratory companion;
the math in `../docs/math.tex` is the unifying reference.

## Quick start

From anywhere in the repo:

```bash
mise run build:python    # uv sync the dev environment
mise run test:python     # pytest
mise run lint:python     # ruff + mypy --strict on src/catins
mise run fmt:python      # ruff format + ruff check --fix
```

Or directly with uv:

```bash
cd python
uv sync                  # installs from uv.lock into .venv/
uv run pytest
uv run ruff check .
uv run mypy --strict src/catins
```

## Layout

```text
python/
├── pyproject.toml        # build (hatchling), deps, ruff, mypy, pytest
├── uv.lock               # locked dependency graph
├── src/
│   └── catins/           # the production package; importable as `catins`
│       ├── __init__.py   # public API; __all__ enforces hygiene
│       └── ...           # framework modules land here in Phase 0
└── tests/
    ├── conftest.py       # pytest fixtures
    ├── strategies.py     # Hypothesis strategy library (Phase 1)
    └── test_smoke.py     # placeholder; removed when real tests land
```

In Phase 0 the framework grows under `src/catins/`:

```text
src/catins/
├── learner/              # Learner data type, compose, parallel, step
├── governance/           # Governed comonad, Rule, Violation
├── decisions/            # Decision[M], DecisionSystem, validate_M
├── monoids/              # one module per Monoid[M] (ADR 005)
├── contract/             # abstract Contract; from_validated factory
└── examples/             # one demo() per module (test-as-documentation)
```

In Phase 1 `tests/` grows the Phase-1-mandated subdirectories:

```text
tests/
├── unit/
├── property/             # category laws, monoid laws, conjunctivity
├── correctness/          # learner smoke tests on fixtures
└── integration/
```

## Conventions

These are repo-wide conventions, called out here because they
distinguish the production target from the playground:

* **`__all__` discipline.** Public symbols are explicitly listed in
  every `__init__.py`. Names beginning with `_` are private; direct
  imports of underscored names are review-blocking. Python has no
  language-level privacy, so the categorical guarantee around
  `Contract` becomes a social contract here.
* **Reproducibility seeds.** Every stochastic operation accepts and
  propagates a seed; no reliance on default RNG.
* **Categorical correspondence.** Every public function carries a
  `# math:` comment pointing at the corresponding definition or
  theorem in `../docs/math.tex`. A pre-commit / CI check enforces
  presence.
* **Test-as-documentation.** Every example module exposes a
  `demo()` function that is both a runnable tutorial and a CI
  smoke test (mirroring the Haskell `Examples.RiskScore.demoRisk`
  pattern).

## References

* `../docs/math.tex` — formal mathematical companion.
* `../docs/adr/` — architecture decision records.
* `../docs/PHASES.md` — staged rollout; this directory is Phase 0
  skeleton today.
* `../haskell/` — the Haskell sketch this implementation tracks.
