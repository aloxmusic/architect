"""Keep nonblank text semantics under search and full-match connector engines."""

import re
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from architect_ai.domain.values import Text
from architect_ai.mcp.server import connector_schema


@pytest.mark.parametrize(
    "value", ["Living Room", "oak", "İstek", "a", "  a  ", "\na\n", "", " ", "\t\n"]
)
def test_nonblank_schema_matches_domain_and_fullmatch(value: str) -> None:
    original = TypeAdapter(Text).json_schema()
    schema = connector_schema(original)
    assert original["pattern"] == r"\S"
    try:
        TypeAdapter(Text).validate_python(value)
    except ValidationError:
        valid = False
    else:
        valid = True
    assert bool(re.search(schema["pattern"], value)) == valid
    assert bool(re.fullmatch(schema["pattern"], value)) == valid


def test_conversion_is_recursive_and_leaves_other_constraints_unchanged() -> None:
    schema: dict[str, Any] = {
        "$defs": {"Text": {"pattern": r"\S", "minLength": 1}},
        "anyOf": [{"pattern": "x"}],
    }
    converted = connector_schema(schema)
    assert converted["$defs"]["Text"]["pattern"] != r"\S"
    assert converted["$defs"]["Text"]["minLength"] == 1
    assert converted["anyOf"] == schema["anyOf"]
    assert schema["$defs"]["Text"]["pattern"] == r"\S"
