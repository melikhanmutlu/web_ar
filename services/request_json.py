"""Tolerant JSON request-body access: malformed or non-object bodies never raise."""

from flask import request


def json_dict():
    """The request's JSON body if it is a JSON object, else an empty dict.

    Invalid JSON, a missing/incorrect Content-Type, or a body that is a list,
    string, number or null all yield {} so callers can validate fields and
    answer 400 instead of crashing into a 500.
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def json_text(data, key, default=""):
    """`data[key]` as a stripped string; `default` if it is missing/empty or not a string."""
    value = data.get(key)
    if isinstance(value, str):
        return value.strip() or default
    return default
