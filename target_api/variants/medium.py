"""The `medium` variant: the easy rules plus four more, with terse errors.

Terse responses carry an error code but no field names, so the agent learns
that something was rejected without being told which parameter caused it.
"""

from __future__ import annotations

from target_api.contract import Contract, PriorClass, Rule, RuleKind, Verbosity
from target_api.variants.easy import RULES as EASY_RULES

CONV = PriorClass.CONVENTIONAL
CP = PriorClass.COUNTER_PRIOR

PHONE_PATTERN = r"\+?\d{7,15}"

EXTRA_RULES: tuple[Rule, ...] = (
    Rule(
        id="products.sort.enum",
        endpoint="GET /products",
        kind=RuleKind.ENUM,
        prior_class=CONV,
        description="sort must be one of price_asc, price_desc, newest",
        param="sort",
        values=("price_asc", "price_desc", "newest"),
        status=400,
    ),
    Rule(
        id="orders.currency.enum",
        endpoint="POST /orders",
        kind=RuleKind.ENUM,
        prior_class=CP,  # XTS is a real ISO test code but nobody guesses it
        description="currency must be one of USD, EUR, GBP, XTS",
        param="currency",
        values=("USD", "EUR", "GBP", "XTS"),
        status=400,
    ),
    Rule(
        id="orders.phone.format",
        endpoint="POST /orders",
        kind=RuleKind.FORMAT,
        prior_class=CONV,
        description="phone must be 7 to 15 digits, optionally leading +",
        param="phone",
        pattern=PHONE_PATTERN,
        example="+15550001111",
        status=400,
    ),
    Rule(
        id="orders.held_requires_reason",
        endpoint="POST /orders",
        kind=RuleKind.CONDITIONAL_REQUIRED,
        prior_class=CP,  # nothing in the name suggests held orders need a reason
        description="if status is held, reason becomes required",
        if_param="status",
        if_value="held",
        then_param="reason",
        status=422,
    ),
)

RULES: tuple[Rule, ...] = EASY_RULES + EXTRA_RULES

CONTRACT = Contract(
    name="medium",
    verbosity=Verbosity.TERSE,
    rules=RULES,
    endpoints=("GET /products", "POST /orders", "GET /orders/{id}"),
)
