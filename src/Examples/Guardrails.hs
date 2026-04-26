-- | Composable internal guardrails for ML-driven insurance pricing.
--
-- These are not statutory; they are first-line internal controls a
-- carrier can compose with any regulatory governance via '<>'. Each
-- guardrail addresses a recurring concern when learned models price
-- contracts:
--
--   * 'consentRequired'        — data ethics
--   * 'rateStability'          — market behaviour, rate-shock prevention
--   * 'explainabilityFloor'    — model auditability
--   * 'reinsuranceCession'     — capital adequacy on large risks
--
-- The bundle 'internalUnderwriting' wires them up with conservative
-- defaults; tune per book of business or compose individually.
--
-- == Naming caveat (ADR 005)
--
-- Each entry below is a 'Rule' — that is, a 'Decision' valued in the
-- @Maybe Violation@ \/ @[Violation]@ monoid with binary admit/deny.
-- By the vocabulary of ADR 005 (\"Governance and Guardrails — Same
-- Category, Different Monoids\") these are therefore *additional
-- governance rules*, not categorical guardrails: each fires on or off,
-- independently of the others, with conjunctive composition.
--
-- The name \"guardrails\" is retained here because the *concerns*
-- addressed (consent, rate stability, explainability, reinsurance)
-- are guardrail-flavoured in product discussions even when the
-- implementation chooses a binary monoid for simplicity.
--
-- For a categorical guardrail in the strict ADR-005 sense — a
-- decision system valued in a non-binary monoid with a thresholding
-- admissibility predicate — see "Examples.RiskScore", which exhibits
-- 'RiskScore' (the additive non-negative real monoid) and the joint
-- product-monoid composition described in math.tex §VI.
module Examples.Guardrails
    ( consentRequired
    , rateStability
    , explainabilityFloor
    , reinsuranceCession
    , internalUnderwriting
    ) where

import Examples.Proposal
import Governance

-- | The insured must have consented to data use.
consentRequired :: Rule Proposal
consentRequired = Rule "guardrail/consent" $ \p ->
    if proposalConsent p
        then Nothing
        else
            Just
                ( Violation
                    "guardrail/consent"
                    "insured consent for data use is required"
                )

-- | Year-over-year premium change bounded by @cap@ (relative).
-- No-ops when there is no prior premium on file.
rateStability :: Double -> Rule Proposal
rateStability cap = Rule "guardrail/rate_stability" $ \p ->
    case proposalPriorPremium p of
        Nothing -> Nothing
        Just prev
            | prev <= 0 -> Nothing
            | otherwise ->
                let delta = abs (proposalPremium p - prev) / prev
                 in if delta > cap
                        then
                            Just
                                ( Violation
                                    "guardrail/rate_stability"
                                    ( "year-over-year premium change "
                                        <> show delta
                                        <> " exceeds cap "
                                        <> show cap
                                    )
                                )
                        else Nothing

-- | The model must be at least @lo@-explainable on a [0, 1] scale.
explainabilityFloor :: Double -> Rule Proposal
explainabilityFloor lo = Rule "guardrail/explainability" $ \p ->
    if proposalExplainabilityScore p >= lo
        then Nothing
        else
            Just
                ( Violation
                    "guardrail/explainability"
                    ( "model explainability "
                        <> show (proposalExplainabilityScore p)
                        <> " below floor "
                        <> show lo
                    )
                )

-- | If coverage exceeds @threshold@, require at least @minCession@
-- (fraction in [0, 1]) ceded to a reinsurer.
reinsuranceCession :: Double -> Double -> Rule Proposal
reinsuranceCession threshold minCession =
    Rule "guardrail/reinsurance_cession" $ \p ->
        if proposalCoverage p <= threshold
            then Nothing
            else
                if proposalCession p >= minCession
                    then Nothing
                    else
                        Just
                            ( Violation
                                "guardrail/reinsurance_cession"
                                ( "coverage "
                                    <> show (proposalCoverage p)
                                    <> " exceeds "
                                    <> show threshold
                                    <> "; cession "
                                    <> show (proposalCession p)
                                    <> " below required "
                                    <> show minCession
                                )
                            )

-- | Bundled internal guardrails with conservative defaults.
internalUnderwriting :: Governance Proposal
internalUnderwriting =
    addRule consentRequired $
        addRule (rateStability 0.25) $
            addRule (explainabilityFloor 0.6) $
                addRule (reinsuranceCession 100000 0.5) mempty
