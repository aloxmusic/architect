"""Pure instruction adapters. No SDK imports, provider clients or image operations."""

import json
from hashlib import sha256
from typing import Protocol

from architect_ai.domain.generation import (
    ChangePermission,
    CompiledInstructionPackage,
    GenerationBrief,
)

INSTRUCTION_VERSION = "architectural-image-instructions-v1"


class ImageInstructionAdapter(Protocol):
    def compile(self, brief: GenerationBrief) -> CompiledInstructionPackage: ...


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def instruction_package(
    brief: GenerationBrief, adapter: str, task: str
) -> CompiledInstructionPackage:
    brief = GenerationBrief.model_validate(brief)
    subject = brief.project
    allowed = [
        {
            "category": p.category.value,
            "entity_ids": [str(i) for i in p.allowed_entity_ids],
            "new_entity_types": p.new_entity_types,
            "instructions": [r.instruction.model_dump(mode="json") for r in p.requests],
        }
        for p in brief.permissions
        if p.permission == ChangePermission.ALLOW
    ]
    facts = {
        "space": subject.relevant_space.model_dump(mode="json"),
        "walls": [w.model_dump(mode="json") for w in brief.geometry.walls],
        "openings": [o.model_dump(mode="json") for o in brief.geometry.openings],
        "fixed_elements": [e.model_dump(mode="json") for e in brief.geometry.fixed_elements],
        "furniture": [f.model_dump(mode="json") for f in brief.geometry.furniture],
        "styles": [s.model_dump(mode="json") for s in brief.design.styles],
        "materials": [m.model_dump(mode="json") for m in brief.materials.existing],
        "lighting": [light.model_dump(mode="json") for light in brief.lighting.elements],
        "camera": brief.camera.camera.model_dump(mode="json") if brief.camera.camera else None,
        "accepted_facts": [f.model_dump(mode="json") for f in brief.accepted_facts],
    }
    primary = (
        f"{task} {brief.output.target.value} of {subject.relevant_space.space_type.value} "
        f"in project {subject.name.value} ({subject.project_type.value}); units {subject.units}. "
        f"Mode: {brief.mode_policy.mode.value}. "
        "Preservation and forbidden changes take precedence over aesthetic instructions. "
        "Change only the listed scopes; ALLOW is not permission to change unrelated elements. "
        f"Allowed changes: {compact(allowed)}. "
        "ADG facts and accepted facts (original sources retained; AI_INFERRED is not explicit): "
        f"{compact(facts)}. "
        "Unverified product entries are requested intent only, not verified specifications. "
        "Only verified_facts contains verified product data; status alone is not evidence. "
        "Do not invent codes, finishes, dimensions or technical product properties. "
        "Use physically plausible materials, scale, surface detail, reflections, construction "
        "and lighting consistent with the supplied facts. "
        f"Photographic presentation: {brief.realism.photographic_intent.value}."
    )
    preservation = (
        "Preserve walls, openings, fixed elements and furniture positions wherever their "
        "category/entity aspect is PRESERVE or LOCKED. Fully preserved entity IDs cannot be "
        "redesigned or moved; an aspect-level preservation does not forbid other allowed aspects. "
        f"Category permissions: {
            compact({p.category.value: p.permission.value for p in brief.permissions})
        }. "
        f"Entity permissions: {
            compact([p.model_dump(mode='json') for p in brief.entity_permissions])
        }. "
        f"Preserved entity IDs: {compact([str(i) for i in brief.geometry.preserved_entity_ids])}. "
        f"Camera/composition preservation: {brief.camera.preserve_composition}. "
        f"Accepted preservation: {
            compact(
                [p.model_dump(mode='json') for p in brief.forbidden_changes.intent_preservation]
            )
        }. "
        f"Project constraints: {
            compact(
                [c.model_dump(mode='json') for c in brief.forbidden_changes.project_restrictions]
            )
        }. "
        "Hard constraints are mandatory; soft constraints remain preferences."
    )
    negative = (
        "No changes outside allowed entity/request scopes. "
        f"Forbidden categories: {', '.join(c.value for c in brief.forbidden_changes.categories)}. "
        f"Protected IDs: {compact([str(i) for i in brief.forbidden_changes.protected_ids])}. "
        f"Prohibited style characteristics: {
            compact(
                [
                    a.model_dump(mode='json')
                    for a in brief.forbidden_changes.prohibited_style_characteristics
                ]
            )
        }. "
        "No invented architectural facts or unverified product specifications."
    )
    reference = brief.reference
    reference_roles = ", ".join(r.value for r in reference.roles) or "none"
    guidance = (
        (
            (
                f"Reference image available; roles: {reference_roles}. "
                f"Preserve reference camera: {reference.preserve_camera}; "
                f"preserve reference composition: {reference.preserve_composition}. "
                "Style/material reference does not authorize geometry or camera changes."
            ),
        )
        if reference.available
        else ()
    )
    return CompiledInstructionPackage(
        compiler_version=brief.compiler_version,
        instruction_version=INSTRUCTION_VERSION,
        adapter=adapter,
        primary_instruction=primary,
        preservation_instruction=preservation,
        negative_instruction=negative,
        reference_guidance=guidance,
        output=brief.output,
        mode_policy=brief.mode_policy,
        permissions=brief.permissions,
        entity_permissions=brief.entity_permissions,
        forbidden_changes=brief.forbidden_changes,
        reference=reference,
        brief_fingerprint=sha256(brief.model_dump_json().encode("utf-8")).hexdigest(),
    )


class OpenAIImageInstructionAdapter:
    def compile(self, brief: GenerationBrief) -> CompiledInstructionPackage:
        return instruction_package(brief, "openai_image", "Create the requested architectural")


class GenericTextToImageInstructionAdapter:
    def compile(self, brief: GenerationBrief) -> CompiledInstructionPackage:
        return instruction_package(brief, "generic_text_to_image", "Generate an architectural")


class GenericImageToImageInstructionAdapter:
    def compile(self, brief: GenerationBrief) -> CompiledInstructionPackage:
        if not brief.reference.available:
            raise ValueError("Image-to-image instructions require an available reference image")
        return instruction_package(brief, "generic_image_to_image", "Edit the supplied image as an")
