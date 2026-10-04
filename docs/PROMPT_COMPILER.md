# Architectural Prompt Compiler (Phase 4)

The pure compiler converts an authoritative ADG snapshot, caller-accepted
`ArchitecturalIntent`, `CompilationOptions`, and validated project constraints into
an immutable provider-neutral `GenerationBrief`. It does not interpret natural
language, accept proposals, update the ADG, generate images, or call providers.
The Phase 3 interpreter/patch service remains the acceptance boundary. Supplying
an intent to the compiler asserts caller acceptance; source labels do not
authenticate that acceptance.

## Contracts and usage

```python
from architect_ai.domain.generation import (
    CompilationOptions,
    GenerationMode,
    OutputSpecification,
    OutputTarget,
)
from architect_ai.providers.image_instructions import OpenAIImageInstructionAdapter
from architect_ai.services.prompt_compiler import compile_generation_brief

options = CompilationOptions(
    output=OutputSpecification(target=OutputTarget.ARCHITECTURAL_RENDER),
    mode=GenerationMode.GEOMETRY_LOCKED_RENDER_MODE,
)
brief = compile_generation_brief(project, accepted_intent, options)
instructions = OpenAIImageInstructionAdapter().compile(brief)
```

`GenerationBrief` contains project/snapshot context and relevant space; typed
output/presentation metadata; mode policy; category and entity permissions;
geometry, openings, fixed elements, furniture and spatial constraints; styles
(primary/secondary, palette, intensity, mood and prohibitions); materials;
lighting; camera/lens/field of view/aspect ratio; realism policies; forbidden
changes; reference authority; accepted facts, inferred assumptions, withheld
requests and compact field/source traceability. Original ADG assertions retain
their `Source` and `source_reference`. Trace origin distinguishes `ADG`,
`ACCEPTED_INTENT`, and `SYSTEM_COMPILATION`. It is not revision history.

Targets are `concept_image`, `architectural_render`, `image_edit`,
`material_study`, `lighting_study`, and `style_study`. Unsupported targets fail
Pydantic validation. Explicit output/camera IDs select known records; multiple
unresolved cameras, missing targets or unresolved intent ambiguities raise typed
`CompilationError`. A locked camera's aspect ratio cannot be overridden.
Output metadata survives adapters without claiming provider API support.

## Modes and permissions

| Mode | Eligible changes, subject to accepted intent and protections |
| --- | --- |
| `CONCEPT_MODE` | All categories; nonprotected elements may vary only in requested scopes |
| `DESIGN_DEVELOPMENT_MODE` | Controlled design refinement; architecture and positions preserved |
| `GEOMETRY_LOCKED_RENDER_MODE` | Design refinement with walls/openings/fixed geometry/positions preserved |
| `MATERIAL_REVISION_MODE` | Requested materials only; other categories preserved |
| `LIGHTING_REVISION_MODE` | Requested lighting only; other categories preserved |
| `CAMERA_LOCKED_MODE` | Camera/composition preserved; other categories follow accepted scopes |

Categories are geometry, openings, fixed elements, furniture positions, furniture
design, materials, lighting, camera, style, decor, and environment. Permissions are
`ALLOW`, `PRESERVE`, or `LOCKED`. `ALLOW` is bounded by requested instructions,
`allowed_entity_ids` and `new_entity_types`; unrequested entities stay preserved.
Entity permissions describe exceptions without making a category-wide grant.

The compiler uses the existing intent category lists. Unclassified geometry
requests need typed target types. Furniture changes default to design refinement,
never position permission. Distinct movement/decor/environment requests can be
categorized explicitly with `ChangeScope(category=..., request=...)`; that request
must already exist in the accepted intent. No keyword matcher guesses category,
scope, dimensions, products or camera decisions from the goal. A vague luxury goal
alone grants no changes; accepted style/material/lighting scopes grant only those
categories. An ambiguous preservation statement without IDs/types is rejected.

Precedence is hard ADG locks, fixed furniture and preserved elements; accepted
preservation; reference geometry/camera authority and restrictive mode policy;
then requested scopes. Creative modes cannot unlock entities. Locked/preserved
walls also preserve their hosted openings. A locked/preserved space conservatively
preserves its architecture. Conflicting requests are recorded in
`withheld_requests`, excluded from effective adapter instructions, and never
relax protections. A scope touching a protected entity is withheld as a whole.
Supported symbolic graph conflicts are rejected through the existing patch
service checker; all spatial constraints retain their hard/soft strength.

## Materials, unknown facts and realism

Verified material records may supply manufacturer, collection, product, finish,
dimensions and evidence through `verified_facts`. Product assertions/evidence
with `AI_INFERRED` source cannot become verified facts merely because the
material's existing status says verified. Original status is retained as ADG
metadata; `verified_facts` is the compiler's emitted product-fact record.
Unverified manufacturer/collection/product names are retained only as requested
product intent. Missing product codes, finishes, dimensions and technical
properties are never filled in. There is no catalogue lookup or verification.

Unrelated material IDs remain preserved under targeted material revision.
ADG v1 has no material-to-surface assignments: the compiler preserves known
material records and explicit preservation instructions without inventing surface
names. Architectural language, contrast and exposure fields remain empty/`None`
when unavailable; accepted textual facts still retain their source. Realism fields
are source-tagged compilation policies, not invented construction or product data.
Photographic intent is enabled for an architectural render.

## Instruction adapters and references

`OpenAIImageInstructionAdapter`, `GenericTextToImageInstructionAdapter`, and
`GenericImageToImageInstructionAdapter` live in the provider layer. They create
`CompiledInstructionPackage` with primary, preservation, negative and reference
instructions; unchanged output/mode/permission/restriction metadata; and a brief
fingerprint. The structured brief remains authoritative. Shared architectural
phrasing prevents adapter drift; adapters differ in task framing, and image-to-image
requires an available reference. No SDK imports or provider calls are involved.

The OpenAI adapter includes relevant subject/design facts and allowed scopes,
explicit preservation, materials, lighting, camera, realism and prohibitions.
It omits proposal history, withheld instructions and internal reasoning. Named
product intent is explicitly separated from verified specifications. No API model,
image size, upload or tool invocation is selected.

`ReferenceImage` describes availability, geometry authority, style/material roles,
and camera/composition preservation. Authority flags require availability.
Geometry authority preserves geometry/openings/fixed elements/object positions;
camera/composition preservation forbids camera changes. Style/material references
grant no additional permissions. This is a contract only, without asset IDs,
storage, image analysis or uploads.

## Determinism, versions and limitations

Same validated inputs produce equivalent briefs and instruction packages. Stable
IDs and sorted entity collections are retained; no timestamps, random IDs, model
calls or input mutation occur. Compiler contract `generation-brief-v1` and adapter
strategy `architectural-image-instructions-v1` evolve independently of ADG 1.0.0.
There is no migration framework or persistence.

ADG v1 lacks space/entity membership, surface assignments and structured exposure,
contrast, decor or environment data. Multi-space projects are rejected even with
an explicit space ID rather than silently attributing all geometry to one room.
Extra accepted categorization is required for position/decor/environment scopes.
Unknown measurements remain unknown. This compiler is not a spatial solver,
product verifier, renderer, or guarantee that a future image model obeys geometry.
Instruction length scales with the relevant one-space geometry; there is no silent
truncation or invented simplification. All tests are offline; the optional Phase 3
live test must remain disabled during Phase 4 verification.
