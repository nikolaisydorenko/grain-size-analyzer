# Methods — ASTM E112 intercept grain sizing

Technical notes on what the analyzer computes and the standards it follows.

## Mean lineal intercept (ℓ)

A test line of known length `L` is superimposed on the microstructure and the number
of intersections with grain boundaries, `P`, is counted. The mean lineal intercept
length is

```
ℓ = (L · k) / P
```

where `k` is the calibration in **µm/pixel** and `L` is the test-line length in
**pixels**. In the app, `N` denotes the user's clicked intersection count (`P`), and
`L · k` is reported as **Test length** in µm.

## ASTM grain-size number (G)

ASTM E112 relates the mean lineal intercept in **millimetres** to the dimensionless
grain-size number:

```
G = −6.643856 · log10(ℓ_mm) − 3.288
```

`G` increases with decreasing grain size; an increase of 1 corresponds to roughly a
doubling of the number of grains per unit area. This is the form used throughout the
app and in the CSV/XLSX exports.

## Test grids

### Abrams three-circle (primary, the E112 referee grid)

Three concentric, **equally-spaced** circles centred on the usable field, radii at
15 %, 30 %, and 45 % of the usable image height — i.e. radii in the **canonical
Abrams 1 : 2 : 3 ratio** (ASTM E112 Fig. 5, Ø 26.53 : 53.05 : 79.58 mm). Total
circumference:

```
L_circle = 2π (r1 + r2 + r3)
```

For example, on a 1920 × 1200 px image at `k = 1.0 µm/px` this is ≈ 6,786 µm; the
value scales linearly with the calibration.

Counting rules (E112 §3.2.3, §14.3.2.2): a grain-boundary tangency counts as 1; a
triple-junction is scored as 2 (ASTM-sanctioned simplification). Circles have no
end-points, so there is no half-intercept end correction.

Rationale: a closed circle samples all orientations equally (removing the
directional bias of straight lines) and has no end-points. Three circles provide
enough length to reach 40–100 intercepts in a single field for typical structures.
The circle grid is locked to the canonical three-circle pattern; to raise the
per-field count on coarse structures, use lower magnification or more fields
(§14.3.2.1) — never a non-standard circle count.

### Heyn lineal (cross-check)

Line presets: **3×3**, **4×4**, **5×5** (horizontal + vertical arrays), plus
**4-dir** and **4×4+diag**, which add the two full-frame diagonals so the array
spans **≥ 4 line orientations** as ASTM E112 §13.4 recommends for structures that
depart from equiaxed (the lines cross at scattered points, not a common centre,
respecting the §13.4 prohibition on grids radiating from one point).

### Grid changes never rescale existing counts

An intercept count is only valid against the grid it was counted on, so every saved
measurement **freezes its test length at click time**. Changing the grid density
affects the drawing (and future counts) only; a field counted on a different grid
shows a "counted on a previous grid" badge and should be cleared and recounted to
migrate. The one exception is a **µm/px recalibration**, which is a pure unit
conversion and rescales stored ℓ/G exactly.

## Full-frame grid

The test grid always uses the **full image frame**, centred on the true image centre
(no scale-bar margin). If an image has a burned-in scale bar in the corner, the outer
circle may clip it slightly — the effect on a coarse intercept count is negligible; if
it matters, crop the bar out of the source image before importing.

## Statistics (ASTM E112 §15, §18)

Per condition, over the *n* fields measured, the app reports exactly what E112
requires:

- **mean ℓ̄** = Σℓ_i / n (§15.2),
- **sample standard deviation** s = √[Σ(ℓ_i − ℓ̄)² / (n−1)] (§15.3, `STDDEV_SAMP`),
- **95 % confidence interval** `95%CI = t · s / √n` using **Student's t** (Table 7;
  e.g. t = 2.776 at n = 5, → 1.96 only as n → ∞) — *not* a fixed 1.96 (§15.4),
- **percent relative accuracy** `%RA = (95%CI / ℓ̄) · 100`; **target ≤ 10 %** (§15.6) —
  the app colours it green/amber and flags fewer than 5 fields,
- **G computed from the mean ℓ̄** via Table 6 — **never** by averaging per-field G
  numbers (§18.7).

A valid CI needs **≥ 5 fields** (§14.3.2); aim for a total of ~400–500 intercepts.
The per-image G shown live (and in the CSV) is the individual field value; the
per-condition G in the summary is computed from the mean ℓ̄.

## Calibration

`k` (µm/px) comes from the objective's calibration in your microscope software, or
can be derived in-app from a burned-in scale bar with the 📏 calibration tool (click
the two ends of the bar, enter its known length). The shipped default of
`1.0 µm/px` is a placeholder meaning **uncalibrated** — set the real scale before
trusting any ℓ or G value. Calibration is stored **per image**
(`cache/index.json`), so images from different magnifications/instruments can
coexist in one database; a recalibration is a pure unit conversion and rescales
stored ℓ/G exactly.

## Standards & sources

- **ASTM E112-13** — *Standard Test Methods for Determining Average Grain Size.*
- H. Abrams (1971) — three-circle intercept procedure.
- **ASTM E1382** — image-analysis grain sizing (for context; not used here, by design).
- G. F. Vander Voort — *Metallography: Principles and Practice* (ASM).
