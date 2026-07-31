"""No-regression validation gates."""

from src.boundary_control.serialization import SerializationBoundaryUnit, SerializationPackage


class NoRegressionValidationUnit:
    """Executable checks for inherited Track 1/2/3 locks."""

    def run(self, package: SerializationPackage) -> list[str]:
        """Run all currently automated no-regression checks."""
        violations = []
        violations.extend(self._separation_tests(package))
        violations.extend(self._track1_tests(package))
        violations.extend(self._runtime_identity_tests(package))
        violations.extend(self._track2_tests(package))
        violations.extend(self._track3_tests(package))
        return violations

    def _separation_tests(self, package: SerializationPackage) -> list[str]:
        """Serialization layer separation must hold at runtime gates."""
        return SerializationBoundaryUnit().check_separation(package)

    def _is_blank(self, value: object) -> bool:
        return not isinstance(value, str) or not value.strip()

    def _track1_tests(self, package: SerializationPackage) -> list[str]:
        """Track 1: FactLedger hard-fact integrity."""
        violations: list[str] = []
        sm = package.stable_memory
        ws = package.working_set
        seen_fact_ids: set[str] = set()

        def check_fact_entry(entry: dict) -> None:
            fact_id = entry.get("fact_id")
            if self._is_blank(fact_id):
                violations.append("Track1: blank fact_id in FactLedger")
            elif fact_id in seen_fact_ids:
                violations.append(f"Track1: duplicate fact_id in FactLedger: {fact_id}")
            else:
                seen_fact_ids.add(fact_id)

            if entry.get("confirmed") is not True:
                violations.append(
                    f"Track1: unconfirmed fact in FactLedger: {entry.get('fact_id')}"
                )

        for ledger in sm.get("FactLedger", []):
            for entry in ledger.get("entries", []):
                check_fact_entry(entry)

        for entry in sm.get("FactEntry", []):
            check_fact_entry(entry)

        if "FactLedger" in ws:
            violations.append("Track1: FactLedger found in working_set (layer violation)")

        return violations

    def _runtime_identity_tests(self, package: SerializationPackage) -> list[str]:
        """Runtime object IDs and references must be explicit."""
        violations: list[str] = []
        sm = package.stable_memory
        ws = package.working_set
        seen_state_ids: set[str] = set()
        seen_plotunit_ids: set[str] = set()
        seen_thread_ids: set[str] = set()
        character_ids = {
            character.get("character_id")
            for character in sm.get("CharacterModel", [])
            if not self._is_blank(character.get("character_id"))
        }

        for state in ws.get("NarrativeState", []):
            state_id = state.get("state_id")
            if self._is_blank(state_id):
                violations.append("Runtime: blank state_id in NarrativeState")
            elif state_id in seen_state_ids:
                violations.append(f"Runtime: duplicate state_id in NarrativeState: {state_id}")
            else:
                seen_state_ids.add(state_id)
            for character_id in state.get("active_characters", []):
                if self._is_blank(character_id):
                    violations.append(
                        f"Runtime: blank active_character in NarrativeState: {state_id}"
                    )
                elif character_ids and character_id not in character_ids:
                    violations.append(
                        "Runtime: unknown active_character in NarrativeState "
                        f"{state_id}: {character_id}"
                    )

        for plotunit in ws.get("PlotUnit", []):
            unit_id = plotunit.get("unit_id")
            if self._is_blank(unit_id):
                violations.append("Runtime: blank unit_id in PlotUnit")
            elif unit_id in seen_plotunit_ids:
                violations.append(f"Runtime: duplicate unit_id in PlotUnit: {unit_id}")
            else:
                seen_plotunit_ids.add(unit_id)
            for field in ("input_state_ref", "output_state_ref"):
                state_ref = plotunit.get(field)
                if self._is_blank(state_ref):
                    violations.append(f"Runtime: blank {field} in PlotUnit: {unit_id}")
                elif state_ref not in seen_state_ids:
                    violations.append(
                        f"Runtime: unknown {field} in PlotUnit {unit_id}: {state_ref}"
                    )
            for character_id in plotunit.get("participants", []):
                if self._is_blank(character_id):
                    violations.append(
                        f"Runtime: blank PlotUnit participant in PlotUnit: {unit_id}"
                    )
                elif character_ids and character_id not in character_ids:
                    violations.append(
                        f"Runtime: unknown PlotUnit participant in PlotUnit "
                        f"{unit_id}: {character_id}"
                    )

        def check_thread(entry: dict) -> None:
            thread_id = entry.get("thread_id")
            if self._is_blank(thread_id):
                violations.append("Runtime: blank thread_id in ForeshadowGraph")
            elif thread_id in seen_thread_ids:
                violations.append(
                    f"Runtime: duplicate thread_id in ForeshadowGraph: {thread_id}"
                )
            else:
                seen_thread_ids.add(thread_id)

        for graph in sm.get("ForeshadowGraph", []):
            for entry in graph.get("entries", []):
                check_thread(entry)
        for entry in sm.get("ForeshadowEntry", []):
            check_thread(entry)

        return violations

    def _track2_tests(self, package: SerializationPackage) -> list[str]:
        """Track 2: bounded runtime-first rewrite."""
        violations: list[str] = []
        rc = package.repair_control

        for issue in rc.get("ReviewIssue", []):
            if issue.get("resolution_status") != "resolved":
                continue
            if package.metadata.get("writeback_complete") is not True:
                violations.append(
                    "Track2: resolved ReviewIssue without writeback_complete metadata"
                )
            if not package.metadata.get("object_writes"):
                violations.append(
                    "Track2: resolved ReviewIssue without object_writes metadata"
                )

        return violations

    def _track3_tests(self, package: SerializationPackage) -> list[str]:
        """Track 3: CharacterModel evidence leakback."""
        violations: list[str] = []
        sm = package.stable_memory
        seen_character_ids: set[str] = set()

        for cm_data in sm.get("CharacterModel", []):
            character_id = cm_data.get("character_id")
            if self._is_blank(character_id):
                violations.append("Track3: blank character_id in CharacterModel")
            elif character_id in seen_character_ids:
                violations.append(
                    f"Track3: duplicate character_id in CharacterModel: {character_id}"
                )
            else:
                seen_character_ids.add(character_id)

            for field in ("knowledge_state", "relations"):
                raw_values = cm_data.get(field, [])
                values = raw_values.values() if isinstance(raw_values, dict) else raw_values
                for value in values:
                    if len(value) > 200:
                        violations.append(
                            f"Track3: CharacterModel.{field} may contain evidence leak: "
                            f"{value[:50]}..."
                        )

        return violations
