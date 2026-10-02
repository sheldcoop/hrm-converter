"""Dynamic detection of features, metrics, units of measurement and unit ids.

Rules (all name lists come from the configuration, none are hardcoded here):

* Feature: the block label in column B, e.g. ``SR Pad 2``. A trailing number
  is the Feature_Number, the text before it is the Feature_Type. Known labels
  are mapped through ``features.aliases``; unknown labels are kept as written
  and reported as newly discovered feature types.
* Metric: every header cell of the block. Names are kept after whitespace
  normalisation unless ``metrics.aliases`` holds an explicit mapping. Feature
  types listed in ``metrics.positional`` take their metric names from the
  column position instead of the (unreliable, operator-typed) header text.
* Unit of measurement: ``units.feature_rules`` (whole feature type, optional
  scale factor) first, then ``units.metric_units``; otherwise blank.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hrm_converter.config import Config, normalize_key
from hrm_converter.hierarchy import LOCATION_COUPON

_TRAILING_NUMBER = re.compile(r"^(?P<base>.*?)[\s\-_]*(?P<number>\d+)$")
_FIRST_NUMBER = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Feature:
    feature_type: str
    feature_number: int
    known: bool
    numbered: bool


@dataclass(frozen=True)
class MetricColumn:
    """One value column of a block (index counts from column C = 0)."""

    index: int
    metric: str
    source_header: str | None
    unit: str
    scale: float


@dataclass(frozen=True)
class MetricSchema:
    columns: tuple[MetricColumn, ...]
    positional_mismatch: bool
    duplicates: tuple[str, ...]
    without_unit: tuple[str, ...]
    discovered: tuple[str, ...]


def split_label(label: str) -> tuple[str, int | None]:
    """'Pad Pos 3' -> ('Pad Pos', 3); 'roughness' -> ('roughness', None)."""
    text = " ".join(label.split())
    match = _TRAILING_NUMBER.match(text)
    if match and match.group("base").strip(" -_"):
        return match.group("base").strip(" -_"), int(match.group("number"))
    return text, None


def detect_feature(label: str, config: Config) -> Feature:
    base, number = split_label(label)
    alias = config.features.aliases.get(normalize_key(base))
    return Feature(
        feature_type=alias if alias is not None else base,
        feature_number=number if number is not None else config.features.default_feature_number,
        known=alias is not None,
        numbered=number is not None,
    )


def parse_unit(unit_label: str, location: str) -> int | str | None:
    """'Unit 7' -> 7 on a Unit folder, 'C7' on a Coupon folder."""
    match = _FIRST_NUMBER.search(unit_label)
    if not match:
        return None
    number = int(match.group(1))
    return f"C{number}" if location == LOCATION_COUPON else number


def _unit_for(metric: str, feature_type: str, config: Config) -> tuple[str, float]:
    rule = config.units.feature_rules.get(normalize_key(feature_type))
    if rule is not None:
        return rule.unit, rule.scale
    return config.units.metric_units.get(normalize_key(metric), ""), 1.0


def detect_metrics(
    header: tuple[str | None, ...], feature_type: str, config: Config
) -> MetricSchema:
    """Turn the header row of a block into metric columns."""
    positional = config.metrics.positional.get(normalize_key(feature_type), ())
    named: list[tuple[int, str, str | None]] = []
    mismatch = False
    discovered: list[str] = []

    for index in range(max(len(header), len(positional))):
        source = header[index] if index < len(header) else None
        source = " ".join(source.split()) or None if source is not None else None
        if index < len(positional):
            metric = positional[index]
            if source is None or normalize_key(source) != normalize_key(metric):
                mismatch = True
        elif source is None:
            continue
        else:
            alias = config.metrics.aliases.get(normalize_key(source))
            metric = alias if alias is not None else source
            if alias is None:
                discovered.append(source)
        named.append((index, metric, source))

    columns: list[MetricColumn] = []
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    without_unit: list[str] = []
    for index, base_metric, source in named:
        count = seen.get(base_metric, 0) + 1
        seen[base_metric] = count
        metric = base_metric
        if count > 1:
            # Never drop or merge a repeated column: keep it under a numbered name.
            duplicates.append(base_metric)
            metric = f"{base_metric} ({count})"
        unit, scale = _unit_for(base_metric, feature_type, config)
        if not unit:
            without_unit.append(metric)
        columns.append(MetricColumn(index, metric, source, unit, scale))

    return MetricSchema(
        columns=tuple(columns),
        positional_mismatch=mismatch,
        duplicates=tuple(dict.fromkeys(duplicates)),
        without_unit=tuple(without_unit),
        discovered=tuple(discovered),
    )
