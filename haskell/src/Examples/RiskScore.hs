-- | A worked instance of "DecisionSystem" using a non-trivial monoid.
--
-- This module makes math.tex §VI's \"Guardrails (additive risk score)\"
-- worked instance concrete. A 'RiskScore' is the additive monoid of
-- non-negative reals; admission is a strict-less-than comparison
-- against a cap.
--
-- The module also demonstrates math.tex §VI's \"Joint governance and
-- guardrails\" instance: the product monoid @([Violation], RiskScore)@
-- composes binary governance with graded guardrails into a single
-- decision system, with the joint admissibility predicate the
-- conjunction of the components'.
--
-- Together with "DecisionSystem" and "Governance", this module gives
-- the Haskell sketch full correspondence with math.tex §VI: at least
-- two distinct monoid choices (@[Violation]@ and 'RiskScore'), plus
-- their product, are exhibited as 'Decision' instances on the same
-- 'Examples.Proposal.Proposal' type.
module Examples.RiskScore
    ( -- * The risk-score monoid
      RiskScore (..)

      -- * Risk decisions
    , highCoverageRisk
    , lowExplainabilityRisk
    , highLossRatioRisk
    , riskBudget

      -- * Risk-only validation
    , validateRiskBudget

      -- * Joint governance + risk validation
    , liftViolation
    , liftRisk
    , jointBundle
    , validateJoint

      -- * Demo
    , demoRisk
    ) where

import Contract (validate)
import DecisionSystem
import qualified Examples.Insurance as I
import Examples.Proposal
import Governance

-- | A risk score: non-negative additive monoid. Higher = more risk.
newtype RiskScore = RiskScore {getRiskScore :: Double}
    deriving (Show, Eq, Ord)

instance Semigroup RiskScore where
    RiskScore a <> RiskScore b = RiskScore (a + b)

instance Monoid RiskScore where
    mempty = RiskScore 0

-- ----------------------------------------------------------------
-- Risk decisions
-- ----------------------------------------------------------------

-- | High coverage adds risk; very high coverage adds more.
highCoverageRisk :: Decision RiskScore Proposal
highCoverageRisk p
    | proposalCoverage p > 30000 = RiskScore 0.30
    | proposalCoverage p > 20000 = RiskScore 0.15
    | otherwise = RiskScore 0

-- | Low model explainability adds risk proportional to the gap below 0.8.
lowExplainabilityRisk :: Decision RiskScore Proposal
lowExplainabilityRisk p =
    RiskScore (max 0 (0.8 - proposalExplainabilityScore p))

-- | Loss ratio above 0.5 adds risk proportional to the excess.
highLossRatioRisk :: Decision RiskScore Proposal
highLossRatioRisk p
    | proposalPremium p <= 0 = RiskScore 0
    | otherwise =
        let lr = proposalExpectedClaim p / proposalPremium p
         in RiskScore (max 0 (lr - 0.5))

-- | Bundled risk-score guardrails.
riskBudget :: DecisionSystem RiskScore Proposal
riskBudget = [highCoverageRisk, lowExplainabilityRisk, highLossRatioRisk]

-- ----------------------------------------------------------------
-- Risk-only validation
-- ----------------------------------------------------------------

-- | Admit the proposal as a risk-budgeted contract iff the aggregated
-- risk score is strictly below @cap@.
validateRiskBudget ::
    -- | risk cap
    Double ->
    Proposal ->
    Either RiskScore (GenContract RiskScore Proposal)
validateRiskBudget cap p =
    validateDS
        (\(RiskScore r) -> r < cap)
        (withDecisions riskBudget p)

-- ----------------------------------------------------------------
-- Joint governance + risk
-- ----------------------------------------------------------------

-- | Lift a binary 'Rule' into a decision in the product monoid: a
-- failing rule contributes its violation to the left component and
-- the additive identity to the right.
liftViolation :: Rule p -> Decision ([Violation], RiskScore) p
liftViolation (Rule _ pr) p = case pr p of
    Nothing -> ([], mempty)
    Just v -> ([v], mempty)

-- | Lift a risk decision into the product monoid: contributes nothing
-- to the violation list and its score to the right component.
liftRisk :: Decision RiskScore p -> Decision ([Violation], RiskScore) p
liftRisk d p = ([], d p)

-- | Joint bundle: 'Examples.Insurance.basicGovernance' lifted into the
-- product monoid alongside the lifted 'riskBudget'. Either layer can
-- veto admission.
jointBundle :: DecisionSystem ([Violation], RiskScore) Proposal
jointBundle =
    [liftViolation r | r <- governanceRules I.basicGovernance]
        ++ map liftRisk riskBudget

-- | Joint admissibility: empty violation list AND risk score below cap.
validateJoint ::
    -- | risk cap
    Double ->
    Proposal ->
    Either ([Violation], RiskScore) (GenContract ([Violation], RiskScore) Proposal)
validateJoint cap p =
    validateDS
        (\(vs, RiskScore r) -> null vs && r < cap)
        (withDecisions jointBundle p)

-- ----------------------------------------------------------------
-- Demo
-- ----------------------------------------------------------------

-- | A demonstration of the M-parameterised framework: aggregate a risk
-- score over a baseline proposal, attempt admission under two
-- monoids (risk-only and joint), and contrast with the binary
-- governance decision.
demoRisk :: IO ()
demoRisk = do
    let ec = 1500
        baseline = I.defaultProposal ec
        cap = 0.5

    putStrLn "=== M = RiskScore (additive guardrail) ==="
    let RiskScore total = aggregate riskBudget baseline
    putStrLn $ "  baseline coverage      : " ++ show (proposalCoverage baseline)
    putStrLn $ "  baseline explainability: " ++ show (proposalExplainabilityScore baseline)
    putStrLn $ "  baseline loss ratio    : " ++ show (proposalExpectedClaim baseline / proposalPremium baseline)
    putStrLn $ "  total risk score       : " ++ show total
    putStrLn $ "  admission cap          : " ++ show cap
    case validateRiskBudget cap baseline of
        Right _ -> putStrLn "  → ADMITTED under risk-only regime"
        Left (RiskScore r) ->
            putStrLn $ "  → REJECTED under risk-only regime (score " ++ show r ++ ")"

    putStrLn ""
    putStrLn "=== M = ([Violation], RiskScore) (joint product monoid) ==="
    case validateJoint cap baseline of
        Right _ -> putStrLn "  → ADMITTED under joint regime"
        Left (vs, RiskScore r) -> do
            putStrLn $ "  → REJECTED under joint regime"
            putStrLn $ "      violations : " ++ show (length vs)
            mapM_ (\v -> putStrLn $ "        - " ++ violationRule v) vs
            putStrLn $ "      risk score : " ++ show r

    putStrLn ""
    putStrLn "=== M = [Violation] (basicGovernance, binary) ==="
    case validate (withGovernance I.basicGovernance baseline) of
        Right _ -> putStrLn "  → ADMITTED under basic governance"
        Left vs -> do
            putStrLn "  → REJECTED under basic governance:"
            mapM_ (\v -> putStrLn $ "    - " ++ violationRule v) vs
