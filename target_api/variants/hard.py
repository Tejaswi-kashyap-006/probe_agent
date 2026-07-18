"""The `hard` variant: the medium rules plus five more, with bare errors.

A bare response is a status code and nothing else — no error code, no field
names. The status still distinguishes 400 from 422 from 409, so an isolating
probe can still attribute a failure; what disappears is any hint about which
parameter was at fault in a request that varies more than one thing at once.
"""

from __future__ import annotations

from target_api.contract import Contract, PriorClass, Rule, RuleKind, Verbosity
from target_api.variants.medium import RULES as MEDIUM_RULES

CONV = PriorClass.CONVENTIONAL
CP = PriorClass.COUNTER_PRIOR

WAREHOUSE_PATTERN = r"WH-[A-Z]{2}\d{2}"

EXTRA_RULES: tuple[Rule, ...] = (
    Rule(
        id="products.page_xor_offset",
        endpoint="GET /products",
        kind=RuleKind.MUTUAL_EXCLUSION,
        prior_class=CP,  # most APIs accept either, or silently prefer one
        description="page and offset cannot both be sent; sending both returns 409",
        param_a="page",
        param_b="offset",
        status=409,
    ),
    Rule(
        id="orders.channel.enum",
        endpoint="POST /orders",
        kind=RuleKind.ENUM,
        prior_class=CONV,
        description="channel must be one of web, mobile, pos",
        param="channel",
        values=("web", "mobile", "pos"),
        status=400,
    ),
    Rule(
        id="orders.warehouse_id.format",
        endpoint="POST /orders",
        kind=RuleKind.FORMAT,
        prior_class=CP,  # arbitrary house format
        description="warehouse_id must match WH-XX## (two letters, two digits)",
        param="warehouse_id",
        pattern=WAREHOUSE_PATTERN,
        example="WH-AB12",
        status=400,
    ),
    Rule(
        id="orders.gift.type",
        endpoint="POST /orders",
        kind=RuleKind.TYPE,
        prior_class=CONV,
        description="gift must be a boolean",
        param="gift",
        type_name="bool",
        status=400,
    ),
    Rule(
        id="orders.gift_requires_recipient_email",
        endpoint="POST /orders",
        kind=RuleKind.CONDITIONAL_REQUIRED,
        prior_class=CONV,
        description="if gift is true, recipient_email becomes required",
        if_param="gift",
        if_value=True,
        then_param="recipient_email",
        status=422,
    ),
)

RULES: tuple[Rule, ...] = MEDIUM_RULES + EXTRA_RULES

CONTRACT = Contract(
    name="hard",
    verbosity=Verbosity.BARE,
    rules=RULES,
    endpoints=("GET /products", "POST /orders", "GET /orders/{id}"),
)
