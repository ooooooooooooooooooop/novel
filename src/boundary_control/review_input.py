"""Referential integrity of the supplied review context (not story quality)."""

from src.object_state import CharacterModel, NarrativeState, PlotUnit


class ReviewInputError(ValueError):
    """A caller supplied an incomplete/ambiguous context, so review is invalid."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("REVIEW_INPUT_INVALID: " + "; ".join(missing))


def validate_review_input(
    objects: list,
    *,
    require_full_context: bool = True,
) -> None:
    """Reject incomplete, dangling, or duplicate full-chain review input.

    This checks the container handed to a full-chain reviewer. It does not
    assess progression, synthesize missing objects, or waive narrative issues.

    ``require_full_context`` is kept explicit so callers that intentionally
    inspect partial reconstructed material can reuse the referential checks
    without turning an audit into a fail-fast production gate.
    """
    states = [o for o in objects if isinstance(o, NarrativeState)]
    cast = [o for o in objects if isinstance(o, CharacterModel)]
    units = [o for o in objects if isinstance(o, PlotUnit)]
    state_ids = {o.state_id for o in states}
    cast_ids = {o.character_id for o in cast}
    errors = []
    if require_full_context:
        if not states:
            errors.append("missing NarrativeState")
        if not cast:
            errors.append("missing CharacterModel")
        if not units:
            errors.append("missing PlotUnit")
    if len(state_ids) != len(states):
        errors.append("duplicate NarrativeState IDs")
    if len(cast_ids) != len(cast):
        errors.append("duplicate CharacterModel IDs")
    for state in states:
        for ref in state.active_characters:
            if ref not in cast_ids:
                errors.append(f"{state.state_id}.active_characters -> {ref}")
    for character in cast:
        for ref in character.relations:
            if ref not in cast_ids:
                errors.append(f"{character.character_id}.relations -> {ref}")
    for unit in units:
        for field in ("input_state_ref", "output_state_ref"):
            ref = getattr(unit, field)
            if ref and ref not in state_ids:
                errors.append(f"{unit.unit_id}.{field} -> {ref}")
        for ref in unit.participants:
            if ref not in cast_ids:
                errors.append(f"{unit.unit_id}.participants -> {ref}")
    if errors:
        raise ReviewInputError(errors)
