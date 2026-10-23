from dataclasses import dataclass

from monitoring.services.simulated_iot import (
    SimulatedIoTError,
    generate_simulated_iot_point,
)
from monitoring.services.simulated_iot_storage import (
    SimulatedIoTStorageError,
    store_simulated_iot_point,
)


class SimulatedIoTRefreshError(RuntimeError):
    """Raised when a simulated IoT refresh cannot complete safely."""


@dataclass(frozen=True)
class SimulatedIoTRefreshSummary:
    county_code: str
    county_name: str
    recorded_at: object
    calibration_observation_count: int
    calibration_reference_date: object
    device_created: bool
    reading_created: bool
    reading_updated: bool
    device_id: str
    message_id: str
    dry_run: bool


def refresh_simulated_iot_county(
    county,
    *,
    recorded_at,
    seed=None,
    dry_run=False,
):
    try:
        point = generate_simulated_iot_point(
            county,
            recorded_at=recorded_at,
            seed=seed,
        )
    except SimulatedIoTError as exc:
        raise SimulatedIoTRefreshError(
            "Simulated IoT generation failed for "
            f"{county.name}: {exc}"
        ) from exc

    try:
        storage = store_simulated_iot_point(
            county,
            point,
            dry_run=dry_run,
        )
    except SimulatedIoTStorageError as exc:
        raise SimulatedIoTRefreshError(
            "Simulated IoT storage failed for "
            f"{county.name}: {exc}"
        ) from exc

    return SimulatedIoTRefreshSummary(
        county_code=county.code,
        county_name=county.name,
        recorded_at=recorded_at,
        calibration_observation_count=(
            point.calibration_observation_count
        ),
        calibration_reference_date=(
            point.calibration_reference_date
        ),
        device_created=storage.device_created,
        reading_created=storage.reading_created,
        reading_updated=storage.reading_updated,
        device_id=storage.device_id,
        message_id=storage.message_id,
        dry_run=dry_run,
    )