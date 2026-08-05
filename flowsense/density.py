"""Per-lane traffic density classification (klasifikasi kepadatan)."""

DENSITY_LEVELS = ("lancar", "sedang", "padat")


def density_from_count(count: int, thresholds: tuple[int, int] = (3, 8)) -> str:
    """Map a vehicle count to a density label."""
    low, high = thresholds
    if count <= low:
        return "lancar"
    if count <= high:
        return "sedang"
    return "padat"


def classify_density(per_lane: dict, thresholds: tuple[int, int] = (3, 8)) -> dict:
    """Classify every lane's vehicle count into a density label."""
    return {lane: density_from_count(count, thresholds) for lane, count in per_lane.items()}
