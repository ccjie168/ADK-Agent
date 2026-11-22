"""Terminology layer: SKOS-subset concepts and mappings (ADR-0038, layer 1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"

MappingKind = Literal["exact", "close", "broad", "narrow", "related"]


class Term(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str = Field(min_length=1)
    language: str = Field(min_length=1)


class Concept(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(pattern=_SAFE_NAME)
    pref_labels: list[Term] = Field(min_length=1)
    alt_labels: list[Term] = Field(default_factory=list)
    hidden_labels: list[Term] = Field(default_factory=list)
    notation: str | None = None
    definition: str | None = None
    broader: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_self(self) -> Concept:
        languages = [label.language for label in self.pref_labels]
        if len(languages) != len(set(languages)):
            raise ValueError("pref_labels must have one label per language")
        if self.concept_id in self.broader or self.concept_id in self.related:
            raise ValueError("a concept cannot relate to itself")
        return self


class ConceptMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    kind: MappingKind


class ConceptScheme(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme_id: str = Field(pattern=_SAFE_NAME)
    concepts: list[Concept] = Field(default_factory=list)
    mappings: list[ConceptMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_scheme(self) -> ConceptScheme:
        ids = {concept.concept_id for concept in self.concepts}
        if len(ids) != len(self.concepts):
            raise ValueError("concept ids must be unique within a scheme")

        parents = {concept.concept_id: concept.broader for concept in self.concepts}
        for concept in self.concepts:
            for parent in concept.broader:
                if parent not in parents:
                    raise ValueError(f"broader target {parent!r} is not in the scheme")
        self._require_acyclic(parents)

        for mapping in self.mappings:
            if mapping.source_id not in ids or mapping.target_id not in ids:
                raise ValueError("a mapping must reference concepts in the scheme")
            if mapping.kind == "exact" and mapping.source_id == mapping.target_id:
                raise ValueError("an exact mapping cannot be self-referential")
        for mapping in self.mappings:
            if mapping.kind != "exact":
                continue
            for other in self.mappings:
                if other.kind in ("broad", "narrow") and {
                    mapping.source_id,
                    mapping.target_id,
                } == {other.source_id, other.target_id}:
                    raise ValueError("exact and broad/narrow mappings are mutually exclusive")
        return self

    @staticmethod
    def _require_acyclic(parents: dict[str, list[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("broader hierarchy must be acyclic")
            if node in visited:
                return
            visiting.add(node)
            for parent in parents.get(node, []):
                visit(parent)
            visiting.remove(node)
            visited.add(node)

        for node in parents:
            visit(node)


__all__ = ["Concept", "ConceptMapping", "ConceptScheme", "MappingKind", "Term"]
