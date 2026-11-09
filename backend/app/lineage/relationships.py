"""Directed lineage relationship types and their source-to-target meanings."""

from enum import StrEnum


class RelationshipType(StrEnum):
    CREATED_FROM = "CREATED_FROM"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    CAPTURED_AS = "CAPTURED_AS"
    NOTIFIED_BY = "NOTIFIED_BY"
    UPDATED_BY = "UPDATED_BY"
    FULFILLED_BY = "FULFILLED_BY"
    SHIPPED_AS = "SHIPPED_AS"
    REFUNDED_BY = "REFUNDED_BY"
    RECORDED_IN = "RECORDED_IN"


# Edges follow these literal directions:
# PayPal order -> merchant order: CREATED_FROM
# Merchant order -> PayPal order/capture: ASSOCIATED_WITH
# PayPal order -> capture: CAPTURED_AS
# Resource -> webhook event: NOTIFIED_BY
# Business record -> webhook event: UPDATED_BY
# Merchant order -> fulfillment record: FULFILLED_BY
# Fulfillment record -> shipping record: SHIPPED_AS
# Order/capture -> refund record: REFUNDED_BY
# Order/capture -> accounting entry: RECORDED_IN
RELATIONSHIPS = tuple(relationship.value for relationship in RelationshipType)
