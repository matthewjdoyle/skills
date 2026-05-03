from __future__ import annotations

import csv
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT / "test_data"


def write_csv(path: Path, rows: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y", "sigma_y"])
        writer.writerows(rows.tolist())


def gaussian_peak_dataset(rng: np.random.Generator) -> np.ndarray:
    x = np.linspace(-4.0, 6.0, 121)
    sigma_y = np.full_like(x, 0.08)
    y_true = 4.2 * np.exp(-0.5 * ((x - 1.1) / 0.75) ** 2) + 0.35
    y = y_true + rng.normal(0.0, sigma_y)
    return np.column_stack([x, y, sigma_y])


def linear_with_edge_distortion_dataset(rng: np.random.Generator) -> np.ndarray:
    x = np.linspace(0.0, 100.0, 121)
    sigma_y = np.full_like(x, 1.0)
    y_true = 1.7 * x + 8.0

    low_edge = np.where(x < 14.0, 0.22 * (14.0 - x) ** 2, 0.0)
    high_edge = np.where(x > 86.0, -0.24 * (x - 86.0) ** 2, 0.0)
    distortion = low_edge + high_edge

    y = y_true + distortion + rng.normal(0.0, sigma_y)
    return np.column_stack([x, y, sigma_y])


def piecewise_linear_dataset(rng: np.random.Generator) -> np.ndarray:
    x = np.linspace(0.0, 100.0, 141)
    sigma_y = np.full_like(x, 0.3)
    breakpoint = 50.0

    left = 0.9 * x + 4.0
    right = 0.9 * breakpoint + 4.0 + 2.8 * (x - breakpoint)
    y_true = np.where(x <= breakpoint, left, right)

    y = y_true + rng.normal(0.0, sigma_y)
    return np.column_stack([x, y, sigma_y])


def main() -> None:
    rng = np.random.default_rng(20260503)
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

    datasets = {
        "gaussian_peak.csv": gaussian_peak_dataset(rng),
        "linear_with_edge_distortion.csv": linear_with_edge_distortion_dataset(rng),
        "piecewise_linear.csv": piecewise_linear_dataset(rng),
    }

    for name, rows in datasets.items():
        write_csv(TEST_DATA_DIR / name, rows)


if __name__ == "__main__":
    main()
