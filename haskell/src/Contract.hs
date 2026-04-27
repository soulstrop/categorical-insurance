-- | Contracts as the audited outputs of governed learner pipelines.
--
-- The 'Contract' type is abstract: the constructor is not exported, so
-- a 'Contract' value can only be obtained via 'validate', which factors
-- through the surrounding 'Governance'. This makes the rule
--
--   /no contract may be made that violates governance/
--
-- a static guarantee — there is no other way to construct a 'Contract'.
module Contract
    ( Contract
    , contractView
    , validate
    , unsafeContract
    ) where

import Governance

-- | A validated contract over proposals of type @p@. Constructor not exported.
newtype Contract p = Contract p

-- | Read-only view of the underlying proposal.
contractView :: Contract p -> p
contractView (Contract p) = p

-- | Attempt to bind a proposal as a 'Contract' under its governance
-- environment. All rules in the surrounding 'Governance' must pass.
validate :: Governed p p -> Either [Violation] (Contract p)
validate g =
    let p = extract g
        rs = governanceRules (governance g)
        vs = [v | r <- rs, Just v <- [rulePredicate r p]]
     in if null vs then Right (Contract p) else Left vs

-- | Escape hatch for tests and one-off prototyping. Do not export from
-- production-facing modules — using this bypasses governance.
unsafeContract :: p -> Contract p
unsafeContract = Contract
