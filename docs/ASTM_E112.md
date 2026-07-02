# ASTM E112 — The Intercept Method, Explained

A self-contained reference to the standard this tool implements:
**ASTM E112-13, *Standard Test Methods for Determining Average Grain Size*.**

This document explains the metallurgical background, the governing equations, the
counting rules, and the statistics — and maps each requirement of the standard to
what the Grain Size Analyzer actually does. For the app-specific implementation
notes (grid geometry, persistence rules), see [METHODS.md](METHODS.md).

---

## 1. Overview & scope

ASTM E112 standardizes three families of methods for measuring the **average grain
size** of metallic (and structurally similar non-metallic) materials:

| Method | Principle | Character |
|---|---|---|
| **Comparison** | Match the microstructure against standard chart plates | Fast, subjective, ±0.5 G at best |
| **Planimetric (Jeffries)** | Count grains inside a known area | Measures N_A (grains/mm²) directly |
| **Intercept (Heyn / Abrams)** | Count grain-boundary crossings along test lines of known length | Measures the mean lineal intercept ℓ̄; fastest route to a stated statistical precision |

**This tool implements the intercept methods only**, in two grid variants:

- **Heyn lineal intercept** — arrays of straight test lines (E112 §13, §14.2);
- **Abrams three-circle intercept** — three concentric circles with diameters in
  a **1 : 2 : 3** ratio (E112 §14.3, Fig. 5), the primary grid in this app.

The core assumption of E112 is a **single-phase, equiaxed grain structure of
uniform size distribution**. The intercept method remains usable when that
assumption is bent:

- **Slightly deformed / non-equiaxed grains** — use test lines in multiple
  orientations (this is why the Heyn presets here span ≥ 4 orientations, §13.4)
  or a circular grid, which averages all orientations automatically.
- **Markedly elongated grains** — E112 §16 prescribes directed counts along the
  principal specimen axes; report directional ℓ values, not a single number.
- **Two-phase (duplex) structures** — E112 §17: measure the matrix phase only and
  do not count test-line segments that lie in the second phase (see §7 below).
  Heavily duplex structures are better served by ASTM E1181.

E112 measures a **planar (2-D section) grain size**. It does not measure the true
3-D grain volume distribution, and it characterizes the *average*: it is not an
individual-grain or largest-grain (ALA) method (that is ASTM E930).

---

## 2. Key definitions

- **Grain** — a region of a polycrystal with (nominally) one crystallographic
  orientation, bounded by grain boundaries. In etched micrographs a grain is the
  area enclosed by visible boundary lines.
- **Grain boundary** — the interface between two grains of different orientation.
  Etchants attack boundaries preferentially, rendering them as dark lines.
- **Twin boundary** — a special low-energy boundary (common as **annealing
  twins** in FCC metals) that appears as straight, parallel-sided bands inside a
  grain. Per E112 §3.2.2 the grain-size methods assume a **twin-free** structure:
  **twin boundaries are NOT counted** as grain-boundary intersections.
- **ASTM grain-size number, G** — a dimensionless logarithmic index of grain
  size. **Higher G = finer grains.** Defined originally from the number of grains
  per square inch at 100× magnification: `n = 2^(G−1)`.
- **Mean lineal intercept, ℓ̄** — the average distance between grain-boundary
  crossings along a random test line through the structure; equivalently the
  average length of line segment ("intercept") lying inside one grain. This is
  the fundamental quantity the intercept method measures.
- **Intercept vs. intersection** — an *intercept* is a line **segment** crossing
  one grain; an *intersection* is a **point** where the line cuts a boundary. For
  a single-phase structure counted on a **closed loop** (a circle) the two counts
  are identical; on a straight line they differ only by end effects. E112 lets
  you count either, with the tally rules of §14.3 making them equivalent.
- **Macro vs. micro designations ("00, 0, 1, 2 …")** — E112 defines both
  *micro* grain sizes (G, typically 00 to 14+, measured at ~100×) and *macro*
  grain sizes (M, for very coarse structures measured at ~1×). Both scales use
  the same doubling logic. The coarsest micro designations are written **"0"**
  and **"00"**, which correspond to G = 0 and G = −1 in the equations: **G can
  legitimately be negative** for very coarse material.

---

## 3. The grain-size number G and the governing equations

### 3.1 From mean lineal intercept to G

E112 Table 6 gives the relationship used throughout this app. With **ℓ̄ in
millimetres**:

```
G = −6.643856 · log10(ℓ_mm) − 3.288
```

(Equivalently `G = 6.643856 · log10(1/ℓ_mm) − 3.288`.) The constant
`6.643856 = 2 · log2(10)` comes directly from the doubling definition of G.

Properties worth internalizing:

- **+1 in G ≈ doubling of grains per unit area** (N_A doubles each unit of G).
- Because ℓ̄ scales as `N_A^(−1/2)`, **ℓ̄ halves for every 2 units of G**.
- **G may be negative** for coarse structures. G = 0 is designated "0" and
  G = −1 is designated **"00"** on the ASTM scale.
- The relation to grains per mm² (from the planimetric method) is
  `G = 3.321928 · log10(N_A) − 2.954`; for a uniform equiaxed structure the
  intercept and planimetric G values agree to within normal scatter.

### 3.2 Worked example

Suppose a field gives `N = 62` intersections on a circle grid of total length
`L_total = 1984 µm` (already in µm via the calibration `k` in µm/px):

```
ℓ    = L_total / N = 1984 / 62 = 32.0 µm
ℓ_mm = 0.0320 mm
G    = −6.643856 · log10(0.0320) − 3.288
     = −6.643856 · (−1.49485) − 3.288
     = 9.9316 − 3.288
     = 6.64
```

A 32 µm mean intercept is ASTM **G ≈ 6.6** — a moderately fine structure.

### 3.3 Reference values (from the Table 6 relation)

| G | ℓ̄ (µm) | ℓ̄ (mm) | Note |
|---:|---:|---:|---|
| −1 | 452.5 | 0.4525 | designation "00" — very coarse |
| 0 | 320.0 | 0.3200 | designation "0" |
| 1 | 226.3 | 0.2263 | |
| 3 | 113.1 | 0.1131 | |
| 5 | 56.6 | 0.0566 | |
| 7 | 28.3 | 0.0283 | |
| 10 | 10.0 | 0.0100 | ℓ̄ = 10 µm ⇔ G = 10.0 (a handy anchor) |
| 12 | 5.0 | 0.0050 | fine |

Note the ×2 in ℓ̄ for every −2 in G, and the coincidence that **G = 10
corresponds to exactly ℓ̄ = 10 µm**, a convenient sanity check.

---

## 4. The intercept methods in detail

### 4.1 Heyn lineal intercept (straight lines)

One or more straight test lines of known total length are laid over the
micrograph and every point where a line crosses a grain boundary is counted.
Then `ℓ = L_total / N`.

Practical points from E112:

- **Orientation bias (§13.4).** A single line direction over-samples one
  orientation; on anything but perfectly equiaxed grains this biases ℓ. E112
  §13.4 therefore recommends test-line arrays spanning **at least four
  orientations**, with the lines crossing at *scattered* points — a grid whose
  lines all radiate from one common point is explicitly prohibited, because the
  region around that point would be massively over-weighted. (This app's
  **4-dir** and **4×4+diag** Heyn presets exist precisely to satisfy §13.4.)
- **End effects.** A straight line generally starts and ends *inside* a grain,
  so the two partial end segments are not full intercepts. E112 handles this
  with the ½-count rule (see §4.3): a line end falling exactly on a boundary
  scores ½. For long lines with many crossings the end correction is small, but
  it never fully vanishes — which motivates circular grids.

### 4.2 Abrams three-circle intercept (the referee grid)

H. Abrams (1971) introduced a grid of **three concentric circles with diameters
in the ratio 1 : 2 : 3** — canonically Ø 26.53 : 53.05 : 79.58 mm, chosen so the
total circumference is 500 mm — standardized as E112 **Fig. 5** and procedure
§14.3. The total test length is simply the summed circumferences:

```
L_circle = 2π · (r1 + r2 + r3)
```

Why closed circles beat straight lines:

- **No orientation bias.** A circle points in every direction at once; every
  boundary orientation is sampled with equal weight, so no multi-orientation
  averaging is needed even for moderately non-equiaxed structures.
- **No end points.** A closed loop has no ends, so the ½-count end correction
  disappears entirely: every crossing is a clean, unambiguous count of 1 (with
  the tangency/triple-point rules below).
- **Statistically efficient.** Abrams showed the three-circle count converges to
  a reliable mean with a near-Gaussian field-to-field distribution, so the
  standard **Student's-t confidence-interval machinery of E112 §15 applies
  directly**. Three circles supply enough line length to land in the desired
  40–100 intercepts per field for typical structures at a sensible
  magnification.

For these reasons the three-circle grid is E112's **preferred procedure when a
specified statistical precision must be demonstrated**, and it is commonly used
as the referee method in disputes. It is the primary grid in this app; the Heyn
lines serve as an independent cross-check on the same field.

### 4.3 Counting conventions (E112 §14.3)

These are the click rules a manual operator must follow. All are implemented as
*operator* conventions in this tool — the app counts exactly what you click.

| Event on the test line | Count | E112 basis |
|---|---:|---|
| Clean crossing of a grain boundary | 1 | §14.3 |
| Line **tangent** to a boundary (touches without crossing) | **1** | §14.3 / §3.2.3 |
| End of a **straight** test line falling **exactly on** a boundary | **½** | §14.3 (never arises on a circle) |
| Line passing through a **triple point** (three grains meet) | **1½**; or, per the §14.3.2.2 simplification, count as **2** | §14.3.2.2 |
| Segment lying inside a **second phase** (duplex structure) | excluded — count only matrix boundary crossings and use only the matrix line length | §17 |
| **Twin boundary** crossing | **0** — not counted | §3.2.2 |

The §14.3.2.2 note observes that scoring a triple point as 2 rather than 1½
introduces negligible bias (triple-point encounters are rare relative to plain
crossings) while making the tally much simpler — this is the convention the
app's documentation recommends for circle counts.

---

## 5. Calibration (µm/px)

The intercept computation needs the test-line length in real units. The app
draws the grid in **pixels** and converts with a per-image calibration factor
`k` in **µm/px**:

```
L_total (µm) = L_grid (px) · k
```

Acceptable sources for `k`, in order of preference:

1. **Microscope objective calibration** — the calibration the acquisition
   software applies for that objective/camera pair, itself traceable to a
   certified **stage micrometer** (ASTM E1951 governs scale-bar and
   magnification calibration).
2. **Stage micrometer imaged directly** — photograph the micrometer at the same
   objective and compute µm/px from a known interval.
3. **Burned-in scale bar** — if the image carries a scale bar rendered by the
   acquisition software, click its two ends and divide the known length by the
   pixel distance (the app's scale-bar calibration tool does exactly this).

Magnification itself must be trusted only through such a calibration — nominal
objective magnifications can be off by a few percent, which propagates linearly
into ℓ and hence directly into G (a 5 % length error shifts G by ≈ 0.14).

**Why per-image calibration matters:** a research database accumulates images
from different objectives, cameras, and instruments. If `k` were global, mixing
a 50× field with a 100× field would silently corrupt every ℓ. This app stores
`k` **per image**, so mixed magnifications coexist safely, and a recalibration
is a pure unit conversion that exactly rescales stored ℓ and G.

---

## 6. Sampling & statistics (E112 §14–§18)

### 6.1 How much to count

- **Per field:** aim for **40–100 intercepts** (§14.3.2.1). Below ~40 the
  per-field estimate is noisy; above ~100 you are spending effort that would be
  better invested in an additional field. If a field yields too few counts,
  **change the magnification or add fields — never distort the grid** (this app
  locks the circle grid to the canonical pattern for exactly this reason).
- **Overall:** measure **at least 5 fields**, selected blindly at well-separated
  locations on the specimen, for a total of roughly **400–500 intercepts**.
  This is normally enough to bring the relative accuracy inside 10 %.

### 6.2 The statistics, step by step

For the *n* fields measured on one condition, with per-field mean intercepts
ℓ_1 … ℓ_n:

```
mean:                ℓ̄  = ( Σ ℓ_i ) / n                          (§15.2)
sample std. dev.:    s  = sqrt[ Σ (ℓ_i − ℓ̄)² / (n − 1) ]         (§15.3)
95 % conf. interval: CI = t · s / sqrt(n)                         (§15.4)
relative accuracy:   %RA = 100 · CI / ℓ̄                          (§15.5)
```

where `t` is **Student's t at 95 % confidence for n − 1 degrees of freedom**,
taken from E112 **Table 7** — *not* the normal-distribution 1.96, which is only
the n → ∞ limit:

| n (fields) | dof (n−1) | t (95 %) |
|---:|---:|---:|
| 5 | 4 | 2.776 |
| 6 | 5 | 2.571 |
| 7 | 6 | 2.447 |
| 8 | 7 | 2.365 |
| 9 | 8 | 2.306 |
| 10 | 9 | 2.262 |
| 15 | 14 | 2.145 |
| 20 | 19 | 2.093 |
| ∞ | ∞ | 1.960 |

### 6.3 Acceptance and reporting rules

- **%RA ≤ 10 % is the E112 target** (§15.6). If %RA exceeds 10 % and higher
  precision is required, measure more fields and recompute. The app colours %RA
  green when ≤ 10 % and amber otherwise.
- **≥ 5 fields for a valid CI** (§14.3.2). With fewer than 5 fields the t
  multiplier explodes (t = 4.30 at n = 3, 12.7 at n = 2) and the CI is not
  meaningful; the app flags any condition with < 5 measured fields.
- **G is computed from the mean ℓ̄ — never by averaging per-field G values**
  (§18.7). Because G is logarithmic in ℓ, `mean(G(ℓ_i)) ≠ G(mean(ℓ_i))`;
  averaging G values biases the result. The app shows per-field G live for
  orientation, but every per-condition (summary/exported) G is computed from
  ℓ̄ via the Table 6 relation.
- Report G to the nearest tenth, together with ℓ̄, n, the 95 % CI, and %RA, and
  state the method (three-circle intercept / lineal intercept) and
  magnification (§18).

---

## 7. Special cases & pitfalls

- **Annealing twins (§3.2.2).** The most common counting error in FCC metals
  (also present in Mg alloys as deformation twins). Twin boundaries are
  straight, often parallel-sided, and terminate *inside* grains — **do not
  click them**. Counting twins can inflate N by 50 % or more, understating ℓ
  and overstating G by a full unit or worse.
- **Two-phase / duplex structures (§17).** Measure the **matrix** phase:
  exclude second-phase particles/islands from the count and subtract the
  test-line length that lies within them. If the second phase is a minor
  dispersion of small particles, its effect on the line length is negligible
  and it can simply be ignored (don't count particle interfaces).
- **Elongated / worked grains (§16).** Rolling, extrusion, or directional
  solidification produce grains with an aspect ratio. A single-direction Heyn
  count gives a direction-dependent ℓ. Either use the orientation-averaging
  circle grid for an overall size, or make **directed counts along and across
  the working direction** and report both (E112 defines the anisotropy index
  from these).
- **Banded structures.** Alternating fine/coarse (or two-phase) bands violate
  the uniformity assumption; place fields to sample bands representatively, or
  report the bands separately (see also ASTM E1268 for banding).
- **Unetched or faint boundaries.** Every boundary the etch fails to reveal is
  a missed intersection: N drops, ℓ inflates, and G reads low. Re-etch rather
  than guess. (The app's brightness/contrast/invert controls help legitimate
  faint-boundary cases, but they cannot conjure an unrevealed boundary.)
- **Scratches, comet tails, etch pits.** Preparation artifacts that cross the
  test line must not be counted; distinguishing them from true boundaries is a
  judgment call an operator makes routinely.

### Why manual counting (vs. automated segmentation)

Automated thresholding/skeletonization (the ASTM E1382 route) is fast but
fragile on real etched surfaces: **scratches, twins, and uneven etch response
all look like grain boundaries to an algorithm**, causing systematic
over-counting, while faint true boundaries are dropped. E1382 consequently
demands extensive image-quality qualification. A trained human simply does not
click a twin or a scratch. This tool keeps the human decision (is this a real
boundary?) and automates everything error-prone around it: grid geometry, line
lengths, unit conversion, the ℓ→G transform, and the §15 statistics.

---

## 8. How this tool implements E112

| E112 requirement | Where | What the app does |
|---|---|---|
| Intercept method, circle grid | §14.3, Fig. 5 | **Abrams three-circle** grid, diameters locked to the canonical **1 : 2 : 3** ratio, centred on the frame |
| Intercept method, straight lines, ≥ 4 orientations | §13.4 | **Heyn presets** (3×3/4×4/5×5 + diagonal variants) spanning ≥ 4 orientations, crossing at scattered points |
| Known test-line length in real units | §13, E1951 | Grid length in px × **per-image µm/px** calibration; scale-bar click-to-calibrate tool |
| ℓ from intersection count | §14.3 | Live `ℓ = L_total(µm) / N` recomputed on every click |
| G from ℓ̄ (Table 6) | Table 6 | `G = −6.643856·log10(ℓ_mm) − 3.288`, shown live per field |
| 40–100 intercepts per field | §14.3.2.1 | N readout turns amber below the recommended per-field count |
| ≥ 5 fields, ~400–500 intercepts | §14.3.2 | Per-condition summary **flags < 5 fields** |
| Mean, sample SD | §15.2–15.3 | ℓ̄ and s (n−1 denominator) per condition |
| 95 % CI with Student's t | §15.4, Table 7 | `CI = t·s/√n` with t looked up for the actual n — never a fixed 1.96 |
| %RA ≤ 10 % target | §15.5–15.6 | `%RA = 100·CI/ℓ̄`, colour-coded against the 10 % target |
| G from the mean, never averaged | §18.7 | Summary/export G always computed from ℓ̄ |
| Auditability | good practice | Full-resolution **overlay PNG export** (grid + clicked marks) per image, so every count can be re-checked |

Two-phase handling, twin exclusion, and artifact rejection are operator
responsibilities under §17 and §3.2.2 — the app records exactly the crossings
you click, which is the point of a manual method.

---

## 9. References

1. **ASTM E112-13**, *Standard Test Methods for Determining Average Grain
   Size*, ASTM International, West Conshohocken, PA, 2013 (reapproved 2021),
   DOI: 10.1520/E0112-13.
2. H. Abrams, "Practical Applications of the Three-Circle Intercept Grain Size
   Method," *Metallography*, Vol. 4, 1971, pp. 59–78 (related development in
   *Metallurgical Transactions*, 1971).
3. **ASTM E1382**, *Standard Test Methods for Determining Average Grain Size
   Using Semiautomatic and Automatic Image Analysis*, ASTM International —
   the automated counterpart, deliberately **not** used by this tool.
4. G. F. Vander Voort, *Metallography: Principles and Practice*, ASM
   International, Materials Park, OH, 1999 — the standard practical text on
   specimen preparation, etching, and grain-size measurement.

Related standards mentioned above: ASTM E930 (largest grain, ALA), ASTM E1181
(duplex grain sizes), ASTM E1268 (banding), ASTM E1951 (magnification and
scale-bar calibration).

> **Disclaimer.** This document summarizes ASTM E112 for users of this
> open-source tool. It is **not** a substitute for purchasing and reading the
> official standard, which contains the authoritative procedures, tables, and
> precision statements. The equations and constants used here follow the
> published E112 Table 6 mean-lineal-intercept relation; section numbers refer
> to E112-13.
