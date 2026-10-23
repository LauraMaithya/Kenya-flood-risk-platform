import json
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

class CountyGeometryError(RuntimeError):
    """Raised when county boundary data cannot be safely processed."""


COUNTY_NAME_ALIASES = {
    "tharaka": "tharakanithi",
}


def normalize_county_name(value):
    normalized = re.sub(
        r"[^a-z0-9]",
        "",
        value.casefold(),
    )

    return COUNTY_NAME_ALIASES.get(
        normalized,
        normalized,
    )


def default_boundary_path():
    return (
        settings.BASE_DIR
        / "monitoring"
        / "static"
        / "monitoring"
        / "data"
        / "kenya_adm1.geojson"
    )


def _ring_area(ring):
    area = 0.0

    for index, point in enumerate(ring):
        next_point = ring[(index + 1) % len(ring)]
        area += (
            float(point[0]) * float(next_point[1])
            - float(next_point[0]) * float(point[1])
        )

    return area / 2.0


def _ring_centroid(ring):
    if len(ring) < 3:
        raise CountyGeometryError(
            "A county boundary ring requires at least three points."
        )

    area = _ring_area(ring)

    if abs(area) < 1e-12:
        longitude = sum(
            float(point[0])
            for point in ring
        ) / len(ring)
        latitude = sum(
            float(point[1])
            for point in ring
        ) / len(ring)

        return longitude, latitude

    longitude_total = 0.0
    latitude_total = 0.0

    for index, point in enumerate(ring):
        next_point = ring[(index + 1) % len(ring)]
        cross_product = (
            float(point[0]) * float(next_point[1])
            - float(next_point[0]) * float(point[1])
        )
        longitude_total += (
            float(point[0]) + float(next_point[0])
        ) * cross_product
        latitude_total += (
            float(point[1]) + float(next_point[1])
        ) * cross_product

    scale = 1.0 / (6.0 * area)

    return (
        longitude_total * scale,
        latitude_total * scale,
    )


def _point_in_ring(point, ring):
    longitude, latitude = point
    inside = False
    previous_index = len(ring) - 1

    for index, current in enumerate(ring):
        previous = ring[previous_index]

        current_longitude = float(current[0])
        current_latitude = float(current[1])
        previous_longitude = float(previous[0])
        previous_latitude = float(previous[1])

        crosses_latitude = (
            current_latitude > latitude
        ) != (
            previous_latitude > latitude
        )

        if crosses_latitude:
            intersecting_longitude = (
                (
                    previous_longitude
                    - current_longitude
                )
                * (
                    latitude - current_latitude
                )
                / (
                    previous_latitude
                    - current_latitude
                )
                + current_longitude
            )

            if longitude < intersecting_longitude:
                inside = not inside

        previous_index = index

    return inside


def _point_in_polygon(point, polygon):
    outer_ring = polygon[0]

    if not _point_in_ring(point, outer_ring):
        return False

    return not any(
        _point_in_ring(point, inner_ring)
        for inner_ring in polygon[1:]
    )


def _largest_polygon(geometry):
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if not coordinates:
        raise CountyGeometryError(
            "County geometry does not contain coordinates."
        )

    if geometry_type == "Polygon":
        return coordinates

    if geometry_type == "MultiPolygon":
        return max(
            coordinates,
            key=lambda polygon: abs(
                _ring_area(polygon[0])
            ),
        )

    raise CountyGeometryError(
        f"Unsupported county geometry type: {geometry_type}"
    )


def _fallback_interior_point(polygon):
    outer_ring = polygon[0]
    longitudes = [
        float(point[0])
        for point in outer_ring
    ]
    latitudes = [
        float(point[1])
        for point in outer_ring
    ]

    minimum_longitude = min(longitudes)
    maximum_longitude = max(longitudes)
    minimum_latitude = min(latitudes)
    maximum_latitude = max(latitudes)

    grid_size = 25
    candidates = []

    for longitude_index in range(1, grid_size):
        longitude = (
            minimum_longitude
            + (
                maximum_longitude - minimum_longitude
            )
            * longitude_index
            / grid_size
        )

        for latitude_index in range(1, grid_size):
            latitude = (
                minimum_latitude
                + (
                    maximum_latitude - minimum_latitude
                )
                * latitude_index
                / grid_size
            )
            point = (longitude, latitude)

            if _point_in_polygon(point, polygon):
                candidates.append(point)

    if not candidates:
        raise CountyGeometryError(
            "No interior point could be derived for a county."
        )

    centre = (
        (
            minimum_longitude + maximum_longitude
        ) / 2.0,
        (
            minimum_latitude + maximum_latitude
        ) / 2.0,
    )

    return min(
        candidates,
        key=lambda point: (
            (point[0] - centre[0]) ** 2
            + (point[1] - centre[1]) ** 2
        ),
    )


def representative_point(geometry):
    polygon = _largest_polygon(geometry)
    centroid = _ring_centroid(polygon[0])

    if _point_in_polygon(centroid, polygon):
        return centroid

    return _fallback_interior_point(polygon)


@lru_cache(maxsize=4)
def load_county_points(boundary_path=None):
    path = Path(
        boundary_path
        if boundary_path is not None
        else default_boundary_path()
    )

    if not path.is_file():
        raise CountyGeometryError(
            f"County boundary file does not exist: {path}"
        )

    try:
        boundary_data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CountyGeometryError(
            f"County boundary file could not be read: {path}"
        ) from exc

    features = boundary_data.get("features")

    if not isinstance(features, list):
        raise CountyGeometryError(
            "County boundary file has no feature collection."
        )

    county_points = {}

    for feature in features:
        properties = feature.get("properties", {})
        county_name = properties.get("shapeName")
        geometry = feature.get("geometry")

        if not county_name or not geometry:
            raise CountyGeometryError(
                "A county boundary is missing its name or geometry."
            )

        county_key = normalize_county_name(
            county_name
        )

        if county_key in county_points:
            raise CountyGeometryError(
                f"Duplicate county boundary: {county_name}"
            )

        longitude, latitude = representative_point(
            geometry
        )

        county_points[county_key] = {
            "county_name": county_name,
            "latitude": latitude,
            "longitude": longitude,
            "geometry": geometry,
        }

    return county_points

def _interior_grid_points(polygon, grid_size=25):
    outer_ring = polygon[0]
    longitudes = [
        float(point[0])
        for point in outer_ring
    ]
    latitudes = [
        float(point[1])
        for point in outer_ring
    ]
    minimum_longitude = min(longitudes)
    maximum_longitude = max(longitudes)
    minimum_latitude = min(latitudes)
    maximum_latitude = max(latitudes)
    candidates = []

    for longitude_index in range(1, grid_size):
        longitude = (
            minimum_longitude
            + (
                maximum_longitude - minimum_longitude
            )
            * longitude_index
            / grid_size
        )

        for latitude_index in range(1, grid_size):
            latitude = (
                minimum_latitude
                + (
                    maximum_latitude - minimum_latitude
                )
                * latitude_index
                / grid_size
            )
            point = (longitude, latitude)

            if _point_in_polygon(point, polygon):
                candidates.append(point)

    return candidates


def sample_county_points(geometry, count=3):
    if count < 1:
        raise CountyGeometryError(
            "County sample-point count must be positive."
        )

    polygon = _largest_polygon(geometry)
    primary_point = representative_point(geometry)
    candidates = _interior_grid_points(polygon)

    if not candidates:
        return (primary_point,)

    selected = [primary_point]
    remaining = [
        point
        for point in candidates
        if point != primary_point
    ]

    while remaining and len(selected) < count:
        next_point = max(
            remaining,
            key=lambda point: min(
                (
                    (point[0] - chosen[0]) ** 2
                    + (point[1] - chosen[1]) ** 2
                )
                for chosen in selected
            ),
        )
        selected.append(next_point)
        remaining.remove(next_point)

    if len(selected) < count:
        raise CountyGeometryError(
            "The requested number of county sample points "
            "could not be derived."
        )

    return tuple(selected)


def load_county_sample_points(count=3):
    county_boundaries = load_county_points()

    return {
        county_key: {
            "county_name": county["county_name"],
            "points": sample_county_points(
                county["geometry"],
                count=count,
            ),
        }
        for county_key, county in county_boundaries.items()
    }