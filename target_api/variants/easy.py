"""The `easy` variant: full rule set, verbose errors.

Roughly half the rules are tagged COUNTER_PRIOR — chosen to defeat an LLM's
memorised API conventions, so that recovering the contract can be told apart
from recalling how store APIs usually work. Each counter-prior rule notes the
conventional value it displaces.
"""

from __future__ import annotations

from target_api.contract import Contract, PriorClass, Rule, RuleKind, Verbosity

CONV = PriorClass.CONVENTIONAL
CP = PriorClass.COUNTER_PRIOR

EMAIL_PATTERN = r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}"
CUSTOMER_ID_PATTERN = r"CUS-\d{6}"

RULES: tuple[Rule, ...] = (
    # ---- GET /products -------------------------------------------------
    Rule(
        id="products.page.optional",
        endpoint="GET /products",
        kind=RuleKind.OPTIONAL,
        prior_class=CP,  # conventional APIs are 1-indexed; this one is 0-indexed
        description="page is optional and defaults to 0 (pages are 0-indexed)",
        param="page",
        default=0,
    ),
    Rule(
        id="products.page.type",
        endpoint="GET /products",
        kind=RuleKind.TYPE,
        prior_class=CONV,
        description="page must be an integer",
        param="page",
        type_name="int",
        status=400,
    ),
    Rule(
        id="products.limit.optional",
        endpoint="GET /products",
        kind=RuleKind.OPTIONAL,
        prior_class=CONV,
        description="limit is optional and defaults to 20",
        param="limit",
        default=20,
    ),
    Rule(
        id="products.limit.type",
        endpoint="GET /products",
        kind=RuleKind.TYPE,
        prior_class=CONV,
        description="limit must be an integer",
        param="limit",
        type_name="int",
        status=400,
    ),
    Rule(
        id="products.limit.cap",
        endpoint="GET /products",
        kind=RuleKind.PAGINATION_CAP,
        prior_class=CP,  # conventional caps are round: 50 or 100. This one is 37.
        description="limit is silently capped at 37; larger values return 37 items",
        param="limit",
        cap=37,
    ),
    Rule(
        id="products.category.enum",
        endpoint="GET /products",
        kind=RuleKind.ENUM,
        prior_class=CP,  # 'sundries' is not a category an LLM would guess
        description="category must be one of electronics, books, garden, sundries",
        param="category",
        values=("electronics", "books", "garden", "sundries"),
        status=400,
    ),
    # ---- POST /orders --------------------------------------------------
    Rule(
        id="orders.customer_id.required",
        endpoint="POST /orders",
        kind=RuleKind.REQUIRED,
        prior_class=CONV,
        description="customer_id is required",
        param="customer_id",
        status=422,
    ),
    Rule(
        id="orders.customer_id.format",
        endpoint="POST /orders",
        kind=RuleKind.FORMAT,
        prior_class=CP,  # arbitrary house format, unguessable from the name
        description="customer_id must match CUS-###### (six digits)",
        param="customer_id",
        pattern=CUSTOMER_ID_PATTERN,
        example="CUS-000123",
        status=400,
    ),
    Rule(
        id="orders.quantity.required",
        endpoint="POST /orders",
        kind=RuleKind.REQUIRED,
        prior_class=CONV,
        description="quantity is required",
        param="quantity",
        status=422,
    ),
    Rule(
        id="orders.quantity.type",
        endpoint="POST /orders",
        kind=RuleKind.TYPE,
        prior_class=CONV,
        description="quantity must be an integer",
        param="quantity",
        type_name="int",
        status=400,
    ),
    Rule(
        id="orders.quantity.range",
        endpoint="POST /orders",
        kind=RuleKind.RANGE,
        prior_class=CP,  # conventional would be 1..99 and a 400, not 1..40 and a 422
        description="quantity must satisfy 1 <= quantity <= 40; violations return 422",
        param="quantity",
        lo=1,
        hi=40,
        status=422,
    ),
    Rule(
        id="orders.status.enum",
        endpoint="POST /orders",
        kind=RuleKind.ENUM,
        prior_class=CP,  # the extra 'held' member breaks the memorised triple
        description="status must be one of pending, shipped, cancelled, held",
        param="status",
        values=("pending", "shipped", "cancelled", "held"),
        status=400,
    ),
    Rule(
        id="orders.email.format",
        endpoint="POST /orders",
        kind=RuleKind.FORMAT,
        prior_class=CONV,
        description="email must look like an email address",
        param="email",
        pattern=EMAIL_PATTERN,
        example="a@b.com",
        status=400,
    ),
    Rule(
        id="orders.expedited.type",
        endpoint="POST /orders",
        kind=RuleKind.TYPE,
        prior_class=CONV,
        description="expedited must be a boolean",
        param="expedited",
        type_name="bool",
        status=400,
    ),
    Rule(
        id="orders.expedited.requires_phone",
        endpoint="POST /orders",
        kind=RuleKind.CONDITIONAL_REQUIRED,
        prior_class=CONV,
        description="if expedited is true, phone becomes required",
        if_param="expedited",
        if_value=True,
        then_param="phone",
        status=422,
    ),
    Rule(
        id="orders.sku_xor_product_id",
        endpoint="POST /orders",
        kind=RuleKind.MUTUAL_EXCLUSION,
        prior_class=CP,  # conventional would be 400; this API returns 409
        description="sku and product_id cannot both be sent; sending both returns 409",
        param_a="sku",
        param_b="product_id",
        status=409,
    ),
    # ---- GET /orders/{id} ----------------------------------------------
    Rule(
        id="orders.lookup.not_found",
        endpoint="GET /orders/{id}",
        kind=RuleKind.RESOURCE_LOOKUP,
        prior_class=CONV,
        description="an unknown order id returns 404",
        param="id",
        status=404,
    ),
)

CONTRACT = Contract(
    name="easy",
    verbosity=Verbosity.VERBOSE,
    rules=RULES,
    endpoints=("GET /products", "POST /orders", "GET /orders/{id}"),
)
