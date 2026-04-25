{-# LANGUAGE DeriveFunctor #-}

-- | A small comonad of governance.
--
-- 'Governed' is the @Env@ comonad parameterised by a 'Governance' value
-- describing the rules a candidate proposal of type @p@ must satisfy.
-- 'Governance' is itself a 'Monoid', so governance objects compose: two
-- regulators' constraints are joined by '<>'.
--
-- The intended invariant — enforced by "Contract".'Contract.validate' —
-- is that a 'Contract.Contract' value can only be constructed by passing
-- a proposal through the surrounding governance.
module Governance
  ( -- * Comonad
    Comonad (..)
    -- * The Env comonad of governance
  , Governed (..)
    -- * Governance objects
  , Governance (..)
  , Rule (..)
  , Violation (..)
    -- * Construction
  , withGovernance
  , addRule
  ) where

-- | Minimal 'Comonad' class, kept self-contained so the categorical
-- structure of this project is visible without a dependency on
-- @comonad@. Swap to @Control.Comonad@ later if useful.
class (Functor w) => Comonad w where
    extract :: w a -> a
    duplicate :: w a -> w (w a)
    duplicate = extend id
    extend :: (w a -> b) -> w a -> w b
    extend f = fmap f . duplicate
    {-# MINIMAL extract, (duplicate | extend) #-}

-- | The Env comonad: a value of type @a@ paired with a governance
-- environment for proposals of type @p@.
data Governed p a = Governed
    { governance :: Governance p
    , underlying :: a
    }
    deriving (Functor)

instance Comonad (Governed p) where
    extract = underlying
    duplicate (Governed g a) = Governed g (Governed g a)

-- | A composable governance object: a list of rules and a bag of tags.
-- Composition by '<>' concatenates both — i.e. constraints are conjoined.
data Governance p = Governance
    { governanceRules :: [Rule p]
    , governanceTags :: [(String, String)]
    }

instance Semigroup (Governance p) where
    Governance r1 t1 <> Governance r2 t2 = Governance (r1 <> r2) (t1 <> t2)

instance Monoid (Governance p) where
    mempty = Governance [] []

-- | A governance rule for proposals of type @p@. Returns 'Nothing' on
-- success and a 'Violation' on failure.
data Rule p = Rule
    { ruleName :: String
    , rulePredicate :: p -> Maybe Violation
    }

-- | A violation report.
data Violation = Violation
    { violationRule :: String
    , violationDetail :: String
    }
    deriving (Show, Eq)

-- | Lift a value into a governance context.
withGovernance :: Governance p -> a -> Governed p a
withGovernance = Governed

-- | Extend governance by appending a single rule.
addRule :: Rule p -> Governance p -> Governance p
addRule r g = g {governanceRules = governanceRules g <> [r]}
