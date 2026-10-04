# Architectural Design Graph

Status: Phase 2 COMPLETE; locally verified on Windows through Codex on 2026-10-01.
See PROJECT_STATE.md for the recorded test, Ruff and mypy results.

The ADG is a provider-independent, typed project snapshot, not a prompt. Schema
`1.0.0` lives in `domain/adg_v1.py`; `domain/serialization.py` explicitly dispatches
the version. Unsupported or missing wire versions and duplicate JSON keys fail.
No migrations, revision history, persistence, API routes or AI parsing are implemented.
Existing Phase 1 HTTP contracts are unchanged.

## Coordinates and units

Right-handed Cartesian world frame: +X right/east on plan, +Y up/north on plan,
+Z upward in elevation. The project origin is an explicitly chosen local origin;
georeferencing is out of scope. All lengths, including lens focal length, use mm.
Space boundaries are simple counterclockwise XY polygons, implicitly closed.
Their XY bounding extents match space width/depth. Ceiling height is measured
above floor elevation. Wall endpoints describe a horizontal baseline at base Z;
height extends upward. Opening position is a distance from the host wall start
along its baseline; sill height is relative to that baseline Z. Opening intervals
may touch but cannot overlap in both horizontal and vertical dimensions.

Furniture/fixed-element positions identify local bounding-box centers in XY and
base elevation in Z. Rotation is degrees counterclockwise about +Z, in [0, 360).
Dimensions are local width/depth/height. Clearances are distances from local box
faces. Camera field_of_view is horizontal degrees, aspect_ratio is width/height;
sensor size and lens/FOV coupling are not modeled. Color temperature uses kelvin.

Finite Decimal values accept integers, decimal strings or Decimal, never floats
or booleans. Magnitude is limited to 1e9 with at most six fractional decimal
digits; values are never rounded silently. JSON decimals are normalized strings.
`to_millimeters` explicitly converts mm/cm/m. Geometric predicates use Fraction
arithmetic for exact results independent of the ambient Decimal context; no
implicit tolerance is applied. This is not a CAD geometry kernel.

## Provenance and immutable updates

Every relevant assertion requires `value` and `source`, with optional
`source_reference`. Sources are USER_EXPLICIT, USER_REFERENCE, IMPORTED_GEOMETRY,
SYSTEM_DERIVED and AI_INFERRED. Provenance on a compound value (dimensions,
coordinates, palette or boundary) applies to the entire compound assertion.
IDs, schema tags, units and constraint discriminators are structural metadata.
UUIDs must be supplied by the caller; copies and serialization retain them.

Models are frozen and collections are tuples. `model_copy(update=...)` is
overridden to revalidate, including nested values. Normal project updates retain
existing constraints and locked/preserved entities. AI-to-user source relabeling
through copy operations is rejected. Explicit acceptance requires a later workflow;
freshly supplied documents cannot authenticate the truth of source labels.
Do not use Pydantic `model_construct`, legacy `copy`, or Python object mutation
to bypass validation. These are trusted-process escape hatches, not ADG APIs.

## Constraints and validation boundary

Discriminated typed constraints represent forbidden_area, required_clearance,
must_touch_wall, cannot_touch_wall, alignment, minimum_distance, maximum_distance,
locked_geometry, locked_camera, locked_object and preserved_element. Each has
typed parameters, provenance-bearing targets/values and hard/soft strength.
Entity IDs are unique across the project; references and target types are checked.
Physical dimensions must be positive where required. Walls, polygons, openings,
camera targets and space dimension consistency have deterministic validation.

Wall-contact rules currently validate declared furniture host-wall associations,
not physical contact or incidental contact with a second wall. For must_touch_wall,
the wall list is an allowed set, not a requirement to touch every listed wall.
Forbidden regions, clearances, alignment and distances are represented and
reference-validated but not solved or geometrically evaluated. Soft rules are
retained as intent. Constraint satisfaction beyond the validators above is unknown;
there is no claim of complete collision detection or buildability certification.
Fixed furniture and lock constraints conservatively protect the complete entity
during normal project updates. Removing protections requires a future workflow.

## Examples and fixtures

Minimal valid project JSON (an empty project is an intentional draft):

```json
{
  "id": "ad55e45b-a2fa-4ba6-85df-7cda38f36ba4",
  "schema_version": "1.0.0",
  "units": "mm",
  "name": {"value": "Kitchen study", "source": "USER_EXPLICIT"},
  "project_type": {"value": "residential", "source": "USER_EXPLICIT"},
  "locale": {"value": "en-GB", "source": "USER_EXPLICIT"},
  "status": {"value": "draft", "source": "USER_EXPLICIT"}
}
```

`tests/fixtures/adg/` contains living_room, l_layout_kitchen, bedroom and
commercial_bar documents. They are synthetic test scenarios, not verified designs.
The kitchen is rectangular, 3270 x 2580 mm, with an L-layout restriction:
cabinetry may use south/west only; north hosts the window and east hosts the
1730 mm opening after an 850 mm wall segment. Both are forbidden cabinetry walls.
These restrictions are tested through JSON round trips and normal copy/update.

Official Pydantic models and serialization documentation was reviewed on
2026-09-30 before implementation. No dependency was added or upgraded:
https://docs.pydantic.dev/latest/concepts/models/
https://docs.pydantic.dev/latest/concepts/serialization/
