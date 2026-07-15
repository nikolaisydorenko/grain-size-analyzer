# User Guide — measuring grain size

This guide walks through producing report-grade grain-size numbers with the
analyzer. It assumes the app is running and your micrographs are loaded
(see the README for cache preparation and import).

---

## 1. Before you click — what counts as a boundary

The method only works if you click **grain boundaries** and nothing else.

| Feature | Looks like | Click it? |
|---|---|---|
| **Grain boundary** | Continuous dark line separating two differently-shaded grains | ✅ Yes |
| **Annealing twin** | Straight, parallel lines *inside* one grain; the two sides have the same orientation/shade | ❌ No |
| **Scratch / polishing line** | Very straight, often spans many grains, ignores boundaries | ❌ No |
| **Etch pit / stain** | Spot or blotch, not a line | ❌ No |
| **Second-phase network** (two-phase alloys) | Fine constituent along/within grains | ⚠️ Decide a rule and keep it (see §6) |

This judgement is the entire reason the measurement is done by hand. When unsure,
**zoom in** (`＋`), use the **🔍 Loupe** for a magnified view at the cursor, or boost
**contrast / invert** in the adjustment bar to make a faint boundary pop.

### Tools that make counting easier
- **Image adjustments** (bar under the toolbar): **brightness**, **contrast**, and
  **invert** change only the display, never the saved data — use them to see faint
  boundaries, then **reset**.
- **🔍 Loupe** — toggles a magnifier that follows the cursor for precise clicks.
- **✥ Move circles** — repositions the Abrams circle grid on this image (for
  off-centre micrographs): toggle it, drag the circles where you want them, then
  toggle off (or press `Esc`). The position is saved per image and used in overlay
  exports. Moving the grid never changes the test-line length, so ℓ and G are
  unaffected — but if you've already counted marks on the old position, clear and
  recount. **⌖ Centre** resets to the image centre. (Circle method only — the Heyn
  lines always span the full frame.)
- **snap to grid** — when on, each click lands exactly on the nearest circle/line.
- **Right-click a mark** to delete just that one (vs. `Z`/Undo which removes the last).
- **Middle-mouse drag** pans when you're zoomed in; **⤢ Fit** returns to whole-frame.
- **Grid** — the circle grid is fixed to the canonical **Abrams three-circle**
  pattern (ASTM E112 Fig. 5), so every field is traceable to the named procedure.
  If a coarse field gives < 40 intercepts, use lower magnification or count more
  fields (§14.3.2.1). The **line** grid is selectable: for non-equiaxed (elongated)
  structures use the **4-dir** or **4×4+diag** presets — they add the two frame
  diagonals so the lines span ≥ 4 orientations (§13.4).
  **Important:** changing the grid affects new counting only. Fields you already
  counted keep the grid they were measured on — the image shows a
  "⚠ counted on a previous grid" badge; use **Clear** and recount to move a field
  onto the new grid.

---

## Organizing with folders

The left sidebar is a **collapsible folder tree**. It starts with one folder per
condition, but you can organize however you like:

- **＋ Folder** (top of the sidebar) — create a new, named folder (e.g. a casting
  batch, a date, an etch condition). Nested folders are supported (hover a folder
  for **＋ subfolder**).
- **Click a folder row** to expand/collapse it; the count shows how many images it holds.
- **Hover a folder** for **✎ rename** and **🗑 delete**. Deleting a folder is safe —
  its images move back to their condition group; the images themselves are not deleted.
- **Move an image** — drag it onto a folder, or use the **Move to…** dropdown in the
  image header. **Ctrl/Shift-click** selects several images for batch move/delete.

Folder assignments are organizational only — each image keeps its **condition**
(which drives the summary statistics), independent of which folder it lives in.

## 2. The workflow

1. **Select an image** from the left sidebar; the dot is green once a field is
   marked done. Use the filter box to jump around.
2. **Choose a method** with the tabs at the top:
   - **◎ Abrams circles** — the primary, recommended method.
   - **▤ Heyn lines** — straight-line cross-check.
3. **Click every crossing.** Walk along each red circle (or line) and click each
   point where it crosses a real grain boundary. A green dot marks each click.
   - **Undo** the last click: toolbar `↶` or press `Z`.
   - **Clear** the whole image: toolbar `✕`.
4. **Watch the live stats** under the image:
   - **N** — intercept count. It shows **amber below 40** (the ASTM E112 §14.3.2.1
     floor; 40–100 per placement is the target range).
   - **ℓ** — mean intercept length in µm.
   - **G** — ASTM grain-size number.
   - **Test length** — the fixed total grid length used in the math.
5. **Mark done & next** (toolbar `✓` or press `D`) to flag the field complete and
   jump to the next image.
6. Repeat across **several fields per condition** (see §4).

Every click auto-saves — you can close the tab and resume later.

---

## 3. Reading the results

The **Per-condition summary** table at the bottom updates live:

| Column | Meaning |
|---|---|
| Condition | the free-text group label the images were imported under |
| Value | the optional numeric value for the condition (orders the table; blank if unset) |
| Fields | number of images measured for that condition |
| Σ Intercepts | total boundary crossings counted |
| ℓ (µm) | mean intercept length across fields |
| ± SD | standard deviation between fields |
| ± 95% CI | 95 % confidence interval of the mean |
| %RA | percent relative accuracy (target ≤ 10 %) |
| G | ASTM grain-size number from the mean ℓ |

Conditions with a **Value** sort numerically; those without sort alphabetically
after them. The table follows the active method tab, so you can compare the circle
and line results side by side by switching tabs.

---

## 4. How many fields and intercepts?

ASTM E112 guidance, applied here:

- **40–100 intercepts per field.** If a field can't reach 40 (coarse structures),
  that's fine — measure more fields and let the average carry it. The amber **N**
  is your reminder.
- **≥ 5 fields per condition** for a reportable mean; more for coarse or
  heterogeneous structures. The 95 % CI tightens as you add fields — use it to
  decide when you have enough.

---

## 5. Importing, calibrating, deleting

### Import a new photo
Use the **＋ Import photo** panel (bottom-left):

1. Choose the image file(s) (JPEG or TIFF — TIFFs are auto-converted for display).
   RAW files are not supported; export a JPEG/TIFF from your camera or microscope
   software first.
2. Type the **Condition** — a free-text label that groups the images in the summary
   (e.g. `as-cast`, `annealed-300C`, `sample A`). Existing labels are suggested as
   you type.
3. Optionally set the **Value** — a number associated with the condition
   (temperature, composition, time…). It orders the summary and becomes the chart
   X-axis. Leave it blank if it doesn't apply.
4. Set **µm/px**. The default `1.0` means **uncalibrated** — if you know the scale
   from your microscope calibration, enter it here; otherwise import and use the
   scale-bar tool below. Calibration is stored per image.
5. Pick a **Folder** (or leave "(same as condition)").
6. **Upload & open** — it appears in the list, ready to measure.

You can change an image's condition later with the condition box in the image
header.

### Calibrate from a scale bar
If you don't know µm/px, derive it from a burned-in scale bar:

1. Open the image, click **📏 Calibrate scale** in the toolbar.
2. Click the **two ends of the scale bar** (an amber line is drawn; the pixel length
   shows live).
3. Enter the bar's **known length** in µm. The computed **µm/px** updates live.
4. Choose **apply to**: *this image*, *this condition*, or *all images* — then
   **Apply**. Any existing ℓ/G for affected images recompute automatically.

### Delete an image
Open the image and click **🗑 Delete** in the image header. This removes the photo
and its measurements (with a confirmation) — use it for mis-imported or duplicate
fields.

---

## 6. Two-phase alloys

When a second phase forms a network, decide **once** what you are measuring and stay
consistent across all fields and conditions:

- **matrix grain size** — click only the boundaries between matrix grains, ignore
  the constituent network; or
- **overall structure** — click every boundary including phase boundaries.

State your choice in your methods section. Mixing the two between fields invalidates
the comparison. (Per ASTM E112 §17.1, grain size in a two-phase structure normally
means the matrix phase.)

---

## 7. Exporting

- **⬇ CSV** — a per-image CSV of every measurement (all methods):
  `condition, value, image, method, n_intercepts, umpp, test_len_um, l_um, ASTM_G, done`.
- **⬇ XLSX + chart** — a workbook with the per-condition summary, a per-image
  sheet, and a native grain-size chart (mean ℓ with 95 % CI error bars; X-axis is
  the Value when every condition has one, otherwise the condition labels).
- **🖼 Overlay** (image header) — a full-resolution PNG of the current image with
  the test grid and your clicked marks drawn on it.
- **🖼 Overlays** (toolbar) — a **zip of overlays** for every measured image in the
  current method. Drop these in a report appendix to show the counts are real.

### Backups
The complete state is the `grainsize.duckdb` file plus the `cache/` folder — copy
both to back up a project.
