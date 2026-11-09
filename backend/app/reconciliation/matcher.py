"""Matching logic for transaction and order alignment."""


def match_records(left: list[str], right: list[str]) -> list[tuple[str, str]]:
    return [(item, item) for item in left if item in right]
