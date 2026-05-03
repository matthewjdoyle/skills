from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from textwrap import fill
from typing import Callable, Sequence

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.stats import chi2 as chi2_distribution

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional dependency
    pd = None

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover - optional dependency
    plt = None


ArrayFunc = Callable[[np.ndarray, float], np.ndarray]


@dataclass
class SigmaInfo:
    values: np.ndarray
    source: str
    absolute_sigma: bool
    meaningful_reduced_chi_squared: bool
    assumption_note: str


@dataclass
class FitMetrics:
    n_points: int
    n_params: int
    dof: int
    chi_squared: float
    reduced_chi_squared: float
    chi_squared_p_value: float | None
    rss: float
    rmse: float
    nrmse: float
    r_squared: float | None
    aic: float
    aicc: float | None
    bic: float
    covariance_condition_number: float | None


@dataclass
class FitResult:
    model: str
    parameter_names: list[str]
    parameters: list[float]
    parameter_std: list[float]
    confidence_95: list[tuple[float, float]]
    covariance: list[list[float]] | None
    correlation: list[list[float]] | None
    metrics: FitMetrics
    x_range: tuple[float, float]
    index_range: tuple[int, int]
    range_source: str
    notes: list[str]
    stable: bool
    window_score: float | None = None


@dataclass
class PiecewiseResult:
    left_model: str
    right_model: str
    breakpoint_index: int
    breakpoint_x: float
    left_fit: FitResult
    right_fit: FitResult
    metrics: FitMetrics
    bic_improvement_vs_best_single: float | None
    reduced_chi_squared_ratio_vs_best_single: float | None
    recommended: bool
    notes: list[str]


@dataclass
class ModelSpec:
    name: str
    parameter_names: list[str]
    function: Callable[..., np.ndarray]
    guess: Callable[[np.ndarray, np.ndarray], Sequence[float]]
    bounds: Callable[[np.ndarray, np.ndarray], tuple[Sequence[float], Sequence[float]]]
    requires_positive_x: bool = False


def safe_exp(values: np.ndarray) -> np.ndarray:
    return np.exp(np.clip(values, -700.0, 700.0))


def linear_model(x: np.ndarray, m: float, b: float) -> np.ndarray:
    return m * x + b


def quadratic_model(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    return a * x**2 + b * x + c


def cubic_model(x: np.ndarray, a: float, b: float, c: float, d: float) -> np.ndarray:
    return a * x**3 + b * x**2 + c * x + d


def exponential_model(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    return a * safe_exp(b * x) + c


def power_law_model(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    clipped = np.clip(x, 1e-12, None)
    return a * clipped**b + c


def gaussian_model(x: np.ndarray, a: float, mu: float, sigma: float, c: float) -> np.ndarray:
    sigma = np.clip(sigma, 1e-12, None)
    return a * np.exp(-0.5 * ((x - mu) / sigma) ** 2) + c


def lorentzian_model(x: np.ndarray, a: float, x0: float, gamma: float, c: float) -> np.ndarray:
    gamma = np.clip(gamma, 1e-12, None)
    return a * (gamma**2 / ((x - x0) ** 2 + gamma**2)) + c


def saturation_model(x: np.ndarray, vmax: float, k: float, c: float) -> np.ndarray:
    return vmax * x / (np.clip(k + x, 1e-12, None)) + c


def sigmoid_model(x: np.ndarray, l: float, x0: float, k: float, c: float) -> np.ndarray:
    return l / (1.0 + safe_exp(-k * (x - x0))) + c


def span(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    return float(np.max(values) - np.min(values))


def edge_baseline(y: np.ndarray) -> float:
    edge_count = max(1, len(y) // 8)
    edges = np.concatenate([y[:edge_count], y[-edge_count:]])
    return float(np.median(edges))


def amplitude_guess(y: np.ndarray) -> float:
    baseline = edge_baseline(y)
    idx = int(np.argmax(np.abs(y - baseline)))
    return float(y[idx] - baseline)


def positive_width_guess(x: np.ndarray) -> float:
    return max(span(x) / 6.0, 1e-6)


def guess_linear(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    if len(x) >= 2:
        coeffs = np.polyfit(x, y, 1)
        return coeffs.tolist()
    return [1.0, float(y[0]) if len(y) else 0.0]


def guess_quadratic(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    degree = min(2, len(x) - 1)
    if degree >= 1:
        coeffs = np.polyfit(x, y, degree)
        coeffs = np.pad(coeffs, (3 - len(coeffs), 0))
        return coeffs.tolist()
    return [0.0, 1.0, float(y[0]) if len(y) else 0.0]


def guess_cubic(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    degree = min(3, len(x) - 1)
    if degree >= 1:
        coeffs = np.polyfit(x, y, degree)
        coeffs = np.pad(coeffs, (4 - len(coeffs), 0))
        return coeffs.tolist()
    return [0.0, 0.0, 1.0, float(y[0]) if len(y) else 0.0]


def guess_exponential(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    c0 = float(np.min(y))
    shifted = y - c0 + max(span(y) * 1e-3, 1e-9)
    positive = shifted > 0
    if np.count_nonzero(positive) >= 2:
        coeffs = np.polyfit(x[positive], np.log(shifted[positive]), 1)
        b = float(coeffs[0])
        a = float(math.exp(coeffs[1]))
        return [a, b, c0]
    return [amplitude_guess(y), 1.0 / max(span(x), 1.0), edge_baseline(y)]


def guess_power_law(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    c0 = float(np.min(y))
    shifted = y - c0 + max(span(y) * 1e-3, 1e-9)
    positive = (x > 0) & (shifted > 0)
    if np.count_nonzero(positive) >= 2:
        coeffs = np.polyfit(np.log(x[positive]), np.log(shifted[positive]), 1)
        return [float(math.exp(coeffs[1])), float(coeffs[0]), c0]
    return [1.0, 1.0, 0.0]


def guess_gaussian(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    base = edge_baseline(y)
    idx = int(np.argmax(np.abs(y - base)))
    return [float(y[idx] - base), float(x[idx]), positive_width_guess(x), base]


def guess_lorentzian(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    base = edge_baseline(y)
    idx = int(np.argmax(np.abs(y - base)))
    return [float(y[idx] - base), float(x[idx]), max(span(x) / 10.0, 1e-6), base]


def guess_saturation(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    vmax = float(np.max(y) - np.min(y))
    positive_x = x[x > 0]
    k = float(np.median(positive_x)) if len(positive_x) else max(span(x) / 2.0, 1e-6)
    return [vmax if vmax else 1.0, max(k, 1e-6), float(np.min(y))]


def guess_sigmoid(x: np.ndarray, y: np.ndarray) -> Sequence[float]:
    return [
        float(np.max(y) - np.min(y)) or 1.0,
        float(np.median(x)),
        1.0 / max(span(x), 1.0),
        float(np.min(y)),
    ]


def unbounded(param_count: int) -> Callable[[np.ndarray, np.ndarray], tuple[Sequence[float], Sequence[float]]]:
    def inner(_x: np.ndarray, _y: np.ndarray) -> tuple[Sequence[float], Sequence[float]]:
        return ([-np.inf] * param_count, [np.inf] * param_count)

    return inner


def positive_width_bounds(param_count: int, width_index: int) -> Callable[[np.ndarray, np.ndarray], tuple[Sequence[float], Sequence[float]]]:
    def inner(_x: np.ndarray, _y: np.ndarray) -> tuple[Sequence[float], Sequence[float]]:
        lower = [-np.inf] * param_count
        upper = [np.inf] * param_count
        lower[width_index] = 1e-12
        return lower, upper

    return inner


MODEL_LIBRARY: dict[str, ModelSpec] = {
    "linear": ModelSpec("linear", ["m", "b"], linear_model, guess_linear, unbounded(2)),
    "quadratic": ModelSpec("quadratic", ["a", "b", "c"], quadratic_model, guess_quadratic, unbounded(3)),
    "cubic": ModelSpec("cubic", ["a", "b", "c", "d"], cubic_model, guess_cubic, unbounded(4)),
    "exponential": ModelSpec("exponential", ["a", "b", "c"], exponential_model, guess_exponential, unbounded(3)),
    "power_law": ModelSpec(
        "power_law",
        ["a", "b", "c"],
        power_law_model,
        guess_power_law,
        unbounded(3),
        requires_positive_x=True,
    ),
    "gaussian": ModelSpec(
        "gaussian",
        ["a", "mu", "sigma", "c"],
        gaussian_model,
        guess_gaussian,
        positive_width_bounds(4, 2),
    ),
    "lorentzian": ModelSpec(
        "lorentzian",
        ["a", "x0", "gamma", "c"],
        lorentzian_model,
        guess_lorentzian,
        positive_width_bounds(4, 2),
    ),
    "saturation": ModelSpec(
        "saturation",
        ["vmax", "k", "c"],
        saturation_model,
        guess_saturation,
        positive_width_bounds(3, 1),
        requires_positive_x=True,
    ),
    "sigmoid": ModelSpec("sigmoid", ["L", "x0", "k", "c"], sigmoid_model, guess_sigmoid, unbounded(4)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare curve_fit models and produce a diagnostics report.")
    parser.add_argument("input_file", type=Path, help="CSV, TSV, TXT, or XLSX file containing the dataset.")
    parser.add_argument("output_dir", type=Path, help="Directory for reports, JSON, and plot output.")
    parser.add_argument("--x-column", help="Column name or zero-based index for x values.")
    parser.add_argument("--y-column", help="Column name or zero-based index for y values.")
    parser.add_argument("--sigma-column", help="Column name or zero-based index for y uncertainty.")
    parser.add_argument("--sigma-value", type=float, help="Constant uncertainty to assign to every point.")
    parser.add_argument("--sigma-fraction", type=float, help="Relative uncertainty, e.g. 0.02 for 2 percent.")
    parser.add_argument("--sheet", help="Optional sheet name for XLSX files.")
    parser.add_argument("--delimiter", help="Override delimiter for text files.")
    parser.add_argument("--models", default="linear,quadratic,exponential,power_law,gaussian,lorentzian,saturation,sigmoid")
    parser.add_argument("--x-min", type=float, help="Manual lower x bound before fitting.")
    parser.add_argument("--x-max", type=float, help="Manual upper x bound before fitting.")
    parser.add_argument("--auto-range", action="store_true", help="Search for the best contiguous fit range per model.")
    parser.add_argument("--piecewise", action="store_true", help="Search for a two-segment fit across the dataset.")
    parser.add_argument("--min-points", type=int, default=8, help="Minimum number of points for any fit window.")
    parser.add_argument("--min-coverage", type=float, default=0.4, help="Minimum fraction of the dataset for auto-range fits.")
    parser.add_argument("--maxfev", type=int, default=50000, help="Maximum function evaluations for curve_fit.")
    return parser.parse_args()


def guess_delimiter(path: Path) -> str | None:
    sample = path.read_text(encoding="utf-8", errors="ignore")[:4096]
    lines = [line for line in sample.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return ","
    try:
        sniffed = csv.Sniffer().sniff("\n".join(lines[:5]), delimiters=",\t; ")
        if sniffed.delimiter == " ":
            return None
        return sniffed.delimiter
    except csv.Error:
        if "," in lines[0]:
            return ","
        if "\t" in lines[0]:
            return "\t"
        if ";" in lines[0]:
            return ";"
        return None


def has_header(path: Path) -> bool:
    sample = path.read_text(encoding="utf-8", errors="ignore")[:2048]
    for line in sample.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return any(ch.isalpha() for ch in stripped)
    return False


def load_table(path: Path, sheet: str | None, delimiter: str | None) -> dict[str, np.ndarray]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        if pd is None:
            raise RuntimeError("XLSX support requires pandas and openpyxl to be installed.")
        frame = pd.read_excel(path, sheet_name=sheet)
        numeric = frame.select_dtypes(include=["number"])
        if numeric.empty:
            raise RuntimeError("No numeric columns were found in the spreadsheet.")
        return {str(column): numeric[column].to_numpy(dtype=float) for column in numeric.columns}

    actual_delimiter = delimiter if delimiter is not None else guess_delimiter(path)
    header = has_header(path)
    if header:
        data = np.genfromtxt(
            path,
            delimiter=actual_delimiter,
            names=True,
            dtype=float,
            encoding="utf-8",
            comments="#",
            invalid_raise=False,
        )
        if not getattr(data.dtype, "names", None):
            raise RuntimeError("Failed to parse named columns from the input file.")
        return {name: np.atleast_1d(np.asarray(data[name], dtype=float)) for name in data.dtype.names}

    data = np.genfromtxt(
        path,
        delimiter=actual_delimiter,
        dtype=float,
        encoding="utf-8",
        comments="#",
        invalid_raise=False,
    )
    data = np.atleast_2d(data)
    if data.shape[0] == 1 and data.ndim == 2 and data.shape[1] == 1:
        raise RuntimeError("The input file must contain at least two numeric columns.")
    return {f"col{idx}": data[:, idx] for idx in range(data.shape[1])}


def resolve_column(columns: dict[str, np.ndarray], selector: str | None, fallback_index: int) -> tuple[str, np.ndarray]:
    names = list(columns.keys())
    if selector is None:
        if fallback_index >= len(names):
            raise RuntimeError("Not enough numeric columns were found in the dataset.")
        name = names[fallback_index]
        return name, np.asarray(columns[name], dtype=float)

    if selector in columns:
        return selector, np.asarray(columns[selector], dtype=float)

    try:
        index = int(selector)
    except ValueError as exc:
        raise RuntimeError(f"Column '{selector}' was not found.") from exc

    if index < 0 or index >= len(names):
        raise RuntimeError(f"Column index {index} is out of range for columns {names}.")
    name = names[index]
    return name, np.asarray(columns[name], dtype=float)


def prepare_dataset(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, SigmaInfo, dict[str, object]]:
    columns = load_table(args.input_file, args.sheet, args.delimiter)
    x_name, x_values = resolve_column(columns, args.x_column, 0)
    y_name, y_values = resolve_column(columns, args.y_column, 1)

    lengths = [len(array) for array in columns.values()]
    if len(set(lengths)) != 1:
        raise RuntimeError("All selected numeric columns must have the same number of rows.")

    sigma_note = ""
    if args.sigma_column:
        sigma_name, sigma_values = resolve_column(columns, args.sigma_column, 2)
        sigma_values = np.asarray(sigma_values, dtype=float)
        source = f"column:{sigma_name}"
        absolute_sigma = True
        meaningful = True
        sigma_note = "Reduced chi-squared is meaningful if this uncertainty column represents 1-sigma measurement errors."
    elif args.sigma_value is not None:
        sigma_values = np.full_like(y_values, float(args.sigma_value), dtype=float)
        source = f"constant:{args.sigma_value}"
        absolute_sigma = True
        meaningful = True
        sigma_note = "Reduced chi-squared depends on the supplied constant uncertainty."
    elif args.sigma_fraction is not None:
        sigma_values = np.maximum(np.abs(y_values) * float(args.sigma_fraction), 1e-12)
        source = f"fraction:{args.sigma_fraction}"
        absolute_sigma = True
        meaningful = True
        sigma_note = "Reduced chi-squared depends on the supplied fractional uncertainty model."
    else:
        sigma_values = np.ones_like(y_values, dtype=float)
        source = "unit_weights"
        absolute_sigma = False
        meaningful = False
        sigma_note = "No measurement uncertainties were provided, so reduced chi-squared is heuristic only."

    mask = np.isfinite(x_values) & np.isfinite(y_values) & np.isfinite(sigma_values) & (sigma_values > 0)
    if args.x_min is not None:
        mask &= x_values >= args.x_min
    if args.x_max is not None:
        mask &= x_values <= args.x_max

    x_values = x_values[mask]
    y_values = y_values[mask]
    sigma_values = sigma_values[mask]

    if len(x_values) < 3:
        raise RuntimeError("At least three valid data points are required after filtering.")

    order = np.argsort(x_values)
    x_values = x_values[order]
    y_values = y_values[order]
    sigma_values = sigma_values[order]

    sigma_info = SigmaInfo(
        values=sigma_values,
        source=source,
        absolute_sigma=absolute_sigma,
        meaningful_reduced_chi_squared=meaningful,
        assumption_note=sigma_note,
    )
    dataset_summary = {
        "x_column": x_name,
        "y_column": y_name,
        "row_count_after_filtering": int(len(x_values)),
        "available_columns": list(columns.keys()),
        "x_min": float(np.min(x_values)),
        "x_max": float(np.max(x_values)),
        "y_min": float(np.min(y_values)),
        "y_max": float(np.max(y_values)),
    }
    return x_values, y_values, sigma_info, dataset_summary


def chosen_models(model_string: str) -> list[ModelSpec]:
    requested = [name.strip() for name in model_string.split(",") if name.strip()]
    missing = [name for name in requested if name not in MODEL_LIBRARY]
    if missing:
        available = ", ".join(sorted(MODEL_LIBRARY))
        raise RuntimeError(f"Unknown model(s): {missing}. Available models: {available}.")
    return [MODEL_LIBRARY[name] for name in requested]


def covariance_and_correlation(pcov: np.ndarray) -> tuple[list[list[float]] | None, list[list[float]] | None]:
    if pcov.size == 0 or not np.all(np.isfinite(pcov)):
        return None, None
    diag = np.diag(pcov)
    if np.any(diag <= 0):
        return pcov.tolist(), None
    std = np.sqrt(diag)
    denominator = np.outer(std, std)
    correlation = np.divide(pcov, denominator, out=np.full_like(pcov, np.nan), where=denominator != 0)
    return pcov.tolist(), correlation.tolist()


def fit_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    sigma: np.ndarray,
    n_params: int,
    meaningful_sigma: bool,
    pcov: np.ndarray,
) -> FitMetrics:
    residuals = y_true - y_pred
    chi_squared = float(np.sum((residuals / sigma) ** 2))
    dof = int(len(y_true) - n_params)
    reduced = chi_squared / dof if dof > 0 else math.inf
    chi_p = None
    if dof > 0 and meaningful_sigma:
        chi_p = float(chi2_distribution.sf(chi_squared, dof))

    rss = float(np.sum(residuals**2))
    rmse = math.sqrt(rss / len(y_true))
    y_span = span(y_true)
    nrmse = rmse / y_span if y_span > 0 else rmse
    tss = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r_squared = None if tss == 0 else float(1.0 - rss / tss)

    safe_rss = max(rss, 1e-300)
    n = len(y_true)
    aic = float(n * math.log(safe_rss / n) + 2 * n_params)
    aicc = None
    if n - n_params - 1 > 0:
        aicc = float(aic + (2 * n_params * (n_params + 1)) / (n - n_params - 1))
    bic = float(n * math.log(safe_rss / n) + n_params * math.log(n))

    condition_number = None
    if pcov.size and np.all(np.isfinite(pcov)):
        with np.errstate(all="ignore"):
            condition_number = float(np.linalg.cond(pcov))
    return FitMetrics(
        n_points=n,
        n_params=n_params,
        dof=dof,
        chi_squared=chi_squared,
        reduced_chi_squared=reduced,
        chi_squared_p_value=chi_p,
        rss=rss,
        rmse=rmse,
        nrmse=nrmse,
        r_squared=r_squared,
        aic=aic,
        aicc=aicc,
        bic=bic,
        covariance_condition_number=condition_number,
    )


def fit_model(
    spec: ModelSpec,
    x: np.ndarray,
    y: np.ndarray,
    sigma_info: SigmaInfo,
    start_index: int,
    end_index: int,
    range_source: str,
    maxfev: int,
) -> FitResult | None:
    notes: list[str] = []
    if spec.requires_positive_x and np.any(x <= 0):
        return None

    try:
        initial = np.asarray(spec.guess(x, y), dtype=float)
        lower, upper = spec.bounds(x, y)
        lower = np.asarray(lower, dtype=float)
        upper = np.asarray(upper, dtype=float)
    except Exception as exc:
        notes.append(f"Initial guess failed: {exc}")
        return None

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", OptimizeWarning)
            popt, pcov = curve_fit(
                spec.function,
                x,
                y,
                p0=initial,
                sigma=sigma_info.values[start_index:end_index],
                absolute_sigma=sigma_info.absolute_sigma,
                bounds=(lower, upper),
                maxfev=maxfev,
            )
        notes.extend(str(item.message) for item in caught)
    except Exception as exc:
        notes.append(f"curve_fit failed: {exc}")
        return None

    y_pred = spec.function(x, *popt)
    if not np.all(np.isfinite(y_pred)):
        notes.append("Predicted values were not finite.")
        return None

    metrics = fit_metrics(
        y_true=y,
        y_pred=y_pred,
        sigma=sigma_info.values[start_index:end_index],
        n_params=len(popt),
        meaningful_sigma=sigma_info.meaningful_reduced_chi_squared,
        pcov=pcov,
    )

    if pcov.size and np.all(np.isfinite(np.diag(pcov))):
        parameter_std = np.sqrt(np.clip(np.diag(pcov), 0.0, None))
    else:
        parameter_std = np.full(len(popt), np.nan)

    confidence_95 = []
    for value, std in zip(popt, parameter_std, strict=True):
        if math.isfinite(std):
            confidence_95.append((float(value - 1.96 * std), float(value + 1.96 * std)))
        else:
            confidence_95.append((math.nan, math.nan))

    covariance, correlation = covariance_and_correlation(pcov)
    stable = bool(np.all(np.isfinite(parameter_std)))
    if metrics.covariance_condition_number is not None and metrics.covariance_condition_number > 1e12:
        stable = False
        notes.append("Covariance matrix is ill-conditioned; parameter errors may be unreliable.")
    if np.any(~np.isfinite(parameter_std)):
        notes.append("Parameter uncertainties could not be estimated cleanly from the covariance matrix.")

    return FitResult(
        model=spec.name,
        parameter_names=list(spec.parameter_names),
        parameters=[float(value) for value in popt],
        parameter_std=[float(value) for value in parameter_std],
        confidence_95=confidence_95,
        covariance=covariance,
        correlation=correlation,
        metrics=metrics,
        x_range=(float(np.min(x)), float(np.max(x))),
        index_range=(start_index, end_index),
        range_source=range_source,
        notes=notes,
        stable=stable,
    )


def compare_key(result: FitResult, meaningful_sigma: bool) -> tuple[float, float, float]:
    stability_penalty = 1.0 if not result.stable else 0.0
    if meaningful_sigma and result.metrics.reduced_chi_squared > 0 and math.isfinite(result.metrics.reduced_chi_squared):
        redchi_term = abs(math.log(result.metrics.reduced_chi_squared))
    else:
        redchi_term = result.metrics.nrmse
    return (stability_penalty, result.metrics.bic, redchi_term)


def score_window(result: FitResult, coverage: float, meaningful_sigma: bool) -> float:
    if meaningful_sigma and result.metrics.reduced_chi_squared > 0 and math.isfinite(result.metrics.reduced_chi_squared):
        fit_term = abs(math.log(result.metrics.reduced_chi_squared))
    else:
        fit_term = math.log(max(result.metrics.nrmse, 1e-12))
    short_range_penalty = 0.35 * (1.0 - coverage)
    stability_penalty = 1.5 if not result.stable else 0.0
    return fit_term + short_range_penalty + stability_penalty


def search_best_range(
    spec: ModelSpec,
    x: np.ndarray,
    y: np.ndarray,
    sigma_info: SigmaInfo,
    min_points: int,
    min_coverage: float,
    maxfev: int,
) -> FitResult | None:
    n = len(x)
    effective_min_points = max(min_points, len(spec.parameter_names) + 3)
    if n < effective_min_points:
        return None

    step = max(1, n // 60)
    candidate_indices = list(range(0, n + 1, step))
    if candidate_indices[-1] != n:
        candidate_indices.append(n)

    best: FitResult | None = None
    best_score = math.inf
    for start in candidate_indices[:-1]:
        for end in candidate_indices[1:]:
            if end - start < effective_min_points:
                continue
            if end <= start:
                continue
            coverage = (end - start) / n
            if coverage < min_coverage:
                continue
            fit = fit_model(spec, x[start:end], y[start:end], sigma_info, start, end, "auto_range", maxfev)
            if fit is None:
                continue
            fit.window_score = score_window(fit, coverage, sigma_info.meaningful_reduced_chi_squared)
            if fit.window_score < best_score:
                best = fit
                best_score = fit.window_score
    return best


def search_piecewise(
    specs: list[ModelSpec],
    x: np.ndarray,
    y: np.ndarray,
    sigma_info: SigmaInfo,
    min_points: int,
    maxfev: int,
    best_single: FitResult | None,
) -> PiecewiseResult | None:
    n = len(x)
    step = max(1, n // 50)
    candidate_breaks = list(range(min_points, n - min_points + 1, step))
    if candidate_breaks and candidate_breaks[-1] != n - min_points:
        candidate_breaks.append(n - min_points)

    best_piecewise: PiecewiseResult | None = None
    best_bic = math.inf
    simplicity_tolerance = 3.0

    for breakpoint in candidate_breaks:
        left_results: list[FitResult] = []
        right_results: list[FitResult] = []
        for spec in specs:
            left_fit = fit_model(spec, x[:breakpoint], y[:breakpoint], sigma_info, 0, breakpoint, "piecewise_left", maxfev)
            right_fit = fit_model(spec, x[breakpoint:], y[breakpoint:], sigma_info, breakpoint, n, "piecewise_right", maxfev)
            if left_fit is not None:
                left_results.append(left_fit)
            if right_fit is not None:
                right_results.append(right_fit)

        for left_fit in left_results:
            for right_fit in right_results:
                total_params = left_fit.metrics.n_params + right_fit.metrics.n_params + 1
                dof = n - total_params
                if dof <= 0:
                    continue
                chi_squared = left_fit.metrics.chi_squared + right_fit.metrics.chi_squared
                rss = left_fit.metrics.rss + right_fit.metrics.rss
                rmse = math.sqrt(rss / n)
                y_span = span(y)
                nrmse = rmse / y_span if y_span > 0 else rmse
                tss = float(np.sum((y - np.mean(y)) ** 2))
                r_squared = None if tss == 0 else float(1.0 - rss / tss)
                aic = float(n * math.log(max(rss, 1e-300) / n) + 2 * total_params)
                aicc = None
                if n - total_params - 1 > 0:
                    aicc = float(aic + (2 * total_params * (total_params + 1)) / (n - total_params - 1))
                bic = float(n * math.log(max(rss, 1e-300) / n) + total_params * math.log(n))
                reduced = chi_squared / dof
                chi_p = None
                if sigma_info.meaningful_reduced_chi_squared:
                    chi_p = float(chi2_distribution.sf(chi_squared, dof))
                piecewise_metrics = FitMetrics(
                    n_points=n,
                    n_params=total_params,
                    dof=dof,
                    chi_squared=chi_squared,
                    reduced_chi_squared=reduced,
                    chi_squared_p_value=chi_p,
                    rss=rss,
                    rmse=rmse,
                    nrmse=nrmse,
                    r_squared=r_squared,
                    aic=aic,
                    aicc=aicc,
                    bic=bic,
                    covariance_condition_number=None,
                )

                bic_improvement = None
                redchi_ratio = None
                recommended = False
                notes: list[str] = []
                if best_single is not None:
                    bic_improvement = best_single.metrics.bic - bic
                    if best_single.metrics.reduced_chi_squared and math.isfinite(best_single.metrics.reduced_chi_squared):
                        redchi_ratio = reduced / best_single.metrics.reduced_chi_squared
                    recommended = bic_improvement > 10.0
                    if recommended:
                        notes.append("Piecewise fit strongly outperforms the best single-fit model by BIC.")

                candidate = PiecewiseResult(
                    left_model=left_fit.model,
                    right_model=right_fit.model,
                    breakpoint_index=breakpoint,
                    breakpoint_x=float(0.5 * (x[breakpoint - 1] + x[breakpoint])),
                    left_fit=left_fit,
                    right_fit=right_fit,
                    metrics=piecewise_metrics,
                    bic_improvement_vs_best_single=bic_improvement,
                    reduced_chi_squared_ratio_vs_best_single=redchi_ratio,
                    recommended=recommended,
                    notes=notes,
                )
                if bic < best_bic - 1e-12:
                    best_bic = bic
                    best_piecewise = candidate
                    continue

                if best_piecewise is None:
                    continue

                if abs(bic - best_bic) <= simplicity_tolerance:
                    candidate_params = candidate.metrics.n_params
                    incumbent_params = best_piecewise.metrics.n_params
                    if candidate_params < incumbent_params:
                        best_bic = bic
                        best_piecewise = candidate
                    elif candidate_params == incumbent_params and candidate.metrics.reduced_chi_squared < best_piecewise.metrics.reduced_chi_squared:
                        best_bic = bic
                        best_piecewise = candidate
    return best_piecewise


def fmt(value: float | None, digits: int = 5) -> str:
    if value is None:
        return "n/a"
    if not math.isfinite(value):
        return "inf"
    return f"{value:.{digits}g}"


def fit_table(results: list[FitResult]) -> str:
    lines = [
        "| Model | Points | Parameters | Reduced chi-squared | BIC | AICc | R^2 | Stable |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    result.model,
                    str(result.metrics.n_points),
                    str(result.metrics.n_params),
                    fmt(result.metrics.reduced_chi_squared),
                    fmt(result.metrics.bic),
                    fmt(result.metrics.aicc),
                    fmt(result.metrics.r_squared),
                    "yes" if result.stable else "no",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def auto_range_table(results: list[FitResult]) -> str:
    lines = [
        "| Model | x-range | Points | Coverage score | Reduced chi-squared | BIC |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    max_index = max(result.index_range[1] for result in results) if results else 1
    for result in results:
        coverage = (result.index_range[1] - result.index_range[0]) / max_index
        lines.append(
            "| "
            + " | ".join(
                [
                    result.model,
                    f"{fmt(result.x_range[0])} to {fmt(result.x_range[1])}",
                    str(result.metrics.n_points),
                    fmt(coverage),
                    fmt(result.metrics.reduced_chi_squared),
                    fmt(result.metrics.bic),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def parameter_section(result: FitResult) -> str:
    lines = [
        "| Parameter | Value | 1-sigma | 95% interval |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, value, std, ci in zip(
        result.parameter_names,
        result.parameters,
        result.parameter_std,
        result.confidence_95,
        strict=True,
    ):
        interval = f"[{fmt(ci[0])}, {fmt(ci[1])}]"
        lines.append(f"| {name} | {fmt(value)} | {fmt(std)} | {interval} |")
    return "\n".join(lines)


def recommendation_summary(
    best_single: FitResult | None,
    best_auto_range: FitResult | None,
    best_piecewise: PiecewiseResult | None,
) -> tuple[str, dict[str, object]]:
    if best_piecewise is not None and best_piecewise.recommended:
        summary = (
            "A two-segment fit is recommended. "
            f"The best split is near x = {fmt(best_piecewise.breakpoint_x)}, "
            f"with {best_piecewise.left_model} on the left and {best_piecewise.right_model} on the right."
        )
        payload = {
            "type": "piecewise",
            "breakpoint_x": best_piecewise.breakpoint_x,
            "left_model": best_piecewise.left_model,
            "right_model": best_piecewise.right_model,
        }
        return summary, payload

    if best_single is not None:
        summary = f"The best single global fit is {best_single.model} over x = {fmt(best_single.x_range[0])} to {fmt(best_single.x_range[1])}."
        payload = {
            "type": "single_model",
            "model": best_single.model,
            "x_range": best_single.x_range,
        }
        if best_auto_range is not None and best_auto_range.model == best_single.model and best_auto_range.index_range != best_single.index_range:
            summary += (
                " A narrower window also looks reasonable for that same model: "
                f"x = {fmt(best_auto_range.x_range[0])} to {fmt(best_auto_range.x_range[1])}."
            )
            payload["narrower_window"] = best_auto_range.x_range
        return summary, payload

    if best_auto_range is not None:
        summary = (
            f"No strong global fit was found, but {best_auto_range.model} fits a narrower window "
            f"from x = {fmt(best_auto_range.x_range[0])} to {fmt(best_auto_range.x_range[1])}."
        )
        payload = {
            "type": "range_limited",
            "model": best_auto_range.model,
            "x_range": best_auto_range.x_range,
        }
        return summary, payload

    return "No model produced a usable fit.", {"type": "none"}


def write_curve_csv(path: Path, x: np.ndarray, y: np.ndarray, fit: FitResult, spec: ModelSpec) -> None:
    y_pred = spec.function(x, *fit.parameters)
    lines = ["x,y,y_fit"]
    lines.extend(f"{xv},{yv},{fv}" for xv, yv, fv in zip(x, y, y_pred, strict=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_piecewise_curve_csv(path: Path, x: np.ndarray, y: np.ndarray, piecewise: PiecewiseResult) -> None:
    left_spec = MODEL_LIBRARY[piecewise.left_model]
    right_spec = MODEL_LIBRARY[piecewise.right_model]
    left_x = x[: piecewise.breakpoint_index]
    right_x = x[piecewise.breakpoint_index :]
    left_fit = left_spec.function(left_x, *piecewise.left_fit.parameters)
    right_fit = right_spec.function(right_x, *piecewise.right_fit.parameters)
    fitted = np.concatenate([left_fit, right_fit])
    lines = ["x,y,y_fit,segment"]
    for idx, (xv, yv, fv) in enumerate(zip(x, y, fitted, strict=True)):
        segment = "left" if idx < piecewise.breakpoint_index else "right"
        lines.append(f"{xv},{yv},{fv},{segment}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prediction_for_fit(result: FitResult, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    spec = MODEL_LIBRARY[result.model]
    start, end = result.index_range
    x_section = x[start:end]
    return x_section, spec.function(x_section, *result.parameters)


def prediction_for_piecewise(result: PiecewiseResult, x: np.ndarray) -> np.ndarray:
    left_spec = MODEL_LIBRARY[result.left_model]
    right_spec = MODEL_LIBRARY[result.right_model]
    left_x = x[: result.breakpoint_index]
    right_x = x[result.breakpoint_index :]
    left_values = left_spec.function(left_x, *result.left_fit.parameters)
    right_values = right_spec.function(right_x, *result.right_fit.parameters)
    return np.concatenate([left_values, right_values])


def build_stats_panel_text(
    recommendation_text: str,
    sigma_info: SigmaInfo,
    best_single: FitResult | None,
    best_auto_range: FitResult | None,
    best_piecewise: PiecewiseResult | None,
) -> str:
    lines = ["Recommendation", fill(recommendation_text, width=34), ""]

    if best_single is not None:
        lines.extend(
            [
                "Best single-fit",
                f"Model: {best_single.model}",
                f"red chi^2: {fmt(best_single.metrics.reduced_chi_squared)}",
                f"dof: {best_single.metrics.dof}",
                f"BIC: {fmt(best_single.metrics.bic)}",
                "",
                "Parameters",
            ]
        )
        for name, value, std in zip(best_single.parameter_names, best_single.parameters, best_single.parameter_std, strict=True):
            lines.append(f"{name} = {fmt(value)} +/- {fmt(std)}")
        lines.append("")

    if best_auto_range is not None:
        lines.extend(
            [
                "Range selection",
                f"x = {fmt(best_auto_range.x_range[0])} to {fmt(best_auto_range.x_range[1])}",
                f"model: {best_auto_range.model}",
                f"red chi^2: {fmt(best_auto_range.metrics.reduced_chi_squared)}",
                "",
            ]
        )

    if best_piecewise is not None:
        lines.extend(
            [
                "Piecewise check",
                f"breakpoint: x = {fmt(best_piecewise.breakpoint_x)}",
                f"models: {best_piecewise.left_model} | {best_piecewise.right_model}",
                f"delta BIC: {fmt(best_piecewise.bic_improvement_vs_best_single)}",
                f"red chi^2: {fmt(best_piecewise.metrics.reduced_chi_squared)}",
                "",
            ]
        )

    lines.extend(
        [
            "Uncertainty note",
            fill(sigma_info.assumption_note, width=34),
        ]
    )
    return "\n".join(lines)


def make_plot(
    output_path: Path,
    dataset_label: str,
    x: np.ndarray,
    y: np.ndarray,
    sigma_info: SigmaInfo,
    full_results: list[FitResult],
    best_single: FitResult | None,
    best_auto_range: FitResult | None,
    best_piecewise: PiecewiseResult | None,
    recommendation_text: str,
) -> None:
    if plt is None:
        return

    palette = {
        "canvas": "#f6f1e8",
        "panel": "#fffdf8",
        "grid": "#d8dee9",
        "text": "#102a43",
        "muted": "#486581",
        "data": "#334e68",
        "error": "#bcccdc",
        "primary": "#0f766e",
        "secondary": "#2563eb",
        "tertiary": "#dc6803",
        "highlight": "#f59e0b",
        "piecewise": "#b54708",
        "danger": "#9a3412",
    }

    fig = plt.figure(figsize=(15.5, 10.5), facecolor=palette["canvas"], constrained_layout=True)
    axes = fig.subplot_mosaic(
        [["fit", "fit", "stats"], ["fit", "fit", "stats"], ["residuals", "residuals", "stats"], ["compare", "compare", "stats"]],
        gridspec_kw={"height_ratios": [1.45, 1.45, 1.0, 0.95], "width_ratios": [1.35, 1.35, 1.05]},
    )
    ax_fit = axes["fit"]
    ax_res = axes["residuals"]
    ax_compare = axes["compare"]
    ax_stats = axes["stats"]

    def style_axis(ax: object, title: str) -> None:
        ax.set_facecolor(palette["panel"])
        ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=palette["text"], pad=10)
        ax.grid(True, color=palette["grid"], alpha=0.8, linewidth=0.85)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#9fb3c8")
        ax.spines["bottom"].set_color("#9fb3c8")

    style_axis(ax_fit, "Data And Candidate Fits")
    style_axis(ax_res, "Residual Structure")
    style_axis(ax_compare, "Model Comparison")
    ax_stats.set_facecolor(palette["panel"])
    ax_stats.axis("off")

    fig.suptitle(f"Curve-Fit Analysis | {dataset_label}", x=0.03, y=0.995, ha="left", fontsize=18, fontweight="bold", color=palette["text"])
    fig.text(
        0.03,
        0.968,
        "Detailed fit figure with model overlays, range selection, residual diagnostics, and recommendation summary.",
        ha="left",
        fontsize=10.5,
        color=palette["muted"],
    )

    show_error_bars = sigma_info.meaningful_reduced_chi_squared or sigma_info.source != "unit_weights"
    if show_error_bars:
        ax_fit.errorbar(
            x,
            y,
            yerr=sigma_info.values,
            fmt="o",
            ms=4.6,
            mfc=palette["data"],
            mec="#ffffff",
            mew=0.6,
            ecolor=palette["error"],
            elinewidth=0.95,
            capsize=2.5,
            alpha=0.95,
            label="Measured data",
            zorder=4,
        )
    else:
        ax_fit.scatter(x, y, s=28, color=palette["data"], edgecolor="#ffffff", linewidth=0.5, alpha=0.95, label="Measured data", zorder=4)

    comparison_results = full_results[: min(len(full_results), 4)]
    comparison_colors = [palette["primary"], palette["secondary"], palette["tertiary"], "#7c2d12"]
    for idx, result in enumerate(comparison_results):
        x_section, y_fit = prediction_for_fit(result, x)
        linestyle = "-" if idx == 0 else (0, (6, 3))
        linewidth = 3.0 if idx == 0 else 2.0
        alpha = 0.95 if idx == 0 else 0.7
        ax_fit.plot(
            x_section,
            y_fit,
            color=comparison_colors[idx],
            linestyle=linestyle,
            linewidth=linewidth,
            alpha=alpha,
            label=f"{result.model} | BIC {fmt(result.metrics.bic)}",
            zorder=3 - min(idx, 2),
        )

    if best_auto_range is not None:
        ax_fit.axvspan(best_auto_range.x_range[0], best_auto_range.x_range[1], color=palette["highlight"], alpha=0.12, label="Selected fit range", zorder=0)
        x_local, y_local = prediction_for_fit(best_auto_range, x)
        ax_fit.plot(
            x_local,
            y_local,
            color=palette["highlight"],
            linewidth=2.4,
            linestyle=(0, (3, 2)),
            alpha=0.95,
            label=f"Best local fit | {best_auto_range.model}",
            zorder=5,
        )

    piecewise_prediction = None
    if best_piecewise is not None:
        piecewise_prediction = prediction_for_piecewise(best_piecewise, x)
        ax_fit.plot(
            x,
            piecewise_prediction,
            color=palette["piecewise"],
            linewidth=2.7,
            linestyle="-.",
            alpha=0.92,
            label=f"Piecewise | {best_piecewise.left_model} + {best_piecewise.right_model}",
            zorder=6,
        )
        ax_fit.axvline(best_piecewise.breakpoint_x, color=palette["danger"], linewidth=1.65, alpha=0.85, label="Suggested breakpoint", zorder=2)

    if best_single is not None:
        _, single_prediction = prediction_for_fit(best_single, x)
        residual_scale = sigma_info.values if sigma_info.meaningful_reduced_chi_squared else np.ones_like(y)
        single_residuals = (y - single_prediction) / residual_scale

        if sigma_info.meaningful_reduced_chi_squared:
            ax_res.axhspan(-2.0, 2.0, color="#d1fae5", alpha=0.6, zorder=0)
            ax_res.axhspan(-1.0, 1.0, color="#a7f3d0", alpha=0.4, zorder=0)

        ax_res.axhline(0.0, color=palette["muted"], linewidth=1.15, alpha=0.85)
        ax_res.plot(x, single_residuals, color=palette["primary"], linewidth=1.8, label=f"{best_single.model} residuals")
        ax_res.scatter(x, single_residuals, color=palette["primary"], s=18, alpha=0.9)

        if piecewise_prediction is not None:
            piecewise_residuals = (y - piecewise_prediction) / residual_scale
            ax_res.plot(x, piecewise_residuals, color=palette["piecewise"], linewidth=1.6, linestyle="-.", label="piecewise residuals")
            ax_res.scatter(x, piecewise_residuals, color=palette["piecewise"], s=15, alpha=0.75)

        if best_auto_range is not None:
            ax_res.axvspan(best_auto_range.x_range[0], best_auto_range.x_range[1], color=palette["highlight"], alpha=0.12, zorder=0)

    if best_single is not None:
        best_bic = best_single.metrics.bic
        labels = [result.model for result in comparison_results]
        delta_bic = [max(result.metrics.bic - best_bic, 0.0) for result in comparison_results]
        y_positions = np.arange(len(labels))
        bar_colors = [comparison_colors[idx] for idx in range(len(labels))]
        bars = ax_compare.barh(y_positions, delta_bic, color=bar_colors, alpha=0.88, height=0.58)
        ax_compare.set_yticks(y_positions, labels)
        ax_compare.invert_yaxis()
        ax_compare.set_xlabel("Delta BIC from best model")
        for bar, result in zip(bars, comparison_results, strict=True):
            text_x = bar.get_width() + max(max(delta_bic, default=0.0) * 0.02, 0.12)
            ax_compare.text(
                text_x,
                bar.get_y() + bar.get_height() / 2,
                f"red chi^2 {fmt(result.metrics.reduced_chi_squared, 4)}",
                va="center",
                ha="left",
                fontsize=9.2,
                color=palette["text"],
            )
    else:
        ax_compare.text(0.02, 0.5, "No converged global fits to compare.", transform=ax_compare.transAxes, fontsize=11, color=palette["muted"], va="center")

    stats_text = build_stats_panel_text(recommendation_text, sigma_info, best_single, best_auto_range, best_piecewise)
    ax_stats.text(
        0.04,
        0.97,
        stats_text,
        transform=ax_stats.transAxes,
        va="top",
        ha="left",
        fontsize=10.2,
        color=palette["text"],
        linespacing=1.4,
        bbox={"boxstyle": "round,pad=0.6", "facecolor": "#fff9f0", "edgecolor": "#d9e2ec", "linewidth": 1.1},
    )

    ax_fit.set_ylabel("y")
    ax_fit.set_xlabel("x")
    ax_fit.legend(loc="upper left", fontsize=9.2, frameon=True, facecolor="#ffffff", edgecolor="#d9e2ec")
    ax_fit.margins(x=0.02)

    residual_label = "Normalized residual ((y - fit) / sigma)" if sigma_info.meaningful_reduced_chi_squared else "Residual (y - fit)"
    ax_res.set_xlabel("x")
    ax_res.set_ylabel(residual_label)
    ax_res.legend(loc="upper left", fontsize=9.0, frameon=True, facecolor="#ffffff", edgecolor="#d9e2ec")
    ax_res.margins(x=0.02)

    fig.savefig(output_path, dpi=220, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def serialize_fit(result: FitResult) -> dict[str, object]:
    payload = asdict(result)
    payload["metrics"] = asdict(result.metrics)
    return payload


def serialize_piecewise(result: PiecewiseResult) -> dict[str, object]:
    payload = asdict(result)
    payload["left_fit"] = serialize_fit(result.left_fit)
    payload["right_fit"] = serialize_fit(result.right_fit)
    payload["metrics"] = asdict(result.metrics)
    return payload


def build_report(
    input_file: Path,
    dataset_summary: dict[str, object],
    sigma_info: SigmaInfo,
    models: list[ModelSpec],
    full_results: list[FitResult],
    auto_results: list[FitResult],
    best_single: FitResult | None,
    best_auto_range: FitResult | None,
    best_piecewise: PiecewiseResult | None,
    recommendation_text: str,
) -> str:
    lines = [
        "# Curve Fit Analysis Report",
        "",
        "## Dataset summary",
        f"- Input file: `{input_file}`",
        f"- x column: `{dataset_summary['x_column']}`",
        f"- y column: `{dataset_summary['y_column']}`",
        f"- Points analysed: {dataset_summary['row_count_after_filtering']}",
        f"- x range: {fmt(dataset_summary['x_min'])} to {fmt(dataset_summary['x_max'])}",
        f"- y range: {fmt(dataset_summary['y_min'])} to {fmt(dataset_summary['y_max'])}",
        f"- Sigma source: `{sigma_info.source}`",
        f"- Sigma note: {sigma_info.assumption_note}",
        "",
        "## Candidate models",
        ", ".join(spec.name for spec in models),
        "",
        "## Model comparison on the common range",
    ]

    if full_results:
        lines.extend([fit_table(full_results), ""])
    else:
        lines.extend(["No candidate model converged on the common range.", ""])

    if best_single is not None:
        lines.extend(
            [
                f"## Best single-fit model: `{best_single.model}`",
                "",
                parameter_section(best_single),
                "",
                f"- Reduced chi-squared: {fmt(best_single.metrics.reduced_chi_squared)}",
                f"- Degrees of freedom: {best_single.metrics.dof}",
                f"- BIC: {fmt(best_single.metrics.bic)}",
                f"- AICc: {fmt(best_single.metrics.aicc)}",
                f"- R-squared: {fmt(best_single.metrics.r_squared)}",
                f"- Covariance condition number: {fmt(best_single.metrics.covariance_condition_number)}",
            ]
        )
        if best_single.notes:
            lines.extend(["- Notes: " + "; ".join(best_single.notes)])
        lines.append("")

    if auto_results:
        lines.extend(["## Auto-range analysis", "", auto_range_table(auto_results), ""])
    else:
        lines.extend(["## Auto-range analysis", "", "Auto-range search was not requested or produced no valid window.", ""])

    lines.extend(["## Piecewise fit check", ""])
    if best_piecewise is None:
        lines.append("No valid two-segment fit was found.")
    else:
        lines.extend(
            [
                f"- Left model: `{best_piecewise.left_model}`",
                f"- Right model: `{best_piecewise.right_model}`",
                f"- Suggested breakpoint: x = {fmt(best_piecewise.breakpoint_x)}",
                f"- Reduced chi-squared: {fmt(best_piecewise.metrics.reduced_chi_squared)}",
                f"- BIC: {fmt(best_piecewise.metrics.bic)}",
                f"- BIC improvement vs best single fit: {fmt(best_piecewise.bic_improvement_vs_best_single)}",
            ]
        )
        if best_piecewise.notes:
            lines.append("- Notes: " + "; ".join(best_piecewise.notes))
    lines.extend(["", "## Recommendation", recommendation_text, ""])
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    x, y, sigma_info, dataset_summary = prepare_dataset(args)
    specs = chosen_models(args.models)

    full_results: list[FitResult] = []
    for spec in specs:
        fit = fit_model(spec, x, y, sigma_info, 0, len(x), "full_range", args.maxfev)
        if fit is not None:
            full_results.append(fit)
    full_results.sort(key=lambda result: compare_key(result, sigma_info.meaningful_reduced_chi_squared))

    auto_results: list[FitResult] = []
    if args.auto_range:
        for spec in specs:
            fit = search_best_range(spec, x, y, sigma_info, args.min_points, args.min_coverage, args.maxfev)
            if fit is not None:
                auto_results.append(fit)
        auto_results.sort(
            key=lambda result: (
                result.window_score if result.window_score is not None else math.inf,
                result.metrics.bic,
            )
        )

    best_single = full_results[0] if full_results else None
    best_auto_range = auto_results[0] if auto_results else None
    best_piecewise = None
    if args.piecewise:
        piecewise_min_points = max(args.min_points, 6)
        best_piecewise = search_piecewise(specs, x, y, sigma_info, piecewise_min_points, args.maxfev, best_single)

    recommendation_text, recommendation_payload = recommendation_summary(best_single, best_auto_range, best_piecewise)

    report = build_report(
        input_file=args.input_file,
        dataset_summary=dataset_summary,
        sigma_info=sigma_info,
        models=specs,
        full_results=full_results,
        auto_results=auto_results,
        best_single=best_single,
        best_auto_range=best_auto_range,
        best_piecewise=best_piecewise,
        recommendation_text=recommendation_text,
    )

    report_path = args.output_dir / "fit_report.md"
    report_path.write_text(report + "\n", encoding="utf-8")

    if best_single is not None:
        write_curve_csv(args.output_dir / "best_fit_curve.csv", x, y, best_single, MODEL_LIBRARY[best_single.model])
    if best_piecewise is not None:
        write_piecewise_curve_csv(args.output_dir / "piecewise_fit_curve.csv", x, y, best_piecewise)
    make_plot(
        args.output_dir / "fit_summary.png",
        args.input_file.name,
        x,
        y,
        sigma_info,
        full_results,
        best_single,
        best_auto_range,
        best_piecewise,
        recommendation_text,
    )

    results_payload = {
        "input_file": str(args.input_file),
        "dataset": dataset_summary,
        "sigma": {
            "source": sigma_info.source,
            "absolute_sigma": sigma_info.absolute_sigma,
            "meaningful_reduced_chi_squared": sigma_info.meaningful_reduced_chi_squared,
            "assumption_note": sigma_info.assumption_note,
        },
        "models_tested": [spec.name for spec in specs],
        "full_range_results": [serialize_fit(result) for result in full_results],
        "auto_range_results": [serialize_fit(result) for result in auto_results],
        "best_piecewise": serialize_piecewise(best_piecewise) if best_piecewise is not None else None,
        "recommendation": recommendation_payload,
        "artifacts": {
            "report": str(report_path),
            "best_fit_curve": str(args.output_dir / "best_fit_curve.csv") if best_single is not None else None,
            "piecewise_fit_curve": str(args.output_dir / "piecewise_fit_curve.csv") if best_piecewise is not None else None,
            "plot": str(args.output_dir / "fit_summary.png") if plt is not None else None,
        },
    }
    (args.output_dir / "fit_results.json").write_text(json.dumps(results_payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
