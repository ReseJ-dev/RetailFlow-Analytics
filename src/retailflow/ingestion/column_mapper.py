"""Normalize and map source columns onto canonical dataset schemas."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from retailflow.common.exceptions import ConfigurationError, DataValidationError
from retailflow.validation.schemas import DatasetSchema, DatasetType, get_dataset_schema

_DUPLICATE_UNDERSCORES = re.compile(r"_+")
_SPACES_AND_HYPHENS = re.compile(r"[\s-]+")
_DEFAULT_ALIASES_PATH = Path(__file__).resolve().parents[3] / "config" / "column_aliases.yaml"

type AliasMapping = Mapping[str, Sequence[str]]


class ColumnMappingResult(BaseModel):
    """Column-mapping outcome suitable for direct display in Streamlit."""

    model_config = ConfigDict(frozen=True)

    dataset_type: DatasetType
    normalized_columns: dict[str, str]
    matched_required_columns: dict[str, str]
    missing_required_columns: tuple[str, ...]
    matched_optional_columns: dict[str, str]
    unknown_source_columns: tuple[str, ...]
    ambiguous_matches: dict[str, tuple[str, ...]]

    @property
    def is_complete(self) -> bool:
        """Return whether every required field has one unambiguous match."""
        return not self.missing_required_columns and not self.ambiguous_matches

    @property
    def column_mapping(self) -> dict[str, str]:
        """Return a source-to-canonical mapping ready for DataFrame renaming."""
        canonical_to_source = self.matched_required_columns | self.matched_optional_columns
        return {source: canonical for canonical, source in canonical_to_source.items()}

    def to_display_rows(self) -> list[dict[str, str]]:
        """Return mapping details as row dictionaries for a Streamlit table."""
        required = set(self.matched_required_columns) | set(self.missing_required_columns)
        rows: list[dict[str, str]] = []
        matched = self.matched_required_columns | self.matched_optional_columns
        for canonical, source in matched.items():
            rows.append(
                {
                    "source_column": source,
                    "canonical_column": canonical,
                    "status": "matched",
                    "requirement": "required" if canonical in required else "optional",
                }
            )
        for canonical in self.missing_required_columns:
            rows.append(
                {
                    "source_column": "",
                    "canonical_column": canonical,
                    "status": "missing",
                    "requirement": "required",
                }
            )
        for canonical, sources in self.ambiguous_matches.items():
            rows.append(
                {
                    "source_column": ", ".join(sources),
                    "canonical_column": canonical,
                    "status": "ambiguous",
                    "requirement": "required" if canonical in required else "optional",
                }
            )
        for source in self.unknown_source_columns:
            rows.append(
                {
                    "source_column": source,
                    "canonical_column": "",
                    "status": "unknown",
                    "requirement": "",
                }
            )
        return rows


def normalize_column_name(column_name: str) -> str:
    """Normalize casing, whitespace, hyphens, and repeated underscores."""
    normalized = _SPACES_AND_HYPHENS.sub("_", column_name.strip().lower())
    return _DUPLICATE_UNDERSCORES.sub("_", normalized)


def load_column_aliases(
    aliases_path: str | Path | None = None,
) -> dict[DatasetType, dict[str, tuple[str, ...]]]:
    """Load and validate dataset-specific aliases from YAML configuration."""
    path = Path(aliases_path) if aliases_path is not None else _DEFAULT_ALIASES_PATH
    try:
        with path.open(encoding="utf-8") as aliases_file:
            loaded = yaml.safe_load(aliases_file)
    except OSError as error:
        raise ConfigurationError(
            f"Could not read the column-alias configuration file '{path}'.",
            technical_detail=str(error),
        ) from error
    except yaml.YAMLError as error:
        raise ConfigurationError(
            f"The column-alias configuration file '{path}' is not valid YAML.",
            technical_detail=str(error),
        ) from error

    if not isinstance(loaded, dict):
        raise ConfigurationError(
            "The column-alias configuration must contain dataset mappings.",
            technical_detail=f"Loaded YAML root type: {type(loaded).__name__}",
        )

    parsed: dict[DatasetType, dict[str, tuple[str, ...]]] = {}
    for dataset_name, raw_aliases in loaded.items():
        if not isinstance(dataset_name, str) or not isinstance(raw_aliases, dict):
            raise ConfigurationError("The column-alias configuration has an invalid structure.")
        try:
            dataset_type = DatasetType(dataset_name)
        except ValueError as error:
            raise ConfigurationError(
                f"The column aliases contain an unsupported dataset '{dataset_name}'."
            ) from error
        schema = get_dataset_schema(dataset_type)
        dataset_aliases: dict[str, tuple[str, ...]] = {}
        for canonical, aliases in raw_aliases.items():
            if not isinstance(canonical, str) or canonical not in schema.all_columns:
                raise ConfigurationError(
                    f"The aliases for '{dataset_name}' contain an unknown field '{canonical}'."
                )
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) for alias in aliases
            ):
                raise ConfigurationError(
                    f"Aliases for '{dataset_name}.{canonical}' must be a list of column names."
                )
            dataset_aliases[canonical] = tuple(aliases)
        parsed[dataset_type] = dataset_aliases
    return parsed


def _resolve_schema(dataset: DatasetSchema | DatasetType | str) -> DatasetSchema:
    """Resolve a schema object or supported dataset identifier."""
    if isinstance(dataset, DatasetSchema):
        return dataset
    return get_dataset_schema(dataset)


def _validate_manual_overrides(
    source_columns: Sequence[str],
    schema: DatasetSchema,
    manual_overrides: Mapping[str, str],
) -> None:
    """Reject override keys or targets that cannot participate in mapping."""
    missing_sources = [source for source in manual_overrides if source not in source_columns]
    unknown_targets = [
        target for target in manual_overrides.values() if target not in schema.all_columns
    ]
    if missing_sources or unknown_targets:
        detail = f"Missing sources: {missing_sources}; unknown targets: {unknown_targets}"
        raise DataValidationError(
            "The manual column mapping contains unknown source or target columns.",
            technical_detail=detail,
        )


def map_columns(
    source_columns: Sequence[str],
    dataset: DatasetSchema | DatasetType | str,
    *,
    manual_overrides: Mapping[str, str] | None = None,
    aliases: AliasMapping | None = None,
    aliases_path: str | Path | None = None,
) -> ColumnMappingResult:
    """Map source columns to a schema without silently resolving ambiguities."""
    schema = _resolve_schema(dataset)
    overrides = dict(manual_overrides or {})
    _validate_manual_overrides(source_columns, schema, overrides)

    if aliases is None:
        aliases = load_column_aliases(aliases_path).get(schema.dataset_type, {})
    normalized_columns = {source: normalize_column_name(source) for source in source_columns}
    alias_tokens = {
        canonical: {
            normalize_column_name(canonical),
            *(normalize_column_name(alias) for alias in aliases.get(canonical, ())),
        }
        for canonical in schema.all_columns
    }

    manual_by_target: defaultdict[str, list[str]] = defaultdict(list)
    for source, target in overrides.items():
        manual_by_target[target].append(source)

    automatic_candidates: dict[str, list[str]] = {
        canonical: [
            source
            for source, normalized in normalized_columns.items()
            if source not in overrides and normalized in tokens
        ]
        for canonical, tokens in alias_tokens.items()
    }
    candidate_targets_by_source: defaultdict[str, list[str]] = defaultdict(list)
    for canonical, candidates in automatic_candidates.items():
        for source in candidates:
            candidate_targets_by_source[source].append(canonical)
    cross_target_sources = {
        source for source, targets in candidate_targets_by_source.items() if len(targets) > 1
    }

    matched: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, ...]] = {}
    ambiguous_sources: set[str] = set()
    for canonical in schema.all_columns:
        manual_candidates = manual_by_target.get(canonical, [])
        if len(manual_candidates) == 1:
            matched[canonical] = manual_candidates[0]
            continue
        if len(manual_candidates) > 1:
            ambiguous[canonical] = tuple(manual_candidates)
            ambiguous_sources.update(manual_candidates)
            continue

        candidates = automatic_candidates[canonical]
        if any(source in cross_target_sources for source in candidates):
            candidates = [source for source in candidates if source in cross_target_sources]
            ambiguous[canonical] = tuple(candidates)
            ambiguous_sources.update(candidates)
        elif len(candidates) == 1:
            matched[canonical] = candidates[0]
        elif len(candidates) > 1:
            ambiguous[canonical] = tuple(candidates)
            ambiguous_sources.update(candidates)

    matched_sources = set(matched.values())
    unknown = tuple(
        source
        for source in source_columns
        if source not in matched_sources and source not in ambiguous_sources
    )
    matched_required = {
        canonical: matched[canonical]
        for canonical in schema.required_columns
        if canonical in matched
    }
    matched_optional = {
        canonical: matched[canonical]
        for canonical in schema.optional_columns
        if canonical in matched
    }
    missing_required = tuple(
        canonical for canonical in schema.required_columns if canonical not in matched_required
    )

    return ColumnMappingResult(
        dataset_type=schema.dataset_type,
        normalized_columns=normalized_columns,
        matched_required_columns=matched_required,
        missing_required_columns=missing_required,
        matched_optional_columns=matched_optional,
        unknown_source_columns=unknown,
        ambiguous_matches=ambiguous,
    )


map_dataset_columns = map_columns
