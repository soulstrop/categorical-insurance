"""Phase 0 Insurance Demo.

This module provides a runnable example of layered governance and a
Bühlmann credibility learner, mirroring the Haskell demo.
"""

from catins.decision import Decision
from catins.learners.credibility import BuhlmannCredibility
from catins.models import Proposal, Violation
from catins.validation import Governed, validate


class InsuranceProposal(Proposal):
    """A concrete insurance proposal for the demo."""

    holder: str
    premium_observed: float
    risk_factors: list[str]


def federal_rules() -> list[Decision[InsuranceProposal, list[Violation]]]:
    """Federal-level governance rules."""

    def no_protected_factors(p: InsuranceProposal) -> list[Violation]:
        protected = {"race", "religion", "origin"}
        found = protected.intersection(p.risk_factors)
        if found:
            return [
                Violation(
                    rule_name="federal/protected_class",
                    message=f"Prohibited factors: {list(found)}",
                    context={"found": list(found)},
                )
            ]
        return []

    return [no_protected_factors]


def state_rules() -> list[Decision[InsuranceProposal, list[Violation]]]:
    """State-level (California) governance rules."""

    def prop_103_compliance(p: InsuranceProposal) -> list[Violation]:
        # Simple example: must have premium > 0
        if p.premium_observed <= 0:
            return [
                Violation(
                    rule_name="ca/prop_103",
                    message="Premium must be positive",
                    context={"premium": p.premium_observed},
                )
            ]
        return []

    return [prop_103_compliance]


def demo() -> None:
    """Exercise a layered governance regime with a learner."""
    # Initialize a learner with some prior knowledge
    # (e.g., from a similar portfolio)
    learner = BuhlmannCredibility(mu0=1000.0, kappa0=0.1, sigma2=500.0)

    # Define a layered regime via list concatenation (the Monoid <> analog)
    regime = federal_rules() + state_rules()

    # 1. A clean proposal
    clean_p = InsuranceProposal(
        holder="Alice", premium_observed=1100.0, risk_factors=["age", "location"]
    )

    # Use learner to get a predicted premium (implement)
    predicted_premium = learner.implement(None)
    print(f"Predicted Premium for Alice: {predicted_premium}")

    # Wrap in Governed context
    governed = Governed(proposal=clean_p, decisions=regime)

    # Validate
    result = validate(governed, adm=lambda m: len(m) == 0)
    print(f"Alice Contract: {result}")

    # If Alice accepts, we would update the learner with the observed outcome
    # (Simplified: we use premium_observed as the outcome)
    learner.update(None, clean_p.premium_observed)
    print(f"Learner state after Alice: {learner.state}")

    # 2. A violating proposal
    bad_p = InsuranceProposal(holder="Bob", premium_observed=-50.0, risk_factors=["race", "age"])

    governed_bad = Governed(proposal=bad_p, decisions=regime)
    violations = validate(governed_bad, adm=lambda m: len(m) == 0)

    print(f"Bob Rejection Violations: {violations}")


if __name__ == "__main__":
    demo()
