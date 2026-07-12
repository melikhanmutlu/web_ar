"""Prepaid AI overage credits (1 credit = 1 AI generation).

Credits are consumed only after a user's monthly plan quota is exhausted
(see app.py::_consume_ai_allowance). This module is the single, payment-
provider-agnostic seam for changing a user's balance: an admin uses it today
(admin.py::adjust_credits), and a future payment webhook (iyzico / PayTR /
Paddle / etc.) will call grant_ai_credits() on a successful purchase without
touching any generation or quota logic.

CREDIT_PACKS is display/catalog config for the packs shown on /pricing; no
checkout is wired yet.
"""

# name -> {credits, price} (price is display-only, monthly currency-agnostic
# figure). Pack economics target ~2-2.3x the Meshy cost per generation.
CREDIT_PACKS = {
    "small": {"credits": 10, "price": 9},
    "medium": {"credits": 50, "price": 39},
    "large": {"credits": 200, "price": 139},
}


def grant_ai_credits(user, amount):
    """Add `amount` credits to a user's balance (a negative amount deducts).
    The balance never goes below zero. Mutates the user in the current session
    and returns the new balance; the caller owns the commit.
    """
    new_balance = max(0, (user.ai_credit_balance or 0) + amount)
    user.ai_credit_balance = new_balance
    return new_balance
