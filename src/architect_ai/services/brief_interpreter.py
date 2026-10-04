"""Interpret proposals through a provider port; Phase 3A remains the acceptance authority."""

import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from architect_ai.domain.adg_v1 import Entity, Project
from architect_ai.domain.patches import (
    AddConstraint,
    AddEntity,
    ChangesBase,
    Conflict,
    ConflictCode,
    EntityType,
    PatchOperation,
    PatchResult,
    PatchStatus,
    UpdateConstraint,
    UpdateEntity,
)
from architect_ai.domain.values import Assertion, DomainModel, Source, to_millimeters
from architect_ai.services.brief_context import build_project_context
from architect_ai.services.brief_contracts import (
    ArchitecturalInterpreterProvider,
    BriefReference,
    BriefRequest,
    InterpretationProposal,
    InterpreterProviderError,
    ProviderErrorCode,
    ProviderInterpretation,
)
from architect_ai.services.patching import (
    apply_patch,
    operation_target,
    project_context,
)


class BriefEvaluation(DomainModel):
    interpretation: ProviderInterpretation
    patch_result: PatchResult


class ArchitecturalBriefInterpreter:
    def __init__(self, provider: ArchitecturalInterpreterProvider) -> None:
        self.provider = provider

    def interpret_only(
        self,
        project: Project,
        text: str,
        *,
        references: tuple[BriefReference, ...] = (),
    ) -> ProviderInterpretation:
        request = BriefRequest(
            text=text, context=build_project_context(project), references=references
        )
        try:
            result = ProviderInterpretation.model_validate(self.provider.interpret(request))
            proposal = result.proposal
            known = {entity.entity.id for entity in request.context.entities}
            intent = proposal.intent
            intent_ids = [*intent.target_ids]
            groups = (
                intent.requested_operations,
                intent.style_changes,
                intent.material_changes,
                intent.lighting_changes,
                intent.furniture_changes,
                intent.camera_changes,
                intent.requested_outputs,
            )
            for group in groups:
                intent_ids.extend(target for item in group for target in item.target_ids)
            intent_ids.extend(
                target for item in intent.explicit_facts for target in item.target_ids
            )
            intent_ids.extend(
                target for item in intent.preservation_instructions for target in item.target_ids
            )
            if any(target not in known for target in intent_ids):
                raise ValueError("Unknown intent target")
            if any(
                a.source != Source.AI_INFERRED for a in (*proposal.assumptions, *intent.assumptions)
            ):
                raise ValueError("Assumptions must be inferred")
            return result
        except InterpreterProviderError:
            raise
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise InterpreterProviderError(ProviderErrorCode.INVALID_RESPONSE) from None

    def interpret_and_evaluate(
        self,
        project: Project,
        text: str,
        *,
        references: tuple[BriefReference, ...] = (),
        confirmed_destructive: bool = False,
    ) -> BriefEvaluation:
        interpretation = self.interpret_only(project, text, references=references)
        result = evaluate_proposal(
            project,
            interpretation.proposal,
            text,
            references=references,
            confirmed_destructive=confirmed_destructive,
        )
        return BriefEvaluation(interpretation=interpretation, patch_result=result)


def evaluate_proposal(
    project: Project,
    proposal: InterpretationProposal,
    text: str,
    *,
    references: tuple[BriefReference, ...] = (),
    confirmed_destructive: bool = False,
) -> PatchResult:
    """Shared deterministic boundary for host proposals and provider interpretations."""
    patch = proposal.proposed_patch
    if patch is None:
        result = PatchResult(
            status=PatchStatus.NEEDS_CLARIFICATION,
            original=project_context(project),
            conflicts=(
                Conflict(
                    code=ConflictCode.VALIDATION_FAILED,
                    severity="clarification",
                    message="Intent has no actionable patch; clarification is required",
                    requires_clarification=True,
                ),
            ),
        )
        return result
    # Even invalid targets/constraints flow through the deterministic engine.
    result = apply_patch(project, patch, confirmed_destructive=confirmed_destructive)
    conflicts = [*result.conflicts, *proposal_conflicts(project, proposal, text, references)]
    if proposal.clarification_recommended or proposal.ambiguities or proposal.intent.ambiguities:
        conflicts.append(
            Conflict(
                code=ConflictCode.VALIDATION_FAILED,
                severity="clarification",
                message="Interpretation contains unresolved material ambiguity",
                requires_clarification=True,
            )
        )
    known = {entity.id: entity for entity in project.entities()}
    intent = proposal.intent
    requests = (
        *intent.requested_operations,
        *intent.style_changes,
        *intent.material_changes,
        *intent.lighting_changes,
        *intent.furniture_changes,
        *intent.camera_changes,
        *intent.requested_outputs,
    )
    numeric_facts = numeric_evidence(text)
    for index, operation in enumerate(patch.operations):
        target = operation_target(operation)
        kind = proposal_type(operation)
        preserved = any(
            target in instruction.target_ids or kind in instruction.target_types
            for instruction in intent.preservation_instructions
        )
        if preserved:
            conflicts.append(
                Conflict(
                    code=ConflictCode.PRESERVED_ELEMENT,
                    message="Operation violates this brief's preservation instructions",
                    target_ids=(target,),
                    proposed=operation,
                    operation_index=index,
                )
            )
        if not any(
            request.operation == operation.operation
            and (not request.target_types or kind in request.target_types)
            and (not request.target_ids or target in request.target_ids)
            for request in requests
        ):
            conflicts.append(
                Conflict(
                    code=ConflictCode.VALIDATION_FAILED,
                    message="Patch operation is outside the declared architectural intent",
                    target_ids=(target,),
                    proposed=operation,
                    operation_index=index,
                )
            )
        if operation.source == Source.USER_EXPLICIT and (
            not operation.origin or operation.origin not in text
        ):
            conflicts.append(
                Conflict(
                    code=ConflictCode.PROVENANCE_CONFLICT,
                    message="Explicit operation origin must quote the actual user brief",
                    target_ids=(target,),
                    proposed=operation,
                    operation_index=index,
                )
            )
        if operation.source == Source.USER_REFERENCE and operation.origin not in {
            reference.reference_id for reference in references
        }:
            conflicts.append(
                Conflict(
                    code=ConflictCode.PROVENANCE_CONFLICT,
                    message="Reference operation must identify a supplied reference",
                    target_ids=(target,),
                    proposed=operation,
                    operation_index=index,
                )
            )
        if isinstance(operation, (UpdateEntity, UpdateConstraint)):
            for field in operation.changes.model_fields_set:
                new_assertion = getattr(operation.changes, field)
                if (
                    isinstance(new_assertion, Assertion)
                    and new_assertion.source == Source.USER_EXPLICIT
                    and isinstance(new_assertion.value, Decimal)
                    and new_assertion.value not in numeric_facts
                ):
                    conflicts.append(
                        Conflict(
                            code=ConflictCode.PROVENANCE_CONFLICT,
                            message="Explicit numeric fact is not supported by the user brief",
                            target_ids=(target,),
                            fields=(field,),
                            proposed=operation,
                            operation_index=index,
                        )
                    )
        if kind == "material" and isinstance(operation, (UpdateEntity, AddEntity)):
            new_fields: Entity | ChangesBase
            if isinstance(operation, AddEntity):
                new_fields = operation.payload.entity
                changed_fields = set(type(new_fields).model_fields)
            else:
                new_fields = operation.changes
                changed_fields = new_fields.model_fields_set
            old_record = known.get(target)
            named_product = any(
                getattr(new_fields, field)
                if field in changed_fields
                else getattr(old_record, field, None)
                for field in ("manufacturer", "collection", "product")
            )
            for field in (
                "manufacturer",
                "collection",
                "product",
                "finish",
                "dimensions",
                "verification_status",
            ):
                if field not in changed_fields:
                    continue
                new = getattr(new_fields, field)
                old = getattr(old_record, field, None)
                if new is None or new == old:
                    continue
                if field == "verification_status" and new.value == "unverified":
                    continue
                if field in {"finish", "dimensions"} and not named_product:
                    continue
                # Product facts require actual user text or supplied reference evidence.
                evidence = (
                    text
                    if new.source == Source.USER_EXPLICIT
                    else "\n".join(
                        ref.text for ref in references if ref.reference_id == new.source_reference
                    )
                    if new.source == Source.USER_REFERENCE
                    else ""
                )
                if (
                    not evidence
                    or str(new.value) not in evidence
                    or (field == "verification_status" and new.value == "verified")
                ):
                    conflicts.append(
                        Conflict(
                            code=ConflictCode.PROVENANCE_CONFLICT,
                            message="Unsupported product fact or verification claim",
                            target_ids=(target,),
                            fields=(field,),
                            proposed=operation,
                            operation_index=index,
                        )
                    )
    if conflicts:
        status = (
            PatchStatus.REJECTED
            if any(c.severity == "error" for c in conflicts)
            else PatchStatus.NEEDS_CLARIFICATION
        )
        result = PatchResult(
            status=status,
            original=result.original,
            conflicts=tuple(conflicts),
            rejected_operations=patch.operations,
        )
    return result


def proposal_type(operation: PatchOperation) -> EntityType:
    if isinstance(operation, (AddEntity, AddConstraint)):
        return operation.payload.entity_type
    if isinstance(operation, (UpdateEntity, UpdateConstraint)):
        return operation.changes.entity_type
    return operation.entity_type


def proposal_conflicts(
    project: Project,
    proposal: InterpretationProposal,
    text: str,
    references: tuple[BriefReference, ...],
) -> list[Conflict]:
    """Check intent IDs and evidence without trusting host/provider source labels."""
    intent = proposal.intent
    known = {entity.id for entity in project.entities()}
    groups = (
        intent.requested_operations,
        intent.style_changes,
        intent.material_changes,
        intent.lighting_changes,
        intent.furniture_changes,
        intent.camera_changes,
        intent.requested_outputs,
        intent.explicit_facts,
        intent.preservation_instructions,
    )
    targets = (
        *intent.target_ids,
        *(i for group in groups for item in group for i in item.target_ids),
    )
    conflicts: list[Conflict] = []
    unknown = tuple(dict.fromkeys(i for i in targets if i not in known))
    if unknown:
        conflicts.append(
            Conflict(
                code=ConflictCode.INVALID_REFERENCE,
                message="Intent references an unknown entity",
                target_ids=unknown,
            )
        )
    if any(a.source != Source.AI_INFERRED for a in (*proposal.assumptions, *intent.assumptions)):
        conflicts.append(
            Conflict(
                code=ConflictCode.PROVENANCE_CONFLICT,
                message="Assumptions must retain inferred provenance",
            )
        )
    reference_text = {ref.reference_id: ref.text for ref in references}

    def check(data: Any) -> None:
        if isinstance(data, dict):
            source = data.get("source")
            value = data.get("value")
            origin = data.get("source_reference")
            evidence = (
                text
                if source == Source.USER_EXPLICIT
                else reference_text.get(origin, "")
                if isinstance(origin, str)
                else ""
            )
            unsupported = False
            if source in {Source.USER_EXPLICIT, Source.USER_REFERENCE}:
                if isinstance(value, str):
                    try:
                        UUID(value)
                    except ValueError:
                        # Explicit text is a quote; paraphrases must remain AI_INFERRED.
                        try:
                            number = Decimal(value)
                        except ArithmeticError:
                            unsupported = not evidence or value not in evidence
                        else:
                            unsupported = number not in numeric_evidence(evidence)
                if source == Source.USER_REFERENCE and origin not in reference_text:
                    unsupported = True
                if source == Source.USER_EXPLICIT and origin is not None and origin not in text:
                    unsupported = True
            if unsupported:
                conflicts.append(
                    Conflict(
                        code=ConflictCode.PROVENANCE_CONFLICT,
                        message="Intent assertion lacks supplied user or reference evidence",
                    )
                )
            for item in data.values():
                check(item)
        elif isinstance(data, (tuple, list)):
            for item in data:
                check(item)

    check(intent.model_dump(mode="python"))
    patch = proposal.proposed_patch
    if patch is not None:
        by_id = {entity.id: entity for entity in project.entities()}
        for operation in patch.operations:
            if isinstance(operation, (AddEntity, AddConstraint)):
                fields = operation.payload.entity.model_dump(mode="python")
            elif isinstance(operation, (UpdateEntity, UpdateConstraint)):
                fields = operation.changes.model_dump(mode="python")
            else:
                continue
            # Phase 3A checks operation/source consistency; references also need evidence IDs.
            for field, assertion in fields.items():
                old = getattr(by_id.get(operation_target(operation)), field, None)
                if isinstance(old, Assertion) and assertion == old.model_dump(mode="python"):
                    continue
                if isinstance(assertion, dict) and assertion.get("source") == Source.USER_EXPLICIT:
                    check(assertion)
                if isinstance(assertion, dict) and assertion.get("source") == Source.USER_REFERENCE:
                    if assertion.get("source_reference") not in reference_text:
                        conflicts.append(
                            Conflict(
                                code=ConflictCode.PROVENANCE_CONFLICT,
                                message="Patch assertion references missing evidence",
                                target_ids=(operation_target(operation),),
                            )
                        )
    return conflicts


def numeric_evidence(text: str) -> set[Decimal]:
    """A conservative evidence check, not an architectural natural-language parser."""
    values: set[Decimal] = set()
    for token, unit in re.findall(
        r"(?<!\w)([+-]?\d+(?:[.,]\d+)?)(?:\s*(mm|cm|m)\b)?", text.lower()
    ):
        number = Decimal(token.replace(",", "."))
        values.add(number)
        if unit in {"mm", "cm", "m"}:
            try:
                if unit == "mm":
                    values.add(to_millimeters(number, "mm"))
                elif unit == "cm":
                    values.add(to_millimeters(number, "cm"))
                else:
                    values.add(to_millimeters(number, "m"))
            except ValueError:
                pass
    return values
