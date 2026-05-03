---
name: curve-fit-analysis
description: >
  Analyse tabular data with scipy.optimize.curve_fit, including model
  comparison, parameter uncertainties, covariance-based error estimates,
  chi-squared and reduced chi-squared, range selection, and two-regime
  piecewise fitting checks. Use this skill whenever a user wants to fit
  experimental or measured data, compare candidate fit functions, decide which
  subset of data should be fitted, report parameter errors properly, or detect
  whether different ranges of the same dataset need different fits.
---

# Curve Fit Analysis

Use `scipy.optimize.curve_fit` to fit measured data, compare candidate models,
and produce a report that is explicit about assumptions, uncertainties, and fit
quality.

## When to use this skill

Use this skill whenever the user is asking for any of the following:

- nonlinear regression with `curve_fit`
- comparison of linear, polynomial, exponential, Gaussian, power-law, or other
  candidate fit functions
- parameter uncertainties or covariance analysis
- chi-squared or reduced chi-squared
- deciding what range of data should be fitted
- identifying whether one model is insufficient across the full dataset
- detecting breakpoints or regime changes that suggest two separate fits

This skill should win over a generic plotting or spreadsheet workflow when the
core task is model fitting and diagnostic interpretation.

## What this skill does

The bundled script `scripts/analyze_curve_fit.py` can:

1. Load CSV, TSV, TXT, and optionally XLSX tabular data.
2. Fit multiple built-in model families with `curve_fit`.
3. Report parameter values, 1-sigma errors, 95% intervals, covariance, and
   correlation structure.
4. Compute chi-squared, reduced chi-squared, RSS, RMSE, R-squared, AIC, AICc,
   and BIC.
5. Search for a better contiguous fit window when the full dataset is not well
   described by a single model.
6. Search for a two-segment solution and compare it against the best single-fit
   model.
7. Write a Markdown report, JSON results, and a detailed styled fit figure that
   shows the data, the chosen fit or fits, residual structure, and model
   comparison diagnostics.

## Dependencies

Install the dependencies before running the script:

```bash
pip install -r <SKILL_PATH>/requirements.txt
```

If the user only needs CSV or TSV input, `pandas` and `openpyxl` are less
important, but `numpy`, `scipy`, and `matplotlib` are required for the full
workflow.

## Core workflow

### 1. Identify the dataset and columns

Work out:

- the input file path
- the `x` column
- the `y` column
- the uncertainty column if one exists, usually `sigma_y`, `y_err`, or similar
- the physical meaning and units of the data

If uncertainties are missing, do not pretend reduced chi-squared is physically
meaningful. You may still fit the data and compare models, but state clearly
that chi-squared-based diagnostics are only heuristic unless the uncertainties
are credible.

### 2. Decide on the candidate models

Prefer physics-informed functions when the domain strongly suggests one. If the
user does not already know the right model, use the script's built-in library
to compare plausible candidates such as:

- `linear`
- `quadratic`
- `cubic`
- `exponential`
- `power_law`
- `gaussian`
- `lorentzian`
- `saturation`
- `sigmoid`

Compare models on the same range before claiming one is globally better.

### 3. Run the analysis

Typical command:

```bash
python <SKILL_PATH>/scripts/analyze_curve_fit.py \
  <data-file> \
  <output-dir> \
  --x-column <x-col> \
  --y-column <y-col> \
  --sigma-column <sigma-col> \
  --auto-range \
  --piecewise
```

Useful variants:

- If the user supplies a constant uncertainty:

```bash
python <SKILL_PATH>/scripts/analyze_curve_fit.py \
  <data-file> \
  <output-dir> \
  --x-column <x-col> \
  --y-column <y-col> \
  --sigma-value 0.05 \
  --auto-range \
  --piecewise
```

- If the data should only be considered over a known manual window:

```bash
python <SKILL_PATH>/scripts/analyze_curve_fit.py \
  <data-file> \
  <output-dir> \
  --x-column <x-col> \
  --y-column <y-col> \
  --x-min 10 \
  --x-max 80 \
  --auto-range \
  --piecewise
```

- If the model family should be restricted:

```bash
python <SKILL_PATH>/scripts/analyze_curve_fit.py \
  <data-file> \
  <output-dir> \
  --x-column <x-col> \
  --y-column <y-col> \
  --models linear,quadratic,exponential
```

### 4. Interpret the outputs

The script writes:

- `fit_report.md`
- `fit_results.json`
- `best_fit_curve.csv`
- `piecewise_fit_curve.csv` when a two-segment solution is found
- `fit_summary.png` when `matplotlib` is available
  This should be treated as a presentation-quality figure, not a token plot. It
  includes the data, fit overlays, residuals, model comparison, selected fit
  range, and recommendation summary.

Use the report, but still apply judgment. The lowest BIC is not enough on its
own if:

- the residuals still show structure
- the parameters are physically nonsensical
- the covariance matrix is ill-conditioned
- the chosen range is too narrow to answer the user's real question

### 5. Report the result cleanly

When responding to the user, cover these points in order:

1. Dataset summary and assumptions.
2. Models compared and why they were considered.
3. Best single-fit result with parameter values and uncertainties.
4. Chi-squared, reduced chi-squared, degrees of freedom, and model-selection
   metrics.
5. Whether a narrower fit range was selected and why.
6. Whether a piecewise or two-regime fit is strongly preferred.
7. Any caveats, especially about missing or assumed uncertainties.

### 6. Always produce a useful plot

The plot is part of the deliverable. Do not stop at a table of fit parameters.
When `matplotlib` is available, make sure the user gets a figure that is worth
looking at:

- show the measured data clearly, with uncertainty bars when available
- overlay the winning fit and any comparison fits that matter
- make the selected fit range visible if the range was narrowed
- show the breakpoint if a two-regime fit is recommended
- include residual diagnostics so the user can see whether structure remains
- keep the styling readable and intentional rather than default-looking

The user should be able to inspect the figure and understand not just what fit
won, but why.

## How to reason about fit range selection

The script's automatic range search is meant to help, not replace judgment.
Use it when:

- edge effects or saturation distort an otherwise good model
- only one region is expected to follow a particular law
- the dataset combines a transient region and a steady-state region

Do not silently exclude data. Explain why the selected range is better. Good
reasons include:

- instrument floor or clipping at one end
- known onset of saturation
- a visible regime change
- contamination by startup or cooldown behaviour

## How to reason about two-regime fits

Ask whether the data appears to have:

- a kink or breakpoint
- one model in the low-`x` region and another in the high-`x` region
- a transition from linear to saturation
- a peak region plus background

When the two-segment search is enabled, treat it as evidence, not proof. Report
the suggested breakpoint and compare the piecewise result against the best
single-fit result. A piecewise fit is most convincing when:

- BIC improves substantially
- reduced chi-squared improves substantially
- residual structure disappears
- the breakpoint matches a physically plausible transition

## Uncertainty and reduced chi-squared discipline

Reduced chi-squared is only meaningful when the uncertainties are real standard
deviations for the measurements. Follow these rules:

- If the dataset contains a proper uncertainty column, use it and report that
  reduced chi-squared is meaningful.
- If the user provides a constant or fractional uncertainty model, say that the
  fit quality depends on that assumption.
- If no uncertainty model exists, say explicitly that reduced chi-squared is
  scale-dependent and should only be used heuristically.

Never present reduced chi-squared as authoritative when the uncertainty model is
invented after the fact.

## Extending the built-in models

If the built-in models are not appropriate, add or adapt a callable in
`scripts/analyze_curve_fit.py` rather than forcing the data into the wrong
family. Keep the same reporting logic so the user still gets covariance,
reduced chi-squared, and comparison metrics.

## Output expectations

The final answer to the user should usually include:

- the selected model or models
- the fitted parameter values in `value +/- 1 sigma` form
- reduced chi-squared and degrees of freedom
- a sentence about whether the fit range was narrowed
- a sentence about whether a two-regime fit is justified
- the location of the generated report and plot files
- an explicit mention that `fit_summary.png` contains the detailed visual
  diagnostics for the fit
