import json
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from architect_ai.domain.adg_v1 import (
    Alignment,
    Boundary,
    Constraint,
    Distance,
    ForbiddenArea,
    Lock,
    Project,
    RequiredClearance,
    WallContact,
)
from architect_ai.domain.serialization import deserialize_project, serialize_project
from architect_ai.domain.values import Assertion, Dimensions, Source, to_millimeters

FIXTURES = Path(__file__).parent / "fixtures" / "adg"


def kitchen() -> Project:
    return deserialize_project((FIXTURES / "l_layout_kitchen.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["living_room", "l_layout_kitchen", "bedroom", "commercial_bar"])
def test_representative_roundtrip(name: str) -> None:
    project = deserialize_project((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    encoded = serialize_project(project)
    assert deserialize_project(encoded) == project
    assert serialize_project(deserialize_project(encoded)) == encoded
    assert json.loads(encoded)["walls"][0]["thickness"]["value"] == "150"
    assert project.model_copy(deep=True) == project


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "0.0000001", 0.1, True])
def test_invalid_dimensions(value: object) -> None:
    with pytest.raises(ValidationError):
        Dimensions.model_validate({"width": value, "depth": "600", "height": "900"})


def test_duplicate_ids_across_entity_types_and_project() -> None:
    project = kitchen()
    for duplicate in (project.id, project.walls[0].id):
        obj = project.furniture[0].model_copy(update={"id": duplicate})
        with pytest.raises(ValidationError, match="Duplicate IDs"):
            project.model_copy(update={"furniture": (obj,)})


@pytest.mark.parametrize(
    "field,value",
    [
        ("width", "4000"),
        ("height", "3000"),
        ("sill_height", "2800"),
        ("position", "3270"),
        ("position", "-1"),
    ],
)
def test_impossible_openings(field: str, value: str) -> None:
    data = kitchen().model_dump(mode="json")
    data["openings"][0][field]["value"] = value
    with pytest.raises(ValidationError):
        Project.model_validate(data)


def test_missing_host_wall() -> None:
    project = kitchen()
    opening = project.openings[0].model_copy(
        update={"host_wall_id": Assertion[UUID](value=uuid4(), source=Source.USER_EXPLICIT)}
    )
    with pytest.raises(ValidationError, match="missing host wall"):
        project.model_copy(update={"openings": (opening,)})


def test_overlapping_openings() -> None:
    project = kitchen()
    duplicate = project.openings[0].model_copy(update={"id": uuid4()})
    with pytest.raises(ValidationError, match="overlapping"):
        project.model_copy(update={"openings": (*project.openings, duplicate)})


def test_exact_opening_edge_and_decimal_context_independence() -> None:
    with localcontext() as ctx:
        ctx.prec = 2
        project = kitchen()
        assert project.openings[1].width.value == Decimal("1730")
        assert to_millimeters("3.270123", "m") == Decimal("3270.123")


def test_kitchen_restrictions_survive_copy_update_and_roundtrip() -> None:
    project = kitchen()
    room = project.spaces[0].dimensions.value
    assert (room.width, room.depth) == (Decimal("3270"), Decimal("2580"))
    rules = [c for c in project.constraints if isinstance(c, WallContact)]
    allowed, forbidden = rules
    assert allowed.kind == "must_touch_wall" and len(allowed.wall_ids.value) == 2
    assert forbidden.kind == "cannot_touch_wall"
    assert set(forbidden.wall_ids.value) == {o.host_wall_id.value for o in project.openings}
    assert set(allowed.wall_ids.value).isdisjoint(forbidden.wall_ids.value)
    renamed = project.model_copy(
        update={"name": project.name.model_copy(update={"value": "Plan B"})}
    )
    restored = deserialize_project(serialize_project(renamed))
    assert restored.constraints == project.constraints
    assert restored.id == project.id
    for wall_id in forbidden.wall_ids.value:
        obj = project.furniture[0].model_copy(
            update={"host_wall_id": Assertion[UUID](value=wall_id, source=Source.USER_EXPLICIT)}
        )
        with pytest.raises(ValidationError, match="wall contact restriction"):
            restored.model_copy(update={"furniture": (obj,)})
    for wall_id in allowed.wall_ids.value:
        obj = project.furniture[0].model_copy(
            update={"host_wall_id": Assertion[UUID](value=wall_id, source=Source.USER_EXPLICIT)}
        )
        assert restored.model_copy(update={"furniture": (obj,)}).constraints == project.constraints
    with pytest.raises(ValueError, match="existing constraints"):
        project.model_copy(update={"constraints": ()})


@pytest.mark.parametrize("version", [None, "", "1.1.0", "2.0.0"])
def test_schema_version_rejected(version: str | None) -> None:
    data = kitchen().model_dump(mode="json")
    if version is None:
        del data["schema_version"]
    else:
        data["schema_version"] = version
    with pytest.raises(ValueError, match="schema_version"):
        deserialize_project(json.dumps(data))


def test_schema_and_unknown_fields() -> None:
    assert Project.model_json_schema()["properties"]["schema_version"]["const"] == "1.0.0"
    with pytest.raises(ValidationError):
        kitchen().model_copy(update={"unknown_field": 1})
    with pytest.raises(ValidationError):
        kitchen().model_copy(update={"units": "cm"})
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        deserialize_project('{"schema_version":"1.0.0","schema_version":"2.0.0"}')


@pytest.mark.parametrize("source", list(Source))
def test_provenance_roundtrip(source: Source) -> None:
    project = kitchen().model_copy(
        update={"name": Assertion[str](value="Evidence", source=source, source_reference="brief:1")}
    )
    assert deserialize_project(serialize_project(project)).name == project.name


def test_no_silent_ai_promotion() -> None:
    project = kitchen()
    inferred = project.styles[0].primary_style
    assert inferred.source == Source.AI_INFERRED
    assert project.model_copy().styles[0].primary_style.source == Source.AI_INFERRED
    with pytest.raises(ValueError, match="promotion"):
        inferred.model_copy(update={"source": Source.USER_EXPLICIT})
    data = project.model_dump(mode="json")
    data["styles"][0]["primary_style"]["source"] = "USER_REFERENCE"
    with pytest.raises(ValueError, match="promotion"):
        project.model_copy(update={"styles": data["styles"]})


@pytest.mark.parametrize(
    "field,value",
    [("value", Decimal("200")), ("source", Source.USER_REFERENCE), ("source_reference", "brief:1")],
)
def test_frozen_nested_values_and_validated_copy(field: str, value: object) -> None:
    project = kitchen()
    with pytest.raises(ValidationError):
        setattr(project.walls[0].thickness, field, value)
    updated = project.walls[0].thickness.model_copy(update={"value": Decimal("200")})
    assert updated.value == Decimal("200")
    assert project.walls[0].thickness.value == Decimal("150")
    with pytest.raises(ValidationError):
        project.walls[0].thickness.model_copy(update={"value": "-10"})


def test_locked_camera_preserved() -> None:
    project = kitchen()
    changed = project.cameras[0].model_copy(
        update={"locked": {"value": False, "source": "USER_EXPLICIT"}}
    )
    with pytest.raises(ValueError, match="locked or preserved"):
        project.model_copy(update={"cameras": (changed,)})
    with pytest.raises(ValidationError, match="missing camera"):
        project.model_copy(update={"cameras": ()})


@pytest.mark.parametrize(
    "vertices",
    [
        [(0, 0), (0, 10), (10, 10), (10, 0)],
        [(0, 0), (10, 0), (0, 0)],
        [(0, 0), (10, 10), (0, 10), (10, 0)],
        [(0, 0), (10, 0), (20, 0)],
    ],
)
def test_invalid_boundaries(vertices: list[tuple[int, int]]) -> None:
    with pytest.raises(ValidationError):
        Boundary.model_validate({"vertices": [{"x": x, "y": y} for x, y in vertices]})


def test_all_constraint_variants_roundtrip_and_reference_validation() -> None:
    project = kitchen()
    target = Assertion[UUID](value=project.furniture[0].id, source=Source.USER_EXPLICIT)
    targets = Assertion[tuple[UUID, UUID]](
        value=(project.furniture[0].id, project.fixed_elements[0].id), source=Source.USER_EXPLICIT
    )
    rules: list[Constraint] = [
        ForbiddenArea(
            id=uuid4(),
            area=project.spaces[0].boundary,
            object_type=project.furniture[0].object_type,
        ),
        RequiredClearance(
            id=uuid4(), target_id=target, clearance=project.furniture[0].clearance_requirements
        ),
        Alignment.model_validate(
            {
                "id": uuid4(),
                "target_ids": targets,
                "axis": {"value": "x", "source": "USER_EXPLICIT"},
            }
        ),
    ]
    for kind in ("minimum_distance", "maximum_distance"):
        rules.append(
            Distance.model_validate(
                {
                    "id": uuid4(),
                    "kind": kind,
                    "target_ids": targets,
                    "distance": {"value": "100", "source": "USER_EXPLICIT"},
                }
            )
        )
    for kind in ("locked_geometry", "locked_camera", "locked_object", "preserved_element"):
        rules.append(
            Lock.model_validate(
                {
                    "id": uuid4(),
                    "kind": kind,
                    "target_id": {
                        "value": project.cameras[0].id if kind == "locked_camera" else target.value,
                        "source": "USER_EXPLICIT",
                    },
                }
            )
        )
    updated = project.model_copy(update={"constraints": (*project.constraints, *rules)})
    assert deserialize_project(serialize_project(updated)) == updated
    invalid = Lock(kind="locked_camera", id=uuid4(), target_id=target)
    with pytest.raises(ValidationError, match="incompatible"):
        project.model_copy(update={"constraints": (*project.constraints, invalid)})
