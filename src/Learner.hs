{-# LANGUAGE ExistentialQuantification #-}

-- | A 'Learner' from @a@ to @b@, after Fong–Spivak–Tuyéras
-- ("Backprop as Functor") and Cruttwell–Gavranović–Ghani–Wilson–Zanasi
-- ("Categorical Foundations of Gradient-Based Learning"), is a quadruple of
--
--   * a state space @s@,
--   * an implementation     @s -> a -> b@,
--   * an update             @s -> a -> b -> s@,
--   * a request             @s -> a -> b -> a@.
--
-- The state @s@ is existentially hidden: two learners with different
-- internal representations are interchangeable at the @a -> b@ interface.
--
-- 'Learner' values form a symmetric monoidal category with 'identity',
-- sequential composition ('compose' / '>>>') and parallel product
-- ('parallel'). The request map is what makes sequential composition
-- well-defined: the downstream learner tells the upstream learner what
-- target to train against.
module Learner
  ( Learner (..)
  , identity
  , compose
  , (>>>)
  , parallel
  , runLearner
  , step
  ) where

-- | A learner with hidden state. Field order: @initial@, @implement@,
-- @update@, @request@.
data Learner a b = forall s.
    Learner
      s                      -- initial state
      (s -> a -> b)          -- implement
      (s -> a -> b -> s)     -- update
      (s -> a -> b -> a)     -- request

-- | The identity learner: trivial state, passes inputs through.
identity :: Learner a a
identity = Learner () (\_ a -> a) (\_ _ _ -> ()) (\_ _ b -> b)

-- | Sequential composition. @compose g f@ runs @f@ then @g@; the
-- composite carries both states as a pair.
compose :: Learner b c -> Learner a b -> Learner a c
compose (Learner s0 i2 u2 r2) (Learner t0 i1 u1 r1) =
    Learner
      (t0, s0)
      (\(t, s) a -> i2 s (i1 t a))
      ( \(t, s) a c ->
          let b  = i1 t a
              t' = u1 t a (r2 s b c)
              s' = u2 s b c
           in (t', s')
      )
      ( \(t, s) a c ->
          let b = i1 t a
           in r1 t a (r2 s b c)
      )

-- | Categorical pipe: @f >>> g = compose g f@.
infixr 1 >>>
(>>>) :: Learner a b -> Learner b c -> Learner a c
f >>> g = compose g f

-- | Parallel (monoidal) product.
parallel :: Learner a b -> Learner c d -> Learner (a, c) (b, d)
parallel (Learner s0 i u r) (Learner t0 i' u' r') =
    Learner
      (s0, t0)
      (\(s, t) (a, c) -> (i s a, i' t c))
      (\(s, t) (a, c) (b, d) -> (u s a b, u' t c d))
      (\(s, t) (a, c) (b, d) -> (r s a b, r' t c d))

-- | Run a learner on an input, returning the current prediction.
runLearner :: Learner a b -> a -> b
runLearner (Learner s i _ _) a = i s a

-- | One training step against an observed target.
step :: Learner a b -> a -> b -> Learner a b
step (Learner s i u r) a b = Learner (u s a b) i u r
