{-# LANGUAGE DeriveFunctor #-}

-- | Decision systems parameterised by a monoid.
--
-- This module implements the generalisation described in @math.tex@,
-- §VI (\"Decision Systems Parameterised by a Monoid\"). A
-- 'Governance.Rule' valued in @Maybe Violation@ is a special case of a
-- 'Decision' valued in any monoid @m@; the existing
-- @M = [Violation]@ governance development is recovered by choosing
-- @m = [Violation]@ with the empty-list admission predicate.
--
-- The module exposes:
--
--   * 'Decision' and 'DecisionSystem' (mirroring math.tex Defs 12, 13)
--   * 'aggregate' — the @\<D\>@ operator
--   * 'GovernedDS' — the Env comonad on decision systems
--   * 'GenContract' — abstract type with private constructor
--   * 'validateDS' — generalised validation, parameterised by @adm@
--
-- Together these instantiate the Generalised Static Admissibility
-- theorem (math.tex Theorem 14): every 'GenContract' value witnesses a
-- decision system and proposal whose aggregate satisfies @adm@.
module DecisionSystem
    ( -- * Decisions and decision systems
      Decision
    , DecisionSystem
    , aggregate

      -- * The Env comonad on decision systems
    , GovernedDS (..)
    , withDecisions

      -- * Generalised abstract contract
    , GenContract
    , contractValue

      -- * Generalised validation
    , validateDS
    ) where

-- | A 'Decision' valued in monoid @m@: given a proposal @p@, produce a
-- summary value in @m@. (math.tex Def. 12.)
type Decision m p = p -> m

-- | A 'DecisionSystem' valued in @m@: a list of 'Decision's. (math.tex
-- Def. 13.) The carrier type @[Decision m p]@ is itself a free monoid
-- under list concatenation.
type DecisionSystem m p = [Decision m p]

-- | The aggregate of a decision system on a single proposal: fold each
-- decision's contribution under @m@'s monoidal operation.
aggregate :: (Monoid m) => DecisionSystem m p -> p -> m
aggregate ds p = foldMap ($ p) ds

-- | The Env comonad over a 'DecisionSystem': a focused value @a@
-- alongside the decision-system context @[Decision m p]@.
data GovernedDS m p a = GovernedDS
    { dsEnvironment :: DecisionSystem m p
    , dsUnderlying :: a
    }
    deriving (Functor)

-- | Lift a value into a decision-system context.
withDecisions :: DecisionSystem m p -> a -> GovernedDS m p a
withDecisions = GovernedDS

-- | Generalised abstract contract: parameterised by the monoid @m@ and
-- the proposal type @p@. Constructor not exported — values can only be
-- obtained via 'validateDS', which factors through the surrounding
-- decision system. (math.tex Def. 15.)
newtype GenContract m p = GenContract p

-- | Read-only access to the underlying proposal of a contract.
contractValue :: GenContract m p -> p
contractValue (GenContract p) = p

-- | Generalised validation. Aggregates the decision system on the
-- focal proposal; returns the constructed contract if @adm@ holds on
-- the aggregate, otherwise the aggregate itself in the left summand.
-- (math.tex Def. 15; Theorem 14 follows by the same argument as the
-- specialised static-governance theorem.)
validateDS ::
    (Monoid m) =>
    (m -> Bool) ->
    GovernedDS m p p ->
    Either m (GenContract m p)
validateDS adm (GovernedDS ds p) =
    let m = aggregate ds p
     in if adm m then Right (GenContract p) else Left m
