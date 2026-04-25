-- | Composable regulatory governance bundles: federal and per-state.
--
-- Each bundle is a 'Governance' value over the 'Proposal' type. They
-- compose via the 'Monoid' instance — e.g.
-- @federalRegulations <> california@ produces the joint regulatory
-- regime applicable to a contract being issued in California.
--
-- The 'Governed' comonad carries the composite environment; the
-- 'Monoid' is the structure being composed, not the comonad itself.
-- Carrying the layered governance through a 'Governed' value means a
-- contract can never be constructed (via "Contract".'Contract.validate')
-- without seeing every layer that applies to it.
module Examples.Regulation
    ( -- * Bundles
      federalRegulations
    , california
    , newYork

      -- * Guards
    , forJurisdiction
    , forProductLine
    , guarded
    ) where

import Examples.Proposal
import Governance

-- | Run a rule's predicate only when a guard on the proposal holds.
guarded :: (Proposal -> Bool) -> Rule Proposal -> Rule Proposal
guarded g (Rule nm f) =
    Rule nm $ \p -> if g p then f p else Nothing

-- | Restrict a rule to a specific jurisdiction code (e.g. @\"CA\"@).
forJurisdiction :: String -> Rule Proposal -> Rule Proposal
forJurisdiction code = guarded (\p -> proposalJurisdiction p == code)

-- | Restrict a rule to a specific 'ProductLine'.
forProductLine :: ProductLine -> Rule Proposal -> Rule Proposal
forProductLine line = guarded (\p -> proposalProductLine p == line)

-- ----------------------------------------------------------------
-- Federal
-- ----------------------------------------------------------------

-- | Rating factors prohibited under federal civil rights law (Title
-- VII, ADA, ECOA, Fair Housing Act) and GINA (genetic information).
prohibitedFederalFactors :: [String]
prohibitedFederalFactors =
    [ "race"
    , "color"
    , "religion"
    , "national_origin"
    , "sex"
    , "disability"
    , "genetic_information"
    ]

federalProtectedClassRule :: Rule Proposal
federalProtectedClassRule = Rule "federal/protected_class" $ \p ->
    let bad = filter (`elem` prohibitedFederalFactors) (proposalRatingFactors p)
     in case bad of
            [] -> Nothing
            xs ->
                Just
                    ( Violation
                        "federal/protected_class"
                        ("rating factors prohibited under federal law: " <> show xs)
                    )

-- | ACA medical-loss-ratio floor for health insurance: claims must be
-- at least 80% of premium for individual and small-group plans (large
-- group is 85%; we use the 80% floor for the demo).
acaMinimumLossRatio :: Rule Proposal
acaMinimumLossRatio =
    forProductLine Health $
        Rule "federal/aca_min_loss_ratio" $ \p ->
            if proposalPremium p <= 0
                then Nothing
                else
                    let lr = proposalExpectedClaim p / proposalPremium p
                     in if lr < 0.80
                            then
                                Just
                                    ( Violation
                                        "federal/aca_min_loss_ratio"
                                        ("ACA: health loss ratio " <> show lr <> " below 0.80 floor")
                                    )
                            else Nothing

federalRegulations :: Governance Proposal
federalRegulations =
    addRule federalProtectedClassRule $
        addRule acaMinimumLossRatio mempty

-- ----------------------------------------------------------------
-- California (Prop 103)
-- ----------------------------------------------------------------

caProp103PermittedAutoFactors :: [String]
caProp103PermittedAutoFactors =
    [ "driving_record"
    , "miles_driven"
    , "years_driving_experience"
    ]

caProp103Rule :: Rule Proposal
caProp103Rule =
    forJurisdiction "CA" $
        forProductLine Auto $
            Rule "ca/prop_103" $ \p ->
                let bad =
                        filter
                            (`notElem` caProp103PermittedAutoFactors)
                            (proposalRatingFactors p)
                 in case bad of
                        [] -> Nothing
                        xs ->
                            Just
                                ( Violation
                                    "ca/prop_103"
                                    ("Prop 103: rating factors not in approved auto set: " <> show xs)
                                )

caMinAutoLiability :: Rule Proposal
caMinAutoLiability =
    forJurisdiction "CA" $
        forProductLine Auto $
            Rule "ca/min_auto_liability" $ \p ->
                if proposalCoverage p < 15000
                    then
                        Just
                            ( Violation
                                "ca/min_auto_liability"
                                "California auto liability minimum is 15,000"
                            )
                    else Nothing

california :: Governance Proposal
california =
    addRule caProp103Rule $
        addRule caMinAutoLiability mempty

-- ----------------------------------------------------------------
-- New York
-- ----------------------------------------------------------------

nyMinAutoLiability :: Rule Proposal
nyMinAutoLiability =
    forJurisdiction "NY" $
        forProductLine Auto $
            Rule "ny/min_auto_liability" $ \p ->
                if proposalCoverage p < 25000
                    then
                        Just
                            ( Violation
                                "ny/min_auto_liability"
                                "New York auto liability minimum is 25,000"
                            )
                    else Nothing

newYork :: Governance Proposal
newYork = addRule nyMinAutoLiability mempty
