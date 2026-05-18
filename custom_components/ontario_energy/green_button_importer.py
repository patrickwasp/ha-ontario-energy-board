"""Import parsed ESPI readings into Home Assistant's long-term statistics.

External statistics live alongside entity-backed statistics in HA's recorder.
Their ``statistic_id`` is of the form ``<source>:<key>`` (where ``<source>``
is our integration domain). Once imported they show up in the Energy Dashboard
as if they came from a normal sensor — but they're stored as cumulative
``sum`` snapshots rather than as state history.

We compute a running cumulative sum across the parsed intervals (the recorder
expects monotonically-increasing ``sum`` values; the Energy Dashboard takes
deltas to render bar charts).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import (
    CONF_DISTRIBUTOR,
    CONF_UTILITY,
    DOMAIN,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
)
from .green_button_parser import (
    COMMODITY_ELECTRICITY,
    COMMODITY_NATURAL_GAS,
    UsagePoint,
    parse_espi,
)
from .parser import OEBError, OEBSchemaError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GreenButtonImportResult:
    """Summary returned after importing one ESPI file."""

    statistic_id: str
    unit: str
    intervals_imported: int
    total: Decimal
    first_start: str
    last_start: str


def _statistic_id(entry: ConfigEntry, commodity: int) -> str:
    """Build the external statistic_id for a (config entry, commodity) pair.

    Format: ``ontario_energy:gb_<entry_id>_<elec|gas>_consumption``.
    """
    suffix = "elec" if commodity == COMMODITY_ELECTRICITY else "gas"
    return f"{DOMAIN}:gb_{entry.entry_id}_{suffix}_consumption"


def _expected_commodity(entry: ConfigEntry) -> int:
    """Return the commodity the entry's utility type expects."""
    utility = entry.data.get(CONF_UTILITY, UTILITY_ELECTRICITY)
    if utility == UTILITY_GAS:
        return COMMODITY_NATURAL_GAS
    if utility == UTILITY_ELECTRICITY:
        return COMMODITY_ELECTRICITY
    raise OEBSchemaError(f"Unknown utility type on config entry: {utility!r}")


def _statistic_unit(commodity: int) -> str:
    if commodity == COMMODITY_ELECTRICITY:
        return UnitOfEnergy.KILO_WATT_HOUR
    return UnitOfVolume.CUBIC_METERS


def _unit_class_for(commodity: int) -> str:
    if commodity == COMMODITY_ELECTRICITY:
        return EnergyConverter.UNIT_CLASS
    return VolumeConverter.UNIT_CLASS


def _name_for(entry: ConfigEntry, commodity: int) -> str:
    label = "Electricity" if commodity == COMMODITY_ELECTRICITY else "Gas"
    distributor = entry.data.get(CONF_DISTRIBUTOR, "Unknown")
    return f"Ontario Energy Board - {distributor} - Green Button {label} consumption"


def _build_statistics(
    usage_point: UsagePoint,
) -> list[StatisticData]:
    """Compute cumulative-sum statistics for HA's recorder.

    Each ESPI interval becomes one ``StatisticData`` whose ``start`` is the
    interval start (UTC) and whose ``sum`` is the cumulative total of all
    prior intervals plus this one. HA's recorder computes per-period deltas
    from the difference between successive ``sum`` values.
    """
    out: list[StatisticData] = []
    running = Decimal(0)
    for reading in usage_point.readings:
        running += reading.value
        out.append(
            {
                "start": reading.start,
                "sum": float(running),
                "state": float(reading.value),
            }
        )
    return out


async def async_import_file(
    hass: HomeAssistant,
    entry: ConfigEntry,
    file_path: Path,
) -> GreenButtonImportResult:
    """Parse ``file_path`` and add the readings to HA's recorder.

    Raises:
        OEBError: any parser error from the underlying ESPI parser.
        FileNotFoundError: the file doesn't exist.
        ValueError: the ESPI file's commodity doesn't match the entry's
            utility (e.g., gas ESPI imported against an electricity entry).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"ESPI file not found: {path}")

    xml_bytes = await hass.async_add_executor_job(path.read_bytes)
    usage_points = await hass.async_add_executor_job(parse_espi, xml_bytes)

    expected = _expected_commodity(entry)
    matching = [up for up in usage_points if up.reading_type.commodity == expected]
    if not matching:
        raise ValueError(
            f"ESPI file {path.name} has no usage points matching the entry's "
            f"utility (expected commodity={expected})"
        )
    if len(matching) > 1:
        _LOGGER.info(
            "ESPI file %s has %d matching usage points; merging readings",
            path.name,
            len(matching),
        )

    # Merge all matching usage points' readings into one stream, sorted.
    all_readings = sorted(
        (r for up in matching for r in up.readings), key=lambda r: r.start
    )
    if not all_readings:
        raise OEBSchemaError(
            f"ESPI file {path.name} has no readings for the entry's utility"
        )

    # Build a single synthetic UsagePoint to feed the statistic builder.
    merged = UsagePoint(reading_type=matching[0].reading_type, readings=tuple(all_readings))

    statistic_id = _statistic_id(entry, expected)
    metadata: StatisticMetaData = {
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": _name_for(entry, expected),
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_class": _unit_class_for(expected),
        "unit_of_measurement": _statistic_unit(expected),
    }
    statistics = _build_statistics(merged)

    async_add_external_statistics(hass, metadata, statistics)

    total = Decimal(0)
    for r in merged.readings:
        total += r.value

    _LOGGER.info(
        "Imported %d Green Button readings (%s %s total) as %s",
        len(merged.readings),
        total,
        merged.normalized_unit,
        statistic_id,
    )
    return GreenButtonImportResult(
        statistic_id=statistic_id,
        unit=merged.normalized_unit,
        intervals_imported=len(merged.readings),
        total=total,
        first_start=merged.readings[0].start.isoformat(),
        last_start=merged.readings[-1].start.isoformat(),
    )


# Re-export common exceptions so callers can import everything from this module.
__all__ = [
    "GreenButtonImportResult",
    "OEBError",
    "async_import_file",
]
