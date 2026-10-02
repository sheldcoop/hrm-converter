"""Sanity checks on the converted values. They only report; values are never changed.

* order      - Min <= Mean <= Max for metric families such as ``Min_Stepheight`` /
               ``Mean_Stepheight`` / ``Max_Stepheight`` or ``Rz_Min`` / ``Rz_Mean`` / ``Rz_Max``
* negative   - any value below zero
* suspicious - a value many times larger or smaller than the median of the same feature
               and metric in its workbook (a typing or unit mistake)

Metric families are recognised from the ``Min`` / ``Mean`` / ``Max`` part of the metric
name, so new metrics are covered without listing them.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict

from hrm_converter.config import Config
from hrm_converter.models import Candidate, LongRecord
from hrm_converter.validation import IssueCollector

_PREFIX = re.compile(r"^(min|mean|max)[ _](.+)$", re.IGNORECASE)
_SUFFIX = re.compile(r"^(.+)[ _](min|mean|max)$", re.IGNORECASE)
_TOLERANCE = 1e-9
_MIN_GROUP = 3


def _family(metric: str) -> tuple[str, str] | None:
    """('Stepheight', 'min') for 'Min_Stepheight' or 'Stepheight_Min'; None otherwise."""
    match = _PREFIX.match(metric)
    if match:
        return match.group(2), match.group(1).lower()
    match = _SUFFIX.match(metric)
    if match:
        return match.group(1), match.group(2).lower()
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def check_values(
    records: list[LongRecord], candidate: Candidate, config: Config, issues: IssueCollector
) -> None:
    """Report implausible values among the records of one workbook."""
    quality = config.quality
    details = {"source_file": candidate.path.name, "relative_path": candidate.relative_path}
    families: dict[tuple[object, str, int, str], dict[str, float]] = defaultdict(dict)
    groups: dict[tuple[str, int, str], list[tuple[object, float]]] = defaultdict(list)

    for record in records:
        number = _number(record.value)
        if number is None:
            continue
        where = f"{record.feature_type} {record.feature_number}, unit {record.unit}"
        if quality.negative_check and number < 0:
            issues.warning(
                "negative_value",
                f"{where}: {record.metric} is negative ({number:g}).",
                field=record.metric,
                **details,
            )
        family = _family(record.metric)
        if family is not None:
            key = (record.unit, record.feature_type, record.feature_number, family[0])
            families[key].setdefault(family[1], number)
        groups[(record.feature_type, record.feature_number, record.metric)].append(
            (record.unit, number)
        )

    if quality.order_check:
        for (unit, feature_type, feature_number, name), found in families.items():
            low, mid, high = found.get("min"), found.get("mean"), found.get("max")
            wrong = []
            if low is not None and mid is not None and mid < low - _TOLERANCE:
                wrong.append(f"Mean ({mid:g}) < Min ({low:g})")
            if mid is not None and high is not None and mid > high + _TOLERANCE:
                wrong.append(f"Mean ({mid:g}) > Max ({high:g})")
            if low is not None and high is not None and low > high + _TOLERANCE:
                wrong.append(f"Min ({low:g}) > Max ({high:g})")
            if wrong:
                issues.warning(
                    "value_order",
                    f"{feature_type} {feature_number}, unit {unit}: {name} {'; '.join(wrong)}.",
                    field=name,
                    **details,
                )

    factor = quality.outlier_factor
    if factor is not None:
        for (feature_type, feature_number, metric), values in groups.items():
            if len(values) < _MIN_GROUP:
                continue
            median = abs(statistics.median(number for _, number in values))
            if median == 0:
                continue
            for unit, number in values:
                size = abs(number)
                if size == 0:
                    continue  # a true zero (no dimple, no bump) is a normal reading
                if size > median * factor or size < median / factor:
                    issues.warning(
                        "suspicious_value",
                        f"{feature_type} {feature_number}, unit {unit}: {metric} = {number:g} is "
                        f"more than {factor:g} times away from the median of this block "
                        f"({median:g}). Possible typing or unit mistake.",
                        field=metric,
                        **details,
                    )
