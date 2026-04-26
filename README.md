# hx

A Haskell sketch exploring the mathematics of using machine learning to write
better insurance policies, structured around a categorical core: **learners as
morphisms**, **governance as a comonad**, **contracts as the audited outputs of
governed learner pipelines**.

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
  Gradient-Based Learning"). Bayesian conjugate updates, GLMs, and SGD are all
  instances of the same `(state, implement, update, request)` quadruple.
- **Governance** is modelled as a **comonad** `Governed p`. A value sits inside
  a governance context that travels with it; rule sets compose via a `Monoid`
  instance.
- A **contract** is an opaque type whose only public constructor is `validate`,
  which factors through the surrounding `Governance`. *No contract may exist
  that violates governance* becomes a static guarantee, not a runtime
  convention.

## What

The library defines, in roughly 200 lines, a categorical core plus two
worked-example learners and a governed-contract demo.

### The core

```text
src/
  Learner.hs       -- Learner a b = ∃s. (s, s→a→b, s→a→b→s, s→a→b→a)
                   -- identity, compose, (>>>), parallel, runLearner, step
  Governance.hs    -- Comonad class; Governed p (Env comonad);
                   -- Governance p (Monoid); Rule, Violation
  Contract.hs      -- abstract Contract; validate :: Governed p p
                   --                              -> Either [Violation] (Contract p)
```

A `Learner` carries a hidden state `s`. Two learners with different internal
representations are interchangeable at the `a → b` interface — this is what
lets a Bayesian credibility model and a neural net be composed in the same
pipeline.

`compose` is the FST/CGGWZ sequential composition: the composite state is the
pair of inner states, and the *request* map propagates target signals upstream
so the inner learner knows what to train against. `parallel` is the monoidal
product: two learners run side-by-side with independent state.

### Examples

```text
src/Examples/
  Credibility.hs   -- Normal–Normal conjugate Bayesian credibility model
                   --   as Learner () Double
                   --   classical Bühlmann credibility falls out of the recursion
  Linear.hs        -- Online-SGD linear regression
                   --   as Learner [Double] Double
                   --   request map carries the input-gradient ∂L/∂x = (ŷ - y) w
  Proposal.hs      -- shared Proposal + ProductLine record
  Regulation.hs    -- composable regulatory bundles:
                   --   federalRegulations  (protected class, ACA MLR floor)
                   --   california          (Prop 103, min auto liability)
                   --   newYork             (min auto liability)
                   --   forJurisdiction / forProductLine guard combinators
  Guardrails.hs    -- "guardrail-flavoured" governance rules (binary
                   --   Decision[List Violation] under the hood; see
                   --   ADR 005 + RiskScore.hs for the genuinely
                   --   monoid-parameterised guardrail)
  RiskScore.hs     -- math.tex §VI worked instance: M = RiskScore
                   --   (additive non-negative reals) with thresholding
                   --   admission; joint product-monoid example combining
                   --   binary governance with graded guardrails;
                   --   demoRisk :: IO () exercises both
  Insurance.hs     -- basicGovernance + defaultProposal + demo :: IO ()
                   --   demo composes regulatory bundles and guardrails into
                   --   a layered regime and exercises each layer
```

The `DecisionSystem` module at the top level (`src/DecisionSystem.hs`)
implements math.tex §VI: `Decision m p = p -> m`, `DecisionSystem m p =
[Decision m p]`, `aggregate`, `GovernedDS` (Env comonad over a decision
system), abstract `GenContract`, and `validateDS` parameterised by an
admissibility predicate `m -> Bool`. Governance, Guardrails, and the
joint product monoid are all instances of this one substrate, per
ADR 005.

#### Layered governance

The demo's contract regime is constructed by `Monoid` composition of four
governance bundles carried by the `Governed` comonad:

```haskell
caRegime = federalRegulations    -- federal statute
        <> california            -- state statute (Prop 103, min liability)
        <> internalUnderwriting  -- ML/pricing guardrails
        <> basicGovernance       -- premium > 0, loss-ratio cap, coverage cap
```

Switching jurisdictions is a one-line edit (`<> newYork` instead of
`<> california`), and a proposal that passes federal but fails Prop 103 (or
that uses a federally prohibited rating factor) is rejected with one
violation per layer that catches it — making layered enforcement legible
rather than collapsing into a single yes/no.

The `demo` shows:

- A credibility learner whose posterior mean tracks the empirical claim mean.
- A linear regressor recovering known weights `[2, 3]` to ~10 digits after
  1400 SGD steps.
- A two-policy portfolio learned via `parallel`, with independent posteriors.
- Eleven proposals run through the layered regime: one approved, ten rejected
  across federal, state, internal-guardrail, and basic-underwriting layers.

## How

### Toolchain

This project is managed by [`hx`](https://github.com/raskell-io/hx), an
opinionated Haskell toolchain CLI.

```bash
hx --version           # confirm hx is installed
hx build               # build the library
hx watch               # rebuild on file changes
hx repl                # interactive GHCi (used to run the demo)
hx fmt                 # format with fourmolu
hx lock / hx sync      # lockfile-pinned reproducible builds
```

`cabal` works directly as well; the project is a plain `cabal-version: 3.0`
library targeting GHC 9.14.

### Running the demo

```bash
cabal repl
ghci> import Examples.Insurance
ghci> demo
```

Expected output (abridged):

```
=== Bayesian credibility learner ===
  posterior mean  : 1224.91...

=== linear regression learner ===
  recovered ≈ [2.0000..., 2.9999...]

=== parallel portfolio (two policies) ===
  posterior means : (1012.4..., 2170.7...)

=== composed governance: federal <> state <> guardrails <> underwriting ===
  CA / clean baseline                 → APPROVED
  CA / federal: prohibited factor     → REJECTED:
    - federal/protected_class: rating factors prohibited under federal law: ["race"]
    - ca/prop_103: Prop 103: rating factors not in approved auto set: ["race"]
  CA / Prop 103: factor not approved  → REJECTED:
    - ca/prop_103: ...
  CA / state: sub-min auto liability  → REJECTED:
    - ca/min_auto_liability: California auto liability minimum is 15,000
  NY / state: sub-min auto liability  → REJECTED:
    - ny/min_auto_liability: New York auto liability minimum is 25,000
  guardrail / no insured consent      → REJECTED:
    - guardrail/consent: insured consent for data use is required
  guardrail / rate shock vs prior     → REJECTED:
    - guardrail/rate_stability: ...
  guardrail / low explainability      → REJECTED:
    - guardrail/explainability: ...
  guardrail / large coverage no re    → REJECTED:
    - guardrail/reinsurance_cession: ...
  underwriting / loss ratio > cap     → REJECTED:
    - max_loss_ratio: ...
    - coverage_cap: ...
  underwriting / coverage > 10x prem  → REJECTED:
    - coverage_cap: ...
```

### Writing a new learner

A learner is a single value of type `Learner a b`:

```haskell
myLearner :: Learner Input Output
myLearner = Learner
    initialState
    (\s a   -> ...)        -- implement: predict given state and input
    (\s a b -> ...)        -- update:    revise state given input + target
    (\s a b -> ...)        -- request:   propagate a target signal upstream
```

Compose with `(>>>)` and `parallel`; train with `step`.

### Writing a governance rule

Rules are predicates on the proposal type, returning `Just Violation` on
failure:

```haskell
solvencyRule :: Rule Proposal
solvencyRule = Rule "solvency" $ \p ->
    if reservesAdequate p
        then Nothing
        else Just (Violation "solvency" "reserve coverage below threshold")
```

Compose rules with `addRule` or `<>` over `Governance`. Bind a proposal as a
`Contract` only via `validate`.

## Status and direction

This is an exploratory sketch, not a library aiming for production use. Open
threads worth pulling on:

- **Probabilistic outputs.** Lift `b` from point estimates to distributions so
  governance can reason about posterior uncertainty, not just the mean.
- **Audit-aware governance.** Widen `Rule` to inspect a learner's audit trail
  (state at decision time, training history) rather than only the proposal.
- **Cokleisli arrows on `Governed`.** Layered governance is currently
  expressed via the `Monoid` instance on `Governance` carried by the
  comonad — composition is at the environment level, not the comonad
  itself. `extend` and `duplicate` become useful when arrows need to
  *transform* governance contextually (e.g., a re-audit step that injects
  additional rules based on what the proposal already passed).
- **Lens / Para alignment.** Sequential composition of learners embeds into
  the bicategory of optics via the `Para` construction. Making that explicit
  would let lens machinery be used directly on learner state.

## Mathematical write-up

A self-contained mathematical companion lives at
[`docs/math.tex`](docs/math.tex). It covers the category of learners
(definition, sequential composition, monoidal product), the two
worked instances (Bühlmann credibility, gradient linear regression),
the Env comonad over the monoid of governance objects, validation as
a co-Kleisli arrow, and layered regulation. Diagrams are typeset with
`tikz-cd`. Build with:

```bash
cd docs && latexmk -pdf math.tex
```

A bibliography of the underlying papers is maintained at
[`docs/REFERENCES.md`](docs/REFERENCES.md).

## References

- Fong, Spivak, Tuyéras — *Backprop as Functor*
- Cruttwell, Gavranović, Ghani, Wilson, Zanasi — *Categorical Foundations of
  Gradient-Based Learning*
- Capucci, Gavranović, Hedges, Rischel — *Towards Foundations of Categorical
  Cybernetics*
- Bühlmann, Gisler — *A Course in Credibility Theory and its Applications*

## License

MIT.
