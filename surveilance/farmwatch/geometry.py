"""Polygon and distance helpers."""
import math
from typing import Sequence, Tuple

Point = Tuple[float, float]


def point_in_polygon(pt: Point, poly: Sequence[Sequence[float]]) -> bool:
    """Ray-casting test. An empty polygon means 'everywhere'."""
    if not poly:
        return True
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
