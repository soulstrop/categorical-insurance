# Haskell sketch

This directory holds the Haskell exploration of the categorical
insurance project: the ~300-line categorical core (`Learner`,
`Governance`, `DecisionSystem`, `Contract`) and the example modules
that demonstrate how the math composes (`Examples.Credibility`,
`Examples.Linear`, `Examples.Insurance`, `Examples.Regulation`,
`Examples.Guardrails`, `Examples.RiskScore`).

It is intentionally low-ceremony — a playground for ideas — and is
not the production target. The Python production system lives in
`../python/` (yet to be added; see `../docs/PHASES.md`).

## Run it

Once the root `mise.toml` is in place (step 2 of the migration in
`../docs/PHASES.md`):

```bash
mise run repl:haskell        # cabal repl, ready to import Examples.*
mise run demo:risk           # runs Examples.RiskScore.demoRisk
mise run test:haskell        # cabal build (no test suite yet)
```

Or, directly with `cabal`:

```bash
cabal repl
ghci> import Examples.Insurance
ghci> demo
```

## References

* `../docs/math.tex` — the mathematical companion. The Haskell types
  here trace one-to-one to the definitions and theorems there.
* `../docs/adr/` — architecture decision records (governance
  evaluation locality, orchestration, learner discipline,
  decision-systems substrate, governance vs guardrails).
* `../docs/PHASES.md` — staged rollout from this sketch to the
  Python production system.
