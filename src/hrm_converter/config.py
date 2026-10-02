"""Typed configuration: defaults, YAML loading and validation.

Every domain rule that could change (folder naming patterns, feature aliases,
metric names, units) lives here so the parsing code stays free of hardcoded
process, feature and metric names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hrm_converter.models import ConfigError

DEFAULTS: dict[str, Any] = {
    "input": {
        "start_path": None,
        "accepted_extensions": [".xlsx"],
        "ignore_filename_prefixes": ["~$"],
        "filename_patterns": ["*_Summary.xlsx"],
    },
    "scope": {
        "part_numbers": "all",
        "lot_numbers": "all",
        "buildups": "all",
        "machine_folder": "HRM",
    },
    "hierarchy": {
        "buildup_pattern": r"^BU[\s\-_]*0*(?P<number>\d+)$",
        "buildup_format": "BU-{number:02d}",
        "require_buildup_pattern": True,
        "process_pattern": r"^(?P<name>.+?)[\s_\-]+HRM[\s_\-]*\d.*$",
        "panel_pattern": r"^Panel[\s\-_]*0*(?P<number>\d+)$",
        "coupon_keyword": "coupon",
        "sides": {"front": "Front", "back": "Back"},
    },
    "metadata": {
        "default_lot_name": "",
        "lot_names": {},
    },
    "cross_check": {
        "sheet_part_number_pattern": r"^[A-Za-z0-9]+_(?P<part_number>.+?)_BU[\s\-]?\d+",
    },
    "processing": {
        "strict_metadata_conflicts": True,
        "multiple_files_policy": "error_and_skip",
        "skip_blank_metric_values": True,
        "preserve_zero_values": True,
        "text_value_policy": "skip_and_report",
        "coerce_numeric_text": True,
    },
    "features": {
        "aliases": {
            "pad": "Pad",
            "pad pos": "Pad",
            "sr pad": "SR Pad",
            "sr pad pos": "SR Pad",
            "landing pad": "Landing_Pad",
            "landing pad pos": "Landing_Pad",
            "trace": "Trace",
            "trace pos": "Trace",
            "via": "Via",
            "via pos": "Via",
            "roughness": "Roughness",
        },
        "default_feature_number": 1,
    },
    "metrics": {
        "aliases": {
            "max stepheight": "Max_Stepheight",
            "min stepheight": "Min_Stepheight",
            "mean stepheight": "Mean_Stepheight",
            "radius": "Radius",
            "diameter": "Diameter",
            "outer radius": "Outer_Radius",
            "inner radius": "Inner_Radius",
            "dimple": "Dimple",
            "bump": "Bump",
            "width": "Width",
            "line": "Width",
            "space": "Space",
        },
        "positional": {
            "Roughness": [
                "Rz_Mean",
                "Rz_Std_dev",
                "Rz_Min",
                "Rz_Max",
                "Ra_Mean",
                "Ra_Std_dev",
                "Ra_Min",
                "Ra_Max",
            ],
        },
    },
    "units": {
        "metric_units": {
            "Max_Stepheight": "µm",
            "Min_Stepheight": "µm",
            "Mean_Stepheight": "µm",
            "Radius": "µm",
            "Diameter": "µm",
            "Outer_Radius": "µm",
            "Inner_Radius": "µm",
            "Dimple": "µm",
            "Bump": "µm",
            "Width": "µm",
            "Space": "µm",
        },
        "feature_rules": {
            "Roughness": {"unit": "nm", "scale": 1000},
        },
    },
    "output": {
        "directory": "output",
        "filename": "hrm_long_format.xlsx",
        "sheet_name": "Long",
    },
    "wide": {
        "filename": "hrm_wide_format.xlsx",
        "reference_path": None,
        "reference_sheet": "Limits",
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
    },
}

MULTIPLE_FILES_POLICIES = ("error_and_skip", "newest")
TEXT_VALUE_POLICIES = ("skip_and_report", "keep_as_text")


def normalize_key(text: object) -> str:
    """Lower case, underscores/hyphens to spaces, single spaces, stripped."""
    return re.sub(r"[\s_\-]+", " ", str(text)).strip().lower()


@dataclass(frozen=True)
class InputConfig:
    start_path: Path | None
    accepted_extensions: tuple[str, ...]
    ignore_filename_prefixes: tuple[str, ...]
    filename_patterns: tuple[str, ...]


@dataclass(frozen=True)
class ScopeConfig:
    """Filters that narrow the scope below the selected folder (None = all)."""

    part_numbers: frozenset[str] | None
    lot_numbers: frozenset[str] | None
    buildups: frozenset[str] | None
    machine_folder: str


@dataclass(frozen=True)
class HierarchyConfig:
    buildup_pattern: re.Pattern[str]
    buildup_format: str
    require_buildup_pattern: bool
    process_pattern: re.Pattern[str]
    panel_pattern: re.Pattern[str]
    coupon_keyword: str
    sides: dict[str, str]


@dataclass(frozen=True)
class MetadataConfig:
    default_lot_name: str
    lot_names: dict[str, str]


@dataclass(frozen=True)
class CrossCheckConfig:
    sheet_part_number_pattern: re.Pattern[str] | None


@dataclass(frozen=True)
class ProcessingConfig:
    strict_metadata_conflicts: bool
    multiple_files_policy: str
    skip_blank_metric_values: bool
    preserve_zero_values: bool
    text_value_policy: str
    coerce_numeric_text: bool


@dataclass(frozen=True)
class FeatureConfig:
    aliases: dict[str, str]
    default_feature_number: int


@dataclass(frozen=True)
class MetricConfig:
    aliases: dict[str, str]
    positional: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class UnitRule:
    unit: str
    scale: float


@dataclass(frozen=True)
class UnitConfig:
    metric_units: dict[str, str]
    feature_rules: dict[str, UnitRule]


@dataclass(frozen=True)
class OutputConfig:
    directory: Path
    filename: str
    sheet_name: str


@dataclass(frozen=True)
class WideConfig:
    filename: str
    reference_path: Path | None
    reference_sheet: str


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    directory: Path


@dataclass(frozen=True)
class Config:
    input: InputConfig
    scope: ScopeConfig
    hierarchy: HierarchyConfig
    metadata: MetadataConfig
    cross_check: CrossCheckConfig
    processing: ProcessingConfig
    features: FeatureConfig
    metrics: MetricConfig
    units: UnitConfig
    output: OutputConfig
    wide: WideConfig
    logging: LoggingConfig


def _merge(defaults: dict[str, Any], user: dict[str, Any], where: str) -> dict[str, Any]:
    """Overlay user settings on the defaults; unknown keys are rejected."""
    merged = dict(defaults)
    for key, value in user.items():
        if key not in defaults:
            raise ConfigError(
                f"Unknown setting '{where}{key}'. Allowed: {', '.join(sorted(defaults))}."
            )
        default = defaults[key]
        # Mapping-style settings (aliases, units, lot names) take any keys.
        open_mapping = where.count(".") >= 1 and isinstance(default, dict)
        if isinstance(default, dict) and isinstance(value, dict) and not open_mapping:
            merged[key] = _merge(default, value, f"{where}{key}.")
        elif isinstance(default, dict) and value is None:
            merged[key] = {}
        elif isinstance(default, dict) and not isinstance(value, dict):
            raise ConfigError(f"Setting '{where}{key}' must be a mapping (key: value pairs).")
        else:
            merged[key] = value
    return merged


def _compile(pattern: object, name: str, group: str | None = None) -> re.Pattern[str]:
    try:
        compiled = re.compile(str(pattern), re.IGNORECASE)
    except re.error as exc:
        raise ConfigError(f"Setting '{name}' is not a valid regular expression: {exc}") from exc
    if group and group not in compiled.groupindex:
        raise ConfigError(f"Setting '{name}' must contain a named group '(?P<{group}>...)'.")
    return compiled


def _filter(value: object, name: str) -> frozenset[str] | None:
    if value is None or (isinstance(value, str) and value.strip().lower() == "all"):
        return None
    items = value if isinstance(value, list) else [value]
    if not items:
        raise ConfigError(f"Setting '{name}' is an empty list; use 'all' or list at least one.")
    return frozenset(normalize_key(item) for item in items)


def _choice(value: object, allowed: tuple[str, ...], name: str) -> str:
    text = str(value).strip().lower()
    if text not in allowed:
        raise ConfigError(f"Setting '{name}' must be one of {', '.join(allowed)} (got '{value}').")
    return text


def _unit_rules(raw: dict[str, Any]) -> dict[str, UnitRule]:
    rules: dict[str, UnitRule] = {}
    for feature, rule in raw.items():
        if not isinstance(rule, dict) or "unit" not in rule:
            raise ConfigError(f"units.feature_rules.{feature} needs at least a 'unit' entry.")
        try:
            scale = float(rule.get("scale", 1))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"units.feature_rules.{feature}.scale must be a number.") from exc
        rules[normalize_key(feature)] = UnitRule(unit=str(rule["unit"]), scale=scale)
    return rules


def build_config(user: dict[str, Any] | None = None) -> Config:
    """Build a validated Config from optional user settings laid over the defaults."""
    raw = _merge(DEFAULTS, user or {}, "")
    inp, scope, hier = raw["input"], raw["scope"], raw["hierarchy"]
    proc, out, log = raw["processing"], raw["output"], raw["logging"]

    part_pattern = raw["cross_check"]["sheet_part_number_pattern"]
    machine = str(scope["machine_folder"]).strip()
    if not machine:
        raise ConfigError("Setting 'scope.machine_folder' must not be empty.")

    return Config(
        input=InputConfig(
            start_path=Path(inp["start_path"]) if inp["start_path"] else None,
            accepted_extensions=tuple(str(e).lower() for e in inp["accepted_extensions"]),
            ignore_filename_prefixes=tuple(str(p) for p in inp["ignore_filename_prefixes"]),
            filename_patterns=tuple(str(p) for p in inp["filename_patterns"] or ["*"]),
        ),
        scope=ScopeConfig(
            part_numbers=_filter(scope["part_numbers"], "scope.part_numbers"),
            lot_numbers=_filter(scope["lot_numbers"], "scope.lot_numbers"),
            buildups=_filter(scope["buildups"], "scope.buildups"),
            machine_folder=machine,
        ),
        hierarchy=HierarchyConfig(
            buildup_pattern=_compile(hier["buildup_pattern"], "hierarchy.buildup_pattern"),
            buildup_format=str(hier["buildup_format"]),
            require_buildup_pattern=bool(hier["require_buildup_pattern"]),
            process_pattern=_compile(hier["process_pattern"], "hierarchy.process_pattern", "name"),
            panel_pattern=_compile(hier["panel_pattern"], "hierarchy.panel_pattern", "number"),
            coupon_keyword=normalize_key(hier["coupon_keyword"]),
            sides={normalize_key(k): str(v) for k, v in hier["sides"].items()},
        ),
        metadata=MetadataConfig(
            default_lot_name=str(raw["metadata"]["default_lot_name"] or ""),
            lot_names={str(k).strip(): str(v) for k, v in raw["metadata"]["lot_names"].items()},
        ),
        cross_check=CrossCheckConfig(
            sheet_part_number_pattern=(
                _compile(part_pattern, "cross_check.sheet_part_number_pattern", "part_number")
                if part_pattern
                else None
            ),
        ),
        processing=ProcessingConfig(
            strict_metadata_conflicts=bool(proc["strict_metadata_conflicts"]),
            multiple_files_policy=_choice(
                proc["multiple_files_policy"],
                MULTIPLE_FILES_POLICIES,
                "processing.multiple_files_policy",
            ),
            skip_blank_metric_values=bool(proc["skip_blank_metric_values"]),
            preserve_zero_values=bool(proc["preserve_zero_values"]),
            text_value_policy=_choice(
                proc["text_value_policy"], TEXT_VALUE_POLICIES, "processing.text_value_policy"
            ),
            coerce_numeric_text=bool(proc["coerce_numeric_text"]),
        ),
        features=FeatureConfig(
            aliases={normalize_key(k): str(v) for k, v in raw["features"]["aliases"].items()},
            default_feature_number=int(raw["features"]["default_feature_number"]),
        ),
        metrics=MetricConfig(
            aliases={normalize_key(k): str(v) for k, v in raw["metrics"]["aliases"].items()},
            positional={
                normalize_key(k): tuple(str(m) for m in v)
                for k, v in raw["metrics"]["positional"].items()
            },
        ),
        units=UnitConfig(
            metric_units={
                normalize_key(k): str(v) for k, v in raw["units"]["metric_units"].items()
            },
            feature_rules=_unit_rules(raw["units"]["feature_rules"]),
        ),
        output=OutputConfig(
            directory=Path(str(out["directory"])),
            filename=str(out["filename"]),
            sheet_name=str(out["sheet_name"]),
        ),
        wide=WideConfig(
            filename=str(raw["wide"]["filename"]),
            reference_path=(
                Path(str(raw["wide"]["reference_path"])) if raw["wide"]["reference_path"] else None
            ),
            reference_sheet=str(raw["wide"]["reference_sheet"]),
        ),
        logging=LoggingConfig(
            level=str(log["level"]).upper(), directory=Path(str(log["directory"]))
        ),
    )


def load_config(path: Path | None) -> Config:
    """Load a YAML config file; ``None`` returns the built-in defaults."""
    if path is None:
        return build_config()
    try:
        with path.open(encoding="utf-8") as handle:
            user = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"Config file cannot be read: {path} ({exc})") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {path} ({exc})") from exc
    if user is not None and not isinstance(user, dict):
        raise ConfigError(f"Config file must contain a mapping of settings: {path}")
    return build_config(user)
