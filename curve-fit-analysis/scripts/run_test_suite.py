from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "analyze_curve_fit.py"
DATA_DIR = ROOT / "test_data"
WORKSPACE_DIR = ROOT.parent / "curve-fit-analysis-workspace" / "iteration-1"


@dataclass
class TestCase:
    name: str
    data_file: Path
    output_dir: Path
    command: list[str]


def run_case(case: TestCase) -> dict[str, object]:
    case.output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(case.command, check=True, cwd=ROOT.parent)
    results_path = case.output_dir / "fit_results.json"
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    plot_path = case.output_dir / "fit_summary.png"
    if not plot_path.exists() or plot_path.stat().st_size == 0:
        raise AssertionError(f"Expected styled plot output at {plot_path}, but it was not created.")
    if payload["artifacts"]["plot"] != str(plot_path):
        raise AssertionError(f"Plot artifact path mismatch for {case.name}: {payload['artifacts']['plot']} vs {plot_path}.")
    return payload


def find_model(results: list[dict[str, object]], model: str) -> dict[str, object]:
    for result in results:
        if result["model"] == model:
            return result
    raise AssertionError(f"Model '{model}' not found in results.")


def assert_between(value: float, lower: float, upper: float, label: str) -> None:
    if not (lower <= value <= upper):
        raise AssertionError(f"{label} expected in [{lower}, {upper}] but got {value}.")


def gaussian_assertions(payload: dict[str, object]) -> list[str]:
    full = payload["full_range_results"]
    best = full[0]
    if best["model"] != "gaussian":
        raise AssertionError(f"Expected gaussian to win, got {best['model']}.")

    params = {name: value for name, value in zip(best["parameter_names"], best["parameters"], strict=True)}
    assert_between(params["mu"], 0.95, 1.25, "gaussian mu")
    assert_between(params["sigma"], 0.6, 0.9, "gaussian sigma")

    redchi = best["metrics"]["reduced_chi_squared"]
    assert_between(redchi, 0.4, 2.2, "gaussian reduced chi-squared")

    recommendation = payload["recommendation"]
    if recommendation["type"] != "single_model" or recommendation["model"] != "gaussian":
        raise AssertionError(f"Unexpected gaussian recommendation: {recommendation}")

    return [
        f"Best model: {best['model']}",
        f"Recovered mu={params['mu']:.4f}, sigma={params['sigma']:.4f}",
        f"Reduced chi-squared={redchi:.4f}",
        "Styled plot artifact present",
    ]


def range_assertions(payload: dict[str, object]) -> list[str]:
    full = payload["full_range_results"]
    auto = payload["auto_range_results"]
    if not auto:
        raise AssertionError("Expected auto-range results but none were produced.")

    full_linear = find_model(full, "linear")
    auto_linear = find_model(auto, "linear")

    full_redchi = full_linear["metrics"]["reduced_chi_squared"]
    auto_redchi = auto_linear["metrics"]["reduced_chi_squared"]
    if auto_redchi >= full_redchi:
        raise AssertionError(
            f"Expected auto-range linear fit to improve reduced chi-squared, got full={full_redchi}, auto={auto_redchi}."
        )

    x_min, x_max = auto_linear["x_range"]
    if not (x_min > 8.0 and x_max < 92.0):
        raise AssertionError(f"Expected a narrowed linear range, got {auto_linear['x_range']}.")

    return [
        f"Linear full-range reduced chi-squared={full_redchi:.4f}",
        f"Linear auto-range reduced chi-squared={auto_redchi:.4f}",
        f"Linear auto-range window={x_min:.3f} to {x_max:.3f}",
        "Styled plot artifact present",
    ]


def piecewise_assertions(payload: dict[str, object]) -> list[str]:
    piecewise = payload["best_piecewise"]
    if piecewise is None:
        raise AssertionError("Expected a piecewise result but none was produced.")

    if not piecewise["recommended"]:
        raise AssertionError(f"Expected piecewise fit to be recommended, got {piecewise}.")

    if piecewise["left_model"] != "linear" or piecewise["right_model"] != "linear":
        raise AssertionError(
            f"Expected linear/linear piecewise fit, got {piecewise['left_model']}/{piecewise['right_model']}."
        )

    breakpoint_x = piecewise["breakpoint_x"]
    assert_between(breakpoint_x, 45.0, 55.0, "piecewise breakpoint")

    bic_improvement = piecewise["bic_improvement_vs_best_single"]
    if bic_improvement is None or bic_improvement <= 20.0:
        raise AssertionError(f"Expected strong BIC improvement for piecewise fit, got {bic_improvement}.")

    return [
        f"Breakpoint x={breakpoint_x:.4f}",
        f"BIC improvement vs single-fit={bic_improvement:.4f}",
        f"Piecewise reduced chi-squared={piecewise['metrics']['reduced_chi_squared']:.4f}",
        "Styled plot artifact present",
    ]


def write_summary(lines: list[str]) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    summary = "# Curve Fit Skill Test Summary\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    (WORKSPACE_DIR / "TEST_SUMMARY.md").write_text(summary, encoding="utf-8")


def main() -> None:
    cases = [
        TestCase(
            name="gaussian_peak",
            data_file=DATA_DIR / "gaussian_peak.csv",
            output_dir=WORKSPACE_DIR / "gaussian_peak",
            command=[
                sys.executable,
                str(SCRIPT_PATH),
                str(DATA_DIR / "gaussian_peak.csv"),
                str(WORKSPACE_DIR / "gaussian_peak"),
                "--x-column",
                "x",
                "--y-column",
                "y",
                "--sigma-column",
                "sigma_y",
                "--models",
                "gaussian,lorentzian,quadratic,linear",
            ],
        ),
        TestCase(
            name="linear_with_edge_distortion",
            data_file=DATA_DIR / "linear_with_edge_distortion.csv",
            output_dir=WORKSPACE_DIR / "linear_with_edge_distortion",
            command=[
                sys.executable,
                str(SCRIPT_PATH),
                str(DATA_DIR / "linear_with_edge_distortion.csv"),
                str(WORKSPACE_DIR / "linear_with_edge_distortion"),
                "--x-column",
                "x",
                "--y-column",
                "y",
                "--sigma-column",
                "sigma_y",
                "--models",
                "linear,quadratic,cubic",
                "--auto-range",
            ],
        ),
        TestCase(
            name="piecewise_linear",
            data_file=DATA_DIR / "piecewise_linear.csv",
            output_dir=WORKSPACE_DIR / "piecewise_linear",
            command=[
                sys.executable,
                str(SCRIPT_PATH),
                str(DATA_DIR / "piecewise_linear.csv"),
                str(WORKSPACE_DIR / "piecewise_linear"),
                "--x-column",
                "x",
                "--y-column",
                "y",
                "--sigma-column",
                "sigma_y",
                "--models",
                "linear",
                "--piecewise",
            ],
        ),
    ]

    summary_lines: list[str] = []
    for case in cases:
        payload = run_case(case)
        summary_lines.append(f"{case.name}: PASS")
        if case.name == "gaussian_peak":
            summary_lines.extend(f"{case.name}: {line}" for line in gaussian_assertions(payload))
        elif case.name == "linear_with_edge_distortion":
            summary_lines.extend(f"{case.name}: {line}" for line in range_assertions(payload))
        elif case.name == "piecewise_linear":
            summary_lines.extend(f"{case.name}: {line}" for line in piecewise_assertions(payload))

    write_summary(summary_lines)


if __name__ == "__main__":
    main()
