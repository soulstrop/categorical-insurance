-- | A small end-to-end demo: train learners, build a 'Proposal' from
-- their output, and validate it through a composable 'Governance'.
module Examples.Insurance
    ( Proposal (..)
    , basicGovernance
    , demo
    ) where

import Contract
import Examples.Credibility (credibilityLearner)
import Examples.Linear (linearLearner)
import Governance
import Learner

data Proposal = Proposal
    { proposalPremium :: !Double
    , proposalCoverage :: !Double
    , proposalExpectedClaim :: !Double
    }
    deriving (Show)

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
    putStrLn $ "  truth weights ≈ [2.0, 3.0]"
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
    putStrLn "=== contract validation ==="
    let loaded =
            Proposal
                { proposalPremium = ec * 1.40
                , proposalCoverage = ec * 8
                , proposalExpectedClaim = ec
                }
        underpriced = loaded {proposalPremium = ec * 1.05}
        overcovered = loaded {proposalCoverage = ec * 25}
    showResult "loaded     " (validate (withGovernance basicGovernance loaded))
    showResult "underpriced" (validate (withGovernance basicGovernance underpriced))
    showResult "overcovered" (validate (withGovernance basicGovernance overcovered))
  where
    showResult name (Right c) =
        putStrLn $ "  " ++ name ++ " → APPROVED: " ++ show (contractView c)
    showResult name (Left vs) = do
        putStrLn $ "  " ++ name ++ " → REJECTED:"
        mapM_ (\v -> putStrLn $ "    - " ++ violationRule v ++ ": " ++ violationDetail v) vs
