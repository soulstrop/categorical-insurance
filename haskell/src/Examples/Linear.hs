-- | Linear regression by online gradient descent, as a 'Learner'.
--
-- State is the weight vector @w@. On input @x@ the prediction is
-- @ŷ = w · x@; on update with target @y@ we step
-- @w' = w - η (ŷ - y) x@ (squared-loss gradient).
--
-- The 'Learner.request' map propagates the *gradient with respect to
-- input* — @∂L/∂x = (ŷ - y) w@ — though in practice this is only used
-- when this learner sits downstream of another in a 'Learner.compose'.
module Examples.Linear
    ( linearLearner
    ) where

import Learner

linearLearner ::
    -- | learning rate η
    Double ->
    -- | initial weights w₀
    [Double] ->
    Learner [Double] Double
linearLearner eta w0 =
    Learner
        w0
        (\ws xs -> dot ws xs)
        ( \ws xs y ->
            let yhat = dot ws xs
                err = yhat - y
             in zipWith (\w x -> w - eta * err * x) ws xs
        )
        ( \ws xs y ->
            let yhat = dot ws xs
                err = yhat - y
             in zipWith (\x w -> x - eta * err * w) xs ws
        )

dot :: [Double] -> [Double] -> Double
dot xs ys = sum (zipWith (*) xs ys)
