"""Difficulty variants: easy, medium, hard."""

from __future__ import annotations

from target_api.contract import Contract
from target_api.variants.easy import CONTRACT as EASY
from target_api.variants.hard import CONTRACT as HARD
from target_api.variants.medium import CONTRACT as MEDIUM

VARIANTS: dict[str, Contract] = {"easy": EASY, "medium": MEDIUM, "hard": HARD}
