"""ADG schema 1.0.0. References form the graph; no infrastructure dependencies."""

from collections.abc import Mapping
from fractions import Fraction
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from architect_ai.domain.values import (
    Angle,
    Assertion,
    Clearance,
    Dimensions,
    DomainModel,
    NonNegative,
    Number,
    Point2,
    Point3,
    Positive,
    Text,
)


def cross(a: Point2, b: Point2, c: Point2) -> Fraction:
    return (Fraction(b.x) - Fraction(a.x)) * (Fraction(c.y) - Fraction(a.y)) - (
        Fraction(b.y) - Fraction(a.y)
    ) * (Fraction(c.x) - Fraction(a.x))


def intersects(a: Point2, b: Point2, c: Point2, d: Point2) -> bool:
    def on_segment(p: Point2, q: Point2, r: Point2) -> bool:
        return (
            cross(p, q, r) == 0
            and min(p.x, q.x) <= r.x <= max(p.x, q.x)
            and min(p.y, q.y) <= r.y <= max(p.y, q.y)
        )

    if any((on_segment(a, b, c), on_segment(a, b, d), on_segment(c, d, a), on_segment(c, d, b))):
        return True
    return cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0


class Boundary(DomainModel):
    vertices: Annotated[tuple[Point2, ...], Field(min_length=3)]

    @model_validator(mode="after")
    def valid_polygon(self) -> Self:
        points = self.vertices
        if len(set(points)) != len(points):
            raise ValueError("Boundary vertices must be distinct; closure is implicit")
        area = sum(
            Fraction(p.x) * Fraction(q.y) - Fraction(q.x) * Fraction(p.y)
            for p, q in zip(points, (*points[1:], points[0]), strict=True)
        )
        if area <= 0:
            raise ValueError("Boundary must have positive area and counterclockwise winding")
        n = len(points)
        for i in range(n):
            if cross(points[i - 1], points[i], points[(i + 1) % n]) == 0:
                raise ValueError("Adjacent boundary edges must not be collinear")
            for j in range(i + 1, n):
                if j == i + 1 or (i == 0 and j == n - 1):
                    continue
                if intersects(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]):
                    raise ValueError("Boundary must not self-intersect")
        return self


class Entity(DomainModel):
    id: UUID


class Space(Entity):
    space_type: Assertion[Text]
    dimensions: Assertion[Dimensions]
    floor_elevation: Assertion[Number]
    ceiling_height: Assertion[Positive]
    boundary: Assertion[Boundary]

    @model_validator(mode="after")
    def consistent_dimensions(self) -> Self:
        p = self.boundary.value.vertices
        d = self.dimensions.value
        if (
            Fraction(max(v.x for v in p)) - Fraction(min(v.x for v in p)) != d.width
            or Fraction(max(v.y for v in p)) - Fraction(min(v.y for v in p)) != d.depth
            or d.height != self.ceiling_height.value
        ):
            raise ValueError("Space dimensions must match boundary bounds and ceiling height")
        return self


class Wall(Entity):
    start: Assertion[Point3]
    end: Assertion[Point3]
    thickness: Assertion[Positive]
    height: Assertion[Positive]
    wall_type: Assertion[Text]

    @model_validator(mode="after")
    def valid_segment(self) -> Self:
        a, b = self.start.value, self.end.value
        if a.z != b.z or (a.x, a.y) == (b.x, b.y):
            raise ValueError("Wall must be a nonzero horizontal baseline")
        return self


class Opening(Entity):
    opening_type: Assertion[Literal["door", "window", "opening"]]
    host_wall_id: Assertion[UUID]
    position: Assertion[NonNegative]
    width: Assertion[Positive]
    height: Assertion[Positive]
    sill_height: Assertion[NonNegative]


class FixedElement(Entity):
    element_type: Assertion[
        Literal[
            "structural_column",
            "shaft",
            "plumbing_point",
            "hvac",
            "electrical_constraint",
            "built_in_element",
        ]
    ]
    dimensions: Assertion[Dimensions]
    position: Assertion[Point3]
    rotation: Assertion[Angle]


class FurnitureObject(Entity):
    object_type: Assertion[Text]
    dimensions: Assertion[Dimensions]
    position: Assertion[Point3]
    rotation: Assertion[Angle]
    clearance_requirements: Assertion[Clearance]
    fixed_or_movable: Assertion[Literal["fixed", "movable"]]
    host_wall_id: Assertion[UUID] | None = None


class Style(Entity):
    primary_style: Assertion[Text]
    secondary_influences: Assertion[tuple[Text, ...]]
    palette: Assertion[tuple[Text, ...]]
    material_characteristics: Assertion[tuple[Text, ...]]
    mood: Assertion[Text]
    design_intensity: Assertion[Annotated[Number, Field(ge=0, le=1)]]
    prohibited_characteristics: Assertion[tuple[Text, ...]]


class Material(Entity):
    generic_material: Assertion[Text]
    manufacturer: Assertion[Text] | None = None
    collection: Assertion[Text] | None = None
    product: Assertion[Text] | None = None
    finish: Assertion[Text] | None = None
    dimensions: Assertion[Dimensions] | None = None
    verification_status: Assertion[Literal["verified", "unverified"]]
    source_reference: Assertion[Text] | None = None

    @model_validator(mode="after")
    def verified_evidence(self) -> Self:
        if self.verification_status.value == "verified":
            if self.source_reference is None or self.verification_status.source == "AI_INFERRED":
                raise ValueError("Verified material requires evidence and non-AI verification")
        return self


class Lighting(Entity):
    fixture_intent: Assertion[Text]
    color_temperature: Assertion[Annotated[Positive, Field(le=100000)]]
    daylight_intent: Assertion[Text]
    artificial_lighting_intent: Assertion[Text]
    lighting_mood: Assertion[Text]


class Camera(Entity):
    position: Assertion[Point3]
    target: Assertion[Point3]
    focal_length: Assertion[Positive]
    field_of_view: Assertion[Annotated[Positive, Field(lt=180)]]
    aspect_ratio: Assertion[Positive]
    locked: Assertion[bool]

    @model_validator(mode="after")
    def distinct_target(self) -> Self:
        if self.position.value == self.target.value:
            raise ValueError("Camera position and target must differ")
        return self


class OutputIntent(Entity):
    output_type: Assertion[
        Literal[
            "concept",
            "render",
            "floor_plan",
            "elevation",
            "section",
            "dxf",
            "sketchup",
            "animation",
        ]
    ]
    camera_id: Assertion[UUID] | None = None


class ConstraintBase(Entity):
    strength: Literal["hard", "soft"] = "hard"


class ForbiddenArea(ConstraintBase):
    kind: Literal["forbidden_area"] = "forbidden_area"
    area: Assertion[Boundary]
    object_type: Assertion[Text]


class RequiredClearance(ConstraintBase):
    kind: Literal["required_clearance"] = "required_clearance"
    target_id: Assertion[UUID]
    clearance: Assertion[Clearance]


class WallContact(ConstraintBase):
    kind: Literal["must_touch_wall", "cannot_touch_wall"]
    wall_ids: Assertion[Annotated[tuple[UUID, ...], Field(min_length=1)]]
    object_type: Assertion[Text]
    # For must_touch_wall, an object must select one of these walls.


class Alignment(ConstraintBase):
    kind: Literal["alignment"] = "alignment"
    target_ids: Assertion[Annotated[tuple[UUID, ...], Field(min_length=2)]]
    axis: Assertion[Literal["x", "y", "z"]]


class Distance(ConstraintBase):
    kind: Literal["minimum_distance", "maximum_distance"]
    target_ids: Assertion[tuple[UUID, UUID]]
    distance: Assertion[NonNegative]


class Lock(ConstraintBase):
    kind: Literal["locked_geometry", "locked_camera", "locked_object", "preserved_element"]
    target_id: Assertion[UUID]


Constraint = Annotated[
    ForbiddenArea | RequiredClearance | WallContact | Alignment | Distance | Lock,
    Field(discriminator="kind"),
]


class Project(Entity):
    name: Assertion[Text]
    project_type: Assertion[Text]
    units: Literal["mm"] = "mm"
    locale: Assertion[Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")]]
    status: Assertion[Literal["draft", "in_review", "approved", "archived"]]
    schema_version: Literal["1.0.0"] = "1.0.0"
    spaces: tuple[Space, ...] = ()
    walls: tuple[Wall, ...] = ()
    openings: tuple[Opening, ...] = ()
    fixed_elements: tuple[FixedElement, ...] = ()
    furniture: tuple[FurnitureObject, ...] = ()
    styles: tuple[Style, ...] = ()
    materials: tuple[Material, ...] = ()
    lighting: tuple[Lighting, ...] = ()
    cameras: tuple[Camera, ...] = ()
    output_intents: tuple[OutputIntent, ...] = ()
    constraints: tuple[Constraint, ...] = ()

    def entities(self) -> tuple[Entity, ...]:
        return (
            *self.spaces,
            *self.walls,
            *self.openings,
            *self.fixed_elements,
            *self.furniture,
            *self.styles,
            *self.materials,
            *self.lighting,
            *self.cameras,
            *self.output_intents,
            *self.constraints,
        )

    @model_validator(mode="after")
    def graph_integrity(self) -> Self:
        entities = self.entities()
        ids = [self.id, *(entity.id for entity in entities)]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate IDs within project")
        by_id = {e.id: e for e in entities}
        walls = {w.id: w for w in self.walls}
        geometry_ids = {
            e.id
            for e in (
                *self.spaces,
                *self.walls,
                *self.openings,
                *self.fixed_elements,
                *self.furniture,
            )
        }
        object_ids = {e.id for e in (*self.fixed_elements, *self.furniture)}
        camera_ids = {e.id for e in self.cameras}
        for opening in self.openings:
            wall = walls.get(opening.host_wall_id.value)
            if wall is None:
                raise ValueError("Opening references missing host wall")
            a, b = wall.start.value, wall.end.value
            length_squared = (Fraction(b.x) - Fraction(a.x)) ** 2 + (
                Fraction(b.y) - Fraction(a.y)
            ) ** 2
            extent = Fraction(opening.position.value) + Fraction(opening.width.value)
            top = Fraction(opening.sill_height.value) + Fraction(opening.height.value)
            if extent**2 > length_squared or top > wall.height.value:
                raise ValueError("Impossible opening: exceeds host wall bounds")
        for i, opening in enumerate(self.openings):
            for other in self.openings[i + 1 :]:
                if opening.host_wall_id.value != other.host_wall_id.value:
                    continue

                def overlaps(
                    a: Assertion[NonNegative],
                    w: Assertion[Positive],
                    b: Assertion[NonNegative],
                    v: Assertion[Positive],
                ) -> bool:
                    return Fraction(a.value) < Fraction(b.value) + Fraction(v.value) and Fraction(
                        b.value
                    ) < Fraction(a.value) + Fraction(w.value)

                if overlaps(
                    opening.position, opening.width, other.position, other.width
                ) and overlaps(
                    opening.sill_height, opening.height, other.sill_height, other.height
                ):
                    raise ValueError("Impossible opening: overlapping openings")
        for furniture in self.furniture:
            if furniture.host_wall_id is not None and furniture.host_wall_id.value not in walls:
                raise ValueError("Furniture references missing host wall")
        for output in self.output_intents:
            if output.camera_id is not None and output.camera_id.value not in camera_ids:
                raise ValueError("Output references missing camera")
        for constraint in self.constraints:
            if isinstance(constraint, WallContact):
                refs = constraint.wall_ids.value
                if len(set(refs)) != len(refs) or any(ref not in walls for ref in refs):
                    raise ValueError("Wall constraint requires distinct existing walls")
                if constraint.strength == "hard":
                    for obj in self.furniture:
                        if obj.object_type.value != constraint.object_type.value:
                            continue
                        host = obj.host_wall_id.value if obj.host_wall_id else None
                        if (constraint.kind == "must_touch_wall" and host not in refs) or (
                            constraint.kind == "cannot_touch_wall" and host in refs
                        ):
                            raise ValueError("Furniture violates declared wall contact restriction")
            elif isinstance(constraint, (Alignment, Distance)):
                refs = constraint.target_ids.value
                if len(set(refs)) != len(refs) or any(ref not in geometry_ids for ref in refs):
                    raise ValueError("Constraint requires distinct geometric targets")
            elif isinstance(constraint, (Lock, RequiredClearance)):
                target = constraint.target_id.value
                allowed = geometry_ids
                if isinstance(constraint, Lock):
                    if constraint.kind == "locked_camera":
                        allowed = camera_ids
                    elif constraint.kind == "locked_object":
                        allowed = object_ids
                    elif constraint.kind == "preserved_element":
                        allowed = set(by_id) - {c.id for c in self.constraints}
                if target not in allowed:
                    raise ValueError("Constraint target missing or incompatible")
        return self

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        result = super().model_copy(update=update, deep=deep)
        new_constraints = {c.id: c for c in result.constraints}
        if any(new_constraints.get(c.id) != c for c in self.constraints):
            raise ValueError("Normal updates cannot remove or change existing constraints")
        protected = {
            c.target_id.value
            for c in self.constraints
            if isinstance(c, Lock) and c.strength == "hard"
        }
        protected.update(c.id for c in self.cameras if c.locked.value)
        protected.update(f.id for f in self.furniture if f.fixed_or_movable.value == "fixed")
        before, after = ({e.id: e for e in p.entities()} for p in (self, result))
        if any(before.get(key) != after.get(key) for key in protected):
            raise ValueError("Normal updates cannot change locked or preserved elements")
        if result.id != self.id:
            raise ValueError("Normal updates must preserve project ID")
        return result
