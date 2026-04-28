# categorical-insurance

A monorepo exploring the mathematics of using machine learning to write better
insurance policies, structured around a categorical core: **learners as
morphisms**, **governance as a comonad**, **decisions parameterised by a
monoid**, **contracts as the audited outputs of governed pipelines**.

The repository is two language peers around a shared core of documentation:

```
.
├── haskell/      idea playground (the original sketch; low ceremony)
├── python/       production-target system (Phase 0 substrate today)
└── docs/         math.tex, ADRs, PHASES.md, ARCHITECTURE.md, REFERENCES.md
```

[`mise`](https://mise.jdx.dev) sits at the root and dispatches every developer
task across both trees.

---

## Why

Pricing, underwriting, and policy design are increasingly informed by learned
models. Two recurring problems show up when you try to build such systems:

1. **Heterogeneity.** Classical actuarial techniques (Bayesian credibility,
   GLMs, Kalman filters) and modern ML (gradient-trained nets, kernel methods)
   are usually treated as disjoint toolkits. They are not — both fit a common
   structure: state, prediction, update.
2. **Governance.** Insurance contracts cannot be written freely; they must
   comply with regulatory, internal, and contractual constraints that
   themselves compose (federal + state + reinsurer + product line). Treating
   governance as an afterthought (runtime checks bolted onto a model) leaves
   the door open to contracts that should never have been constructed.

This project takes both problems as a single design question: **what is the
right algebra for "a model that learns from data, embedded in a context that
governs what contracts it may produce"?**

The answer pursued here is taken from category theory:

- A **learner** `A → B` is a morphism in a symmetric monoidal category, after
  Fong–Spivak–Tuyéras ("Backprop as Functor") and
  Cruttwell–Gavranović–Ghani–Wilson–Zanasi ("Categorical Foundations of
  Gradient-Based Learning").
- A **decision** is a function `P → M` valued in a monoid `M`. **Governance**
  (binary admit/deny via the free monoid on violations) and **guardrails**
  (graded scores via richer monoids) are the same structural object,
  distinguished only by their monoid choice and admissibility predicate.
- The **`Governed` comonad** carries a decision system as context for a
  proposal; **validation** is the co-Kleisli arrow that produces a contract
  iff the aggregated decisions satisfy the admissibility predicate.
- A **contract** is an opaque type whose only public introduction rule is
  `validate`. *No contract may exist that violates governance* becomes a
  static guarantee, not a runtime convention.

The full mathematical development is in [`docs/math.tex`](docs/math.tex);
the architectural choices in [`docs/adr/`](docs/adr/); the staged rollout in
[`docs/PHASES.md`](docs/PHASES.md).

## What

### The Haskell sketch (`haskell/`)

Roughly 300 lines of idiomatic Haskell exhibiting the categorical core and
worked examples:

```text
haskell/src/
  Learner.hs           -- Learner a b = ∃s. (s, s→a→b, s→a→b→s, s→a→b→a)
                       -- identity, compose, (>>>), parallel, runLearner, step
  Governance.hs        -- Comonad class; Governed p (Env comonad);
                       -- Governance p (Monoid); Rule, Violation
  DecisionSystem.hs    -- math.tex §VI: Decision m p, DecisionSystem m p,
                       -- aggregate, GovernedDS, GenContract, validateDS
  Contract.hs          -- abstract Contract; validate :: Governed p p
                       --                              -> Either [Violation] (Contract p)
  Examples/
    Credibility.hs     -- Normal–Normal Bayesian credibility (M = ()) ; Bühlmann
                       -- credibility falls out of the recursion
    Linear.hs          -- Online-SGD linear regression; request map carries
                       -- the input-gradient ∂L/∂x = (ŷ - y) w
    Proposal.hs        -- shared Proposal + ProductLine record
    Regulation.hs      -- composable regulatory bundles (federal, CA, NY)
    Guardrails.hs      -- "guardrail-flavoured" governance rules (binary
                       -- Decision[List Violation]; see ADR 005)
    RiskScore.hs       -- math.tex §VI worked instance: M = RiskScore
                       -- (additive non-negative reals); joint product-monoid
                       -- example combining binary governance with graded
                       -- guardrails; demoRisk :: IO () exercises both
    Insurance.hs       -- basicGovernance + defaultProposal + demo :: IO ()
                       -- composes regulatory bundles + guardrails into a
                       -- layered regime and exercises each layer
```

This tree is the **idea playground**: low ceremony, type-system-enforced
guarantees (the `Contract` abstraction barrier is a real one), reasoning
short-cuts that the production substrate has to recover by other means.

### The Python production system (`python/`)

Currently at **Phase 3** ([`docs/PHASES.md`](docs/PHASES.md)). The
engineering substrate is fully established, including:
- A categorical `Decision[M]` core and composable `Learner` optics (`catins/`).
- DuckDB/Parquet integrations for persistence.
- Snowpark-compatible Pandas vectorized UDF evaluation.
- First-class Dagster orchestration, including asset graphs for proposals, validation, and automated asset checks against schema drift and guardrail stability.
- A `pyproject.toml` (hatchling build, ruff, mypy `--strict`, pytest), `uv.lock` for reproducible installs, and CI workflow.

The conventions that recover the Haskell guarantees in a
language without privacy or `--strict` typing as a default are in
[`python/README.md`](python/README.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## How

### Setup (once per fresh checkout)

```bash
git clone <repo> && cd categorical-insurance
mise trust              # one-time: trust the mise.toml files
mise install            # installs pinned tools (python, uv, hx)
mise run build:python   # uv sync the Python venv
mise run setup          # installs the pre-commit git hook
mise run test           # smoke: both languages green end-to-end
```

### Daily tasks

```bash
mise tasks              # list everything
mise run test           # all tests across languages
mise run lint           # all linters (ruff + mypy --strict)
mise run fmt            # all formatters
mise run docs:math      # build docs/math.tex to PDF
```

Per-language scoping:

```bash
mise run test:haskell    mise run test:python
mise run lint:python     mise run fmt:python
```

Haskell demos run directly:

```bash
mise run repl:haskell        # cabal repl, ready to import Examples.*
mise run demo:risk           # Examples.RiskScore.demoRisk
mise run demo:insurance      # Examples.Insurance.demo
```

### Layered governance demo (Haskell)

The composed contract regime is built by `Monoid` composition of bundles
carried by the `Governed` comonad:

```haskell
caRegime = federalRegulations    -- federal statute
        <> california            -- state statute (Prop 103, min liability)
        <> internalUnderwriting  -- ML/pricing guardrails (binary)
        <> basicGovernance       -- premium > 0, loss-ratio cap, coverage cap
```

Switching jurisdictions is a one-line edit (`<> newYork`); a proposal that
passes federal but fails Prop 103 (or uses a federally prohibited rating
factor) is rejected with one violation per layer that catches it. The
`demo` exercises eleven proposals and produces output of the form:

```
=== composed governance: federal <> state <> guardrails <> underwriting ===
  CA / clean baseline                 → APPROVED
  CA / federal: prohibited factor     → REJECTED:
    - federal/protected_class: rating factors prohibited under federal law: ["race"]
    - ca/prop_103: Prop 103: rating factors not in approved auto set: ["race"]
  ...
```

`Examples.RiskScore.demoRisk` runs the same baseline through three regimes —
the `M = list[Violation]` governance, the `M = RiskScore` guardrail
(additive non-negative reals with thresholding admission), and the joint
product monoid `M = ([Violation], RiskScore)` — making math.tex §VI's
"same category, different monoids" concrete.

## Documentation

| Document | What |
|---|---|
| [`docs/math.tex`](docs/math.tex) | Formal mathematical companion (LaTeX/IEEEtran, build with `mise run docs:math`) |
| [`docs/adr/`](docs/adr/) | Five architecture decision records (governance locality, orchestration, learners vs Cortex, decision systems, governance vs guardrails) |
| [`docs/PHASES.md`](docs/PHASES.md) | Phased rollout plan (laptop MVP → multi-jurisdiction with replay → audit-aware research extensions) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Production system architecture on Snowflake |
| [`docs/REFERENCES.md`](docs/REFERENCES.md) | Bibliography of underlying papers |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Setup, mise tasks, per-language conventions, ADR authoring guidance |

## Status and direction

This is exploratory. Open threads worth pulling on (also captured in
math.tex's *Outlook* section and PHASES.md's Phase 5):

- **Probabilistic outputs.** Lift the codomain of `implement` from point
  estimates to distributions so guardrails can reason about posterior
  uncertainty, not only the mean.
- **Audit-aware governance.** Widen `Rule` / `Decision` to inspect a
  learner's audit trail (state at decision time, training history) rather
  than only the proposal.
- **Cokleisli arrows on `Governed`.** Layered governance is currently
  expressed via the `Monoid` instance carried by the comonad — composition
  is at the environment level, not the comonad itself. `extend` and
  `duplicate` become useful when arrows need to *transform* governance
  contextually (e.g., a re-audit step that injects additional rules based
  on what the proposal already passed).
- **Lens / Para alignment.** Sequential composition of learners embeds into
  the bicategory of optics via the `Para` construction. Making that
  explicit would let lens machinery be used directly on learner state.

## References

- Fong, Spivak, Tuyéras — *Backprop as Functor*
- Cruttwell, Gavranović, Ghani, Wilson, Zanasi — *Categorical Foundations of
  Gradient-Based Learning*
- Capucci, Gavranović, Hedges, Rischel — *Towards Foundations of Categorical
  Cybernetics*
- Bühlmann, Gisler — *A Course in Credibility Theory and its Applications*

Full bibliography in [`docs/REFERENCES.md`](docs/REFERENCES.md).

## License

MIT — see [`LICENSE`](LICENSE).
