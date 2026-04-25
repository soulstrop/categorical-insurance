-- | Shared types for the insurance examples.
--
-- 'Proposal' is the candidate object that flows out of a learner
-- pipeline and into governance. Carving it out into its own module
-- breaks the import cycle between rule bundles
-- ('Examples.Regulation', 'Examples.Guardrails') and the demo entry
-- point ('Examples.Insurance').
module Examples.Proposal
    ( Proposal (..)
    , ProductLine (..)
    ) where

data ProductLine = Auto | Health | Life | PropertyCasualty
    deriving (Show, Eq)

data Proposal = Proposal
    { proposalPremium :: !Double
    , proposalCoverage :: !Double
    , proposalExpectedClaim :: !Double
    , proposalJurisdiction :: !String
    , proposalProductLine :: !ProductLine
    , proposalRatingFactors :: ![String]
    , proposalConsent :: !Bool
    , proposalPriorPremium :: !(Maybe Double)
    , proposalExplainabilityScore :: !Double
    , proposalCession :: !Double
    }
    deriving (Show)
