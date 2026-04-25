-- | End-to-end demo: train learners, build a 'Proposal' from their
-- output, and validate it through layered, composable 'Governance'.
--
-- The contract regime is constructed by 'Monoid' composition of four
-- bundles carried by the 'Governed' comonad:
--
--   * 'Examples.Regulation.federalRegulations'  — federal statute
--   * 'Examples.Regulation.california' \/ '.newYork' — state statute
--   * 'Examples.Guardrails.internalUnderwriting' — internal ML/pricing
--                                                  guardrails
--   * 'basicGovernance'                          — basic underwriting
--                                                  hygiene
--
-- Their order of composition is irrelevant (the underlying 'Monoid' is
-- commutative for our purposes — rule predicates do not interact),
-- but reading left-to-right roughly captures decreasing legal weight
-- and increasing carrier discretion.
module Examples.Insurance
    ( -- * Proposal (re-exported)
      Proposal (..)
    , ProductLine (..)
    , defaultProposal

      -- * Basic underwriting hygiene
    , basicGovernance
    , positivePremium
    , maxLossRatio
    , coverageCap

      -- * Demo
    , demo
    ) where

import Contract
import Examples.Credibility (credibilityLearner)
import Examples.Guardrails (internalUnderwriting)
import Examples.Linear (linearLearner)
import Examples.Proposal
import Examples.Regulation (california, federalRegulations, newYork)
import Governance
import Learner

-- | A Proposal seeded from an expected-claim value; defaults pass all
-- four governance layers when used as-is.
defaultProposal :: Double -> Proposal
defaultProposal ec =
    Proposal
        { proposalPremium = ec * 1.65
        , proposalCoverage = ec * 14
        , proposalExpectedClaim = ec
        , proposalJurisdiction = "CA"
        , proposalProductLine = Auto
        , proposalRatingFactors = ["driving_record", "miles_driven"]
        , proposalConsent = True
        , proposalPriorPremium = Just (ec * 1.55)
        , proposalExplainabilityScore = 0.75
        , proposalCession = 0.0
        }

positivePremium :: Rule Proposal
positivePremium = Rule "positive_premium" $ \p ->
    if proposalPremium p > 0
        then Nothing
        else Just (Violation "positive_premium" "premium must be > 0")

maxLossRatio :: Double -> Rule Proposal
maxLossRatio cap = Rule "max_loss_ratio" $ \p ->
    if proposalPremium p <= 0
        then Nothing
        else
            let lr = proposalExpectedClaim p / proposalPremium p
             in if lr > cap
                    then
                        Just
                            ( Violation
                                "max_loss_ratio"
                                ("loss ratio " <> show lr <> " exceeds cap " <> show cap)
                            )
                    else Nothing

coverageCap :: Double -> Rule Proposal
coverageCap mult = Rule "coverage_cap" $ \p ->
    if proposalCoverage p <= mult * proposalPremium p
        then Nothing
        else
            Just
                ( Violation
                    "coverage_cap"
                    ("coverage exceeds " <> show mult <> "x premium")
                )

basicGovernance :: Governance Proposal
basicGovernance =
    addRule (coverageCap 10) $
        addRule (maxLossRatio 0.85) $
            addRule positivePremium mempty

trainCredibility :: [Double] -> Learner () Double
trainCredibility =
    foldl' (\l x -> step l () x) (credibilityLearner 1000 1e-7 250000)

trainLinear :: [([Double], Double)] -> Learner [Double] Double
trainLinear =
    foldl' (\l (xs, y) -> step l xs y) (linearLearner 0.01 [0, 0])

demo :: IO ()
demo = do
    putStrLn "=== Bayesian credibility learner ==="
    let claims = [1200, 1500, 980, 1100, 1300, 1450, 1050]
        cred = trainCredibility claims
        ec = runLearner cred ()
    putStrLn $ "  observed claims : " ++ show claims
    putStrLn $ "  posterior mean  : " ++ show ec

    putStrLn ""
    putStrLn "=== linear regression learner ==="
    let truth xs = sum (zipWith (*) [2, 3] xs)
        pts = [[1, 2], [3, 1], [2, 2], [4, 1], [0, 3], [2, 0], [1, 1]]
        training = [(p, truth p) | p <- pts]
        lin = trainLinear (concat (replicate 200 training))
    putStrLn "  truth weights ≈ [2.0, 3.0]"
    putStrLn $ "  recovered ≈ " ++ show [runLearner lin [1, 0], runLearner lin [0, 1]]

    putStrLn ""
    putStrLn "=== parallel portfolio (two policies) ==="
    let two =
            parallel
                (credibilityLearner 1000 1e-7 250000)
                (credibilityLearner 2000 1e-7 1000000)
        pairs = [(800, 1900), (1200, 2400), (950, 2100), (1100, 2300)]
        two' = foldl' (\l (a, b) -> step l ((), ()) (a, b)) two pairs
    putStrLn $ "  posterior means : " ++ show (runLearner two' ((), ()))

    putStrLn ""
    putStrLn "=== composed governance: federal <> state <> guardrails <> underwriting ==="
    let baseline = defaultProposal ec
        caRegime = federalRegulations <> california <> internalUnderwriting <> basicGovernance
        nyRegime = federalRegulations <> newYork <> internalUnderwriting <> basicGovernance

    showResult "CA / clean baseline                " $
        validate (withGovernance caRegime baseline)

    showResult "CA / federal: prohibited factor    " $
        validate
            ( withGovernance
                caRegime
                baseline {proposalRatingFactors = ["driving_record", "race"]}
            )

    showResult "CA / Prop 103: factor not approved " $
        validate
            ( withGovernance
                caRegime
                baseline {proposalRatingFactors = ["driving_record", "credit_score"]}
            )

    showResult "CA / state: sub-min auto liability " $
        validate (withGovernance caRegime baseline {proposalCoverage = 10000})

    showResult "NY / state: sub-min auto liability " $
        validate
            ( withGovernance
                nyRegime
                baseline
                    { proposalJurisdiction = "NY"
                    , proposalCoverage = 20000
                    }
            )

    showResult "guardrail / no insured consent     " $
        validate (withGovernance caRegime baseline {proposalConsent = False})

    showResult "guardrail / rate shock vs prior    " $
        validate (withGovernance caRegime baseline {proposalPremium = ec * 2.20})

    showResult "guardrail / low explainability     " $
        validate
            (withGovernance caRegime baseline {proposalExplainabilityScore = 0.40})

    showResult "guardrail / large coverage no re   " $
        validate
            ( withGovernance
                caRegime
                baseline
                    { proposalCoverage = 150000
                    , proposalPremium = ec * 30
                    , proposalCession = 0.0
                    , proposalPriorPremium = Nothing
                    }
            )

    showResult "underwriting / loss ratio > cap    " $
        validate
            ( withGovernance
                caRegime
                baseline
                    { proposalPremium = ec * 1.05
                    , proposalPriorPremium = Nothing
                    }
            )

    showResult "underwriting / coverage > 10x prem " $
        validate (withGovernance caRegime baseline {proposalCoverage = ec * 25})
  where
    showResult name (Right _) =
        putStrLn $ "  " ++ name ++ " → APPROVED"
    showResult name (Left vs) = do
        putStrLn $ "  " ++ name ++ " → REJECTED:"
        mapM_
            (\v -> putStrLn $ "    - " ++ violationRule v ++ ": " ++ violationDetail v)
            vs
