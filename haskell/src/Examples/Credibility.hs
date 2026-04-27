-- | A Bayesian credibility model as a 'Learner'.
--
-- We use the Normal–Normal conjugate model: claim severity is assumed
-- @Normal(θ, σ²)@ for some unknown individual mean @θ@ with prior
-- @θ ~ Normal(μ₀, 1/κ₀)@. After each observation the posterior on @θ@
-- remains Normal with precision-weighted mean updates.
--
-- The classical Bühlmann credibility factor
--
-- > Z = n / (n + σ²/τ₀²)
--
-- falls out of the recursion: after @n@ observations the posterior
-- mean equals @Z * sample_mean + (1 - Z) * μ₀@.
module Examples.Credibility
    ( CredState (..)
    , credibilityLearner
    ) where

import Learner

data CredState = CredState
    { credMean :: !Double
    , credPrecision :: !Double
    }
    deriving (Show)

credibilityLearner ::
    -- | prior mean μ₀
    Double ->
    -- | prior precision on the mean κ₀ = 1/τ₀²
    Double ->
    -- | observation noise variance σ²
    Double ->
    Learner () Double
credibilityLearner mu0 kappa0 sigma2 =
    Learner
        (CredState mu0 kappa0)
        (\s () -> credMean s)
        ( \(CredState mu kappa) () x ->
            let pObs = 1 / sigma2
                kappa' = kappa + pObs
                mu' = (kappa * mu + pObs * x) / kappa'
             in CredState mu' kappa'
        )
        (\_ () _ -> ())
