"""Scoring correctness. If this is wrong, every number in the write-up is wrong.

Three families of case matter: paraphrases of the same rule must match, subtly
wrong rules must not, and invented rules must cost precision.
"""

from __future__ import annotations

from typing import Any

from probe.eval.scoring import normalize, score, score_by_subset

QUANTITY_RANGE: dict[str, Any] = {
    "id": "orders.quantity.range",
    "endpoint": "POST /orders",
    "kind": "range",
    "param": "quantity",
    "lo": 1,
    "hi": 40,
    "status": 422,
    "prior_class": "counter_prior",
}

STATUS_ENUM: dict[str, Any] = {
    "id": "orders.status.enum",
    "endpoint": "POST /orders",
    "kind": "enum",
    "param": "status",
    "values": ["pending", "shipped", "cancelled", "held"],
    "status": 400,
    "prior_class": "counter_prior",
}

EMAIL_FORMAT: dict[str, Any] = {
    "id": "orders.email.format",
    "endpoint": "POST /orders",
    "kind": "format",
    "param": "email",
    "pattern": r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}",
    "status": 400,
    "prior_class": "conventional",
}

CUSTOMER_REQUIRED: dict[str, Any] = {
    "id": "orders.customer_id.required",
    "endpoint": "POST /orders",
    "kind": "required",
    "param": "customer_id",
    "status": 422,
    "prior_class": "conventional",
}

TRUTH = [QUANTITY_RANGE, STATUS_ENUM, EMAIL_FORMAT, CUSTOMER_REQUIRED]


# --- paraphrases must match -------------------------------------------------


def test_identical_rule_matches() -> None:
    assert score([QUANTITY_RANGE], [QUANTITY_RANGE]).recall == 1.0


def test_range_written_with_min_max_matches_lo_hi() -> None:
    paraphrase = {
        "endpoint": "POST /orders",
        "kind": "range",
        "param": "quantity",
        "min": 1,
        "max": 40,
    }
    assert score([paraphrase], [QUANTITY_RANGE]).recall == 1.0


def test_exclusive_bounds_match_equivalent_inclusive_bounds() -> None:
    # 0 < quantity < 41 is the same rule as 1 <= quantity <= 40.
    paraphrase = {
        "endpoint": "POST /orders",
        "kind": "bounds",
        "param": "quantity",
        "gt": 0,
        "lt": 41,
    }
    assert score([paraphrase], [QUANTITY_RANGE]).recall == 1.0


def test_enum_order_and_kind_alias_do_not_matter() -> None:
    paraphrase = {
        "endpoint": "post /orders",
        "kind": "one_of",
        "field": "status",
        "allowed_values": ["held", "cancelled", "pending", "shipped"],
    }
    assert score([paraphrase], [STATUS_ENUM]).recall == 1.0


def test_differently_written_email_regex_matches() -> None:
    paraphrase = {
        "endpoint": "POST /orders",
        "kind": "regex",
        "param": "email",
        "pattern": r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}",
    }
    assert score([paraphrase], [EMAIL_FORMAT]).recall == 1.0


def test_type_alias_matches() -> None:
    truth = {
        "id": "orders.quantity.type",
        "endpoint": "POST /orders",
        "kind": "type",
        "param": "quantity",
        "type_name": "int",
    }
    paraphrase = {
        "endpoint": "POST /orders",
        "kind": "type_constraint",
        "param": "quantity",
        "type": "integer",
    }
    assert score([paraphrase], [truth]).recall == 1.0


def test_mutual_exclusion_is_unordered() -> None:
    truth = {
        "id": "orders.sku_xor_product_id",
        "endpoint": "POST /orders",
        "kind": "mutual_exclusion",
        "param_a": "sku",
        "param_b": "product_id",
    }
    paraphrase = {
        "endpoint": "POST /orders",
        "kind": "mutually_exclusive",
        "param_a": "product_id",
        "param_b": "sku",
    }
    assert score([paraphrase], [truth]).recall == 1.0


# --- subtly wrong rules must NOT match --------------------------------------


def test_off_by_one_upper_bound_does_not_match() -> None:
    off_by_one = {**QUANTITY_RANGE, "hi": 41}
    result = score([off_by_one], [QUANTITY_RANGE])
    assert result.recall == 0.0
    assert result.false_positives == 1


def test_off_by_one_lower_bound_does_not_match() -> None:
    off_by_one = {**QUANTITY_RANGE, "lo": 0}
    assert score([off_by_one], [QUANTITY_RANGE]).recall == 0.0


def test_enum_missing_a_member_does_not_match() -> None:
    # The memorised triple without the unguessable fourth member.
    conventional_guess = {**STATUS_ENUM, "values": ["pending", "shipped", "cancelled"]}
    assert score([conventional_guess], [STATUS_ENUM]).recall == 0.0


def test_enum_with_an_extra_member_does_not_match() -> None:
    too_broad = {**STATUS_ENUM, "values": [*STATUS_ENUM["values"], "refunded"]}
    assert score([too_broad], [STATUS_ENUM]).recall == 0.0


def test_wrong_format_does_not_match() -> None:
    wrong = {
        "endpoint": "POST /orders",
        "kind": "format",
        "param": "email",
        "pattern": r"CUS-\d{6}",
    }
    assert score([wrong], [EMAIL_FORMAT]).recall == 0.0


def test_right_rule_on_the_wrong_parameter_does_not_match() -> None:
    wrong_param = {**QUANTITY_RANGE, "param": "limit"}
    assert score([wrong_param], [QUANTITY_RANGE]).recall == 0.0


def test_right_rule_on_the_wrong_endpoint_does_not_match() -> None:
    wrong_endpoint = {**QUANTITY_RANGE, "endpoint": "GET /products"}
    assert score([wrong_endpoint], [QUANTITY_RANGE]).recall == 0.0


def test_cap_off_by_one_does_not_match() -> None:
    truth = {
        "id": "products.limit.cap",
        "endpoint": "GET /products",
        "kind": "pagination_cap",
        "param": "limit",
        "cap": 37,
    }
    conventional_guess = {**truth, "cap": 50}
    assert score([conventional_guess], [truth]).recall == 0.0


def test_default_off_by_one_does_not_match() -> None:
    truth = {
        "id": "products.page.optional",
        "endpoint": "GET /products",
        "kind": "optional",
        "param": "page",
        "default": 0,
    }
    conventional_guess = {**truth, "default": 1}
    assert score([conventional_guess], [truth]).recall == 0.0


# --- hallucinations must cost precision -------------------------------------


def test_invented_rule_lowers_precision() -> None:
    invented = {
        "endpoint": "POST /orders",
        "kind": "required",
        "param": "shipping_address",
    }
    result = score([CUSTOMER_REQUIRED, invented], [CUSTOMER_REQUIRED])
    assert result.recall == 1.0
    assert result.precision == 0.5
    assert result.false_positives == 1
    assert "required:shipping_address" in result.hallucinated


def test_claiming_everything_is_punished_by_precision() -> None:
    noise = [
        {"endpoint": "POST /orders", "kind": "required", "param": f"junk_{i}"}
        for i in range(16)
    ]
    result = score([*TRUTH, *noise], TRUTH)
    assert result.recall == 1.0
    assert result.precision == 0.2
    assert round(result.f1, 4) == 0.3333


def test_duplicate_claims_do_not_inflate_the_score() -> None:
    result = score([QUANTITY_RANGE, dict(QUANTITY_RANGE)], [QUANTITY_RANGE])
    assert result.true_positives == 1
    assert result.precision == 1.0


def test_missing_rules_lower_recall() -> None:
    result = score([CUSTOMER_REQUIRED], TRUTH)
    assert result.recall == 0.25
    assert result.precision == 1.0
    assert set(result.missed_rule_ids) == {
        "orders.quantity.range",
        "orders.status.enum",
        "orders.email.format",
    }


def test_empty_report_scores_zero_not_an_error() -> None:
    result = score([], TRUTH)
    assert (result.precision, result.recall, result.f1) == (0.0, 0.0, 0.0)


def test_unintelligible_rules_are_dropped_not_crashed_on() -> None:
    assert normalize({"kind": "nonsense", "param": "x"}) is None
    assert normalize({"kind": "range", "param": "quantity"}) is None
    result = score([{"kind": "gibberish"}, CUSTOMER_REQUIRED], [CUSTOMER_REQUIRED])
    assert result.recall == 1.0


# --- error semantics are scored separately from rule identity ---------------


def test_wrong_status_still_matches_but_lowers_error_semantics_accuracy() -> None:
    # A range violation returning the conventional 400 rather than this API's 422.
    wrong_status = {**QUANTITY_RANGE, "status": 400}
    result = score([wrong_status], [QUANTITY_RANGE])
    assert result.recall == 1.0, "the constraint itself was recovered"
    assert result.error_semantics_accuracy == 0.0


def test_right_status_scores_full_error_semantics_accuracy() -> None:
    assert score([QUANTITY_RANGE], [QUANTITY_RANGE]).error_semantics_accuracy == 1.0


# --- subset reporting -------------------------------------------------------


def test_subsets_are_reported_separately() -> None:
    # An agent that recalls conventions but recovers nothing unguessable.
    report = [CUSTOMER_REQUIRED, EMAIL_FORMAT]
    result = score_by_subset(report, TRUTH)

    assert result["conventional"]["recall"] == 1.0
    assert result["counter_prior"]["recall"] == 0.0
    assert result["all"]["recall"] == 0.5


def test_unachievable_rules_are_excluded_from_scoring() -> None:
    achievable = {"orders.customer_id.required", "orders.email.format"}
    result = score_by_subset([CUSTOMER_REQUIRED, EMAIL_FORMAT], TRUTH, achievable=achievable)
    assert result["all"]["recall"] == 1.0
