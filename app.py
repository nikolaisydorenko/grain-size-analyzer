#!/usr/bin/env python3
"""
Grain Size Analyzer — manual intercept grain sizing per ASTM E112.
Two selectable methods (tabs):
  - circle : Abrams three concentric circles (orientation-averaged)
  - line   : Heyn straight lines (4 horizontal + 4 vertical)
Both: l = total test-line length (um) / number of boundary crossings clicked.
Per-image calibration (um/px); default 1.0 (uncalibrated) — set the real scale at
import or with the in-app scale-bar tool. Images are grouped by a free-text
"condition" label with an optional numeric "value" for ordering/charting.
Results persist in DuckDB; exports: CSV, XLSX + native chart, annotated overlays.
"""
import os, json, math, csv, io, datetime, threading
import duckdb
from PIL import Image, ImageDraw
from werkzeug.utils import secure_filename
from flask import Flask, jsonify, request, send_file, Response, render_template_string, abort

ROOT        = os.path.dirname(os.path.abspath(__file__))
CACHE       = os.path.join(ROOT, "cache")
INDEX_PATH  = os.path.join(CACHE, "index.json")
DB_PATH     = os.environ.get("GRAINSIZE_DB", os.path.join(ROOT, "grainsize.duckdb"))
PORT        = int(os.environ.get("PORT", "5066"))
DEFAULT_UMPP = 1.0
# selectable test-grid densities (to reach the ASTM 40-100 intercepts per placement)
# Locked to the canonical ASTM E112 Abrams THREE-circle grid (radii 1:2:3, equally
# spaced, Fig. 5). Non-standard 2- and 4-circle presets were removed 2026-07-02 so
# every measurement is traceable to the named procedure. For coarse structures use
# more fields or lower magnification (s14.3.2.1), never more circles.
CIRCLE_PRESETS = {"3": (0.15, 0.30, 0.45)}
# Student's t (two-sided 95%, dof = n-1) per ASTM E112 Table 7 (extended)
T_TABLE = {2:12.706,3:4.303,4:3.182,5:2.776,6:2.571,7:2.447,8:2.365,9:2.306,
           10:2.262,11:2.228,12:2.201,13:2.179,14:2.160,15:2.145,16:2.131,
           17:2.120,18:2.110,19:2.101,20:2.093,21:2.086,22:2.080,23:2.074,
           24:2.069,25:2.064,26:2.060,27:2.056,28:2.052,29:2.048,30:2.045}
def t_mult(n):
    if n < 2: return 0.0
    if n in T_TABLE: return T_TABLE[n]
    return 2.04 if n <= 40 else (2.00 if n < 120 else 1.96)
# Heyn line grids. h/v = fractional positions; diag=True adds the two full-frame
# diagonals, giving >=4 line orientations per ASTM E112 s13.4 (the lines cross at
# scattered points, not a common centre, per the s13.4 "radiating" prohibition).
LINE_PRESETS = {
    "3x3":     {"h": (0.30, 0.50, 0.70), "v": (0.30, 0.50, 0.70)},
    "4x4":     {"h": (0.30, 0.45, 0.60, 0.70), "v": (0.25, 0.40, 0.60, 0.75)},
    "5x5":     {"h": (0.18, 0.34, 0.50, 0.66, 0.82), "v": (0.16, 0.32, 0.50, 0.68, 0.84)},
    "4-dir":   {"h": (0.30, 0.70), "v": (0.30, 0.70), "diag": True},
    "4x4+diag":{"h": (0.30, 0.45, 0.60, 0.70), "v": (0.25, 0.40, 0.60, 0.75), "diag": True},
}

app = Flask(__name__)
# 300 MB: full-resolution 16-bit TIFF exports from a DSLR can reach ~140 MB; a
# lower cap rejected them with an HTML 413 the upload UI couldn't parse.
app.config["MAX_CONTENT_LENGTH"] = 300*1024*1024
_DB_WRITE_LOCK = threading.Lock()

@app.errorhandler(413)
def too_large(e):
    mb = app.config["MAX_CONTENT_LENGTH"] // (1024*1024)
    return jsonify(ok=False, error=f"file is larger than the {mb} MB upload limit — "
                   "export a JPEG (or a smaller TIFF) and re-import"), 413
FOLDERS_PATH = os.path.join(CACHE, "folders.json")
INDEX = json.load(open(INDEX_PATH)) if os.path.exists(INDEX_PATH) else []

for d in INDEX:                                # back-fill calibration + grouping + folder
    d.setdefault("umpp", DEFAULT_UMPP)
    d.setdefault("condition", "")
    d.setdefault("value", None)
    d.setdefault("folder", d["condition"] or "Ungrouped")
    d.pop("mask", None)                        # scale-bar margin removed — always full frame
BYNAME = {d["name"]: d for d in INDEX}

def load_folders():
    if os.path.exists(FOLDERS_PATH):
        return json.load(open(FOLDERS_PATH))
    def _key(d):                               # seed from conditions, value-ordered
        v = d.get("value")
        return (v is None, v if v is not None else 0.0, d["folder"])
    order = []
    for d in sorted(INDEX, key=_key):
        if d["folder"] not in order:
            order.append(d["folder"])
    return order

FOLDERS = load_folders()

GRID_PATH = os.path.join(CACHE, "grid.json")
def load_grid():
    g = {"circles": "3", "lines": "4x4"}
    if os.path.exists(GRID_PATH):
        try: g = {**g, **json.load(open(GRID_PATH))}
        except Exception: pass
    g["circles"] = "3"          # circle grid is locked to canonical Abrams
    return g
GRID = load_grid()

def save_index():
    json.dump(INDEX, open(INDEX_PATH, "w"))

def save_folders():
    json.dump(FOLDERS, open(FOLDERS_PATH, "w"))

def save_grid():
    json.dump(GRID, open(GRID_PATH, "w"))

def db():
    con = duckdb.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS intercepts(
        name VARCHAR, method VARCHAR, condition VARCHAR, value DOUBLE,
        umpp DOUBLE, clicks JSON, n INTEGER, test_len_um DOUBLE,
        l_um DOUBLE, astm_g DOUBLE, done BOOLEAN, updated_at TIMESTAMP,
        PRIMARY KEY (name, method))""")
    return con

def geometry(d):
    """Return circle + line geometry (pixel coords) and total lengths (px),
    using the currently selected grid density (GRID). Full frame; the circle
    grid is centred plus an optional per-image offset ("coff"), clamped so the
    largest circle stays fully inside the frame (the test line must lie in the
    field). Position doesn't change test length, so ℓ/G are offset-independent."""
    w, h = d["w"], d["h"]
    cx, cy = w/2.0, h/2.0
    rfr = CIRCLE_PRESETS.get(GRID["circles"], CIRCLE_PRESETS["3"])
    lp = LINE_PRESETS.get(GRID["lines"], LINE_PRESETS["4x4"])
    radii = [h*f for f in rfr]
    rmax = max(radii)
    ox, oy = d.get("coff", (0, 0))
    if 2*rmax <= w: cx = min(max(rmax, cx + ox), w - rmax)
    if 2*rmax <= h: cy = min(max(rmax, cy + oy), h - rmax)
    circ_px = 2*math.pi*sum(radii)
    lines = []
    for f in lp.get("h", ()): lines.append([0, h*f, w, h*f])
    for f in lp.get("v", ()): lines.append([w*f, 0, w*f, h])
    if lp.get("diag"):
        lines.append([0, 0, w, h])       # two full-frame diagonals: 2 extra
        lines.append([0, h, w, 0])       # orientations (s13.4: >=4 orientations)
    line_px = sum(math.hypot(x2-x1, y2-y1) for x1,y1,x2,y2 in lines)
    return dict(cx=cx, cy=cy, radii=radii, circ_px=circ_px,
                lines=lines, line_px=line_px, w=w, h=h)

def total_len_px(d, method):
    g = geometry(d)
    return g["circ_px"] if method == "circle" else g["line_px"]

def to_G(l_mm): return -6.643856*math.log10(l_mm) - 3.288

def compute(name, method, n):
    d = BYNAME[name]; umpp = d.get("umpp", DEFAULT_UMPP)
    L = round(total_len_px(d, method)*umpp, 1)
    if n <= 0: return dict(n=0, l_um=None, G=None, L_um=L)
    l = total_len_px(d, method)*umpp/n
    return dict(n=n, l_um=round(l,1), G=round(to_G(l/1000.0),2), L_um=L)

@app.route("/")
def home(): return render_template_string(PAGE)

@app.route("/api/images")
def images():
    con = db()
    rows = con.execute("SELECT name,method,n,done FROM intercepts").fetchall(); con.close()
    by = {}
    for name, method, n, done in rows:
        by.setdefault(name, {})[method] = (n, done)
    out = []
    for d in INDEX:
        m = by.get(d["name"], {})
        out.append(dict(name=d["name"], condition=d["condition"], value=d.get("value"),
            folder=d.get("folder", d["condition"]), umpp=d.get("umpp", DEFAULT_UMPP),
            n_circle=m.get("circle",(0,0))[0] or 0, n_line=m.get("line",(0,0))[0] or 0,
            done_circle=bool(m.get("circle",(0,0))[1]),
            done_line=bool(m.get("line",(0,0))[1])))
    return jsonify(dict(folders=FOLDERS, images=out))

def _norm_path(p):
    """Normalise a folder path: strip, collapse slashes, drop empty segments."""
    return "/".join(s for s in (p or "").strip().split("/") if s.strip())

def _add_with_ancestors(path):
    parts = path.split("/")
    for i in range(1, len(parts) + 1):
        p = "/".join(parts[:i])
        if p not in FOLDERS: FOLDERS.append(p)

@app.route("/api/folder/create", methods=["POST"])
def folder_create():
    """Create a folder (path with '/' = subfolder, e.g. 'as-cast/Batch A')."""
    name = _norm_path(request.get_json().get("name"))
    if not name: return jsonify(ok=False, error="empty name"), 400
    _add_with_ancestors(name); save_folders()
    return jsonify(ok=True, folders=FOLDERS)

@app.route("/api/folder/rename", methods=["POST"])
def folder_rename():
    """Rename a folder and its whole subtree (updates descendant paths + images)."""
    b = request.get_json(); old = _norm_path(b.get("old")); new = _norm_path(b.get("new"))
    if not old or not new: return jsonify(ok=False, error="empty name"), 400
    def remap(p):
        if p == old: return new
        if p.startswith(old + "/"): return new + p[len(old):]
        return p
    seen = []
    for f in FOLDERS:
        r = remap(f)
        if r not in seen: seen.append(r)
    FOLDERS[:] = seen
    _add_with_ancestors(new)
    for d in INDEX:
        if d.get("folder"): d["folder"] = remap(d["folder"])
    save_folders(); save_index()
    return jsonify(ok=True, folders=FOLDERS)

@app.route("/api/folder/delete", methods=["POST"])
def folder_delete():
    """Delete a folder and its subtree; its images fall back to their condition group."""
    name = _norm_path(request.get_json().get("name"))
    victims = {f for f in FOLDERS if f == name or f.startswith(name + "/")}
    FOLDERS[:] = [f for f in FOLDERS if f not in victims]
    for d in INDEX:
        fld = d.get("folder")
        if fld and (fld == name or fld.startswith(name + "/")):
            d["folder"] = d["condition"] or "Ungrouped"
    save_folders(); save_index()
    return jsonify(ok=True, folders=FOLDERS)

@app.route("/api/folder/move", methods=["POST"])
def folder_move():
    b = request.get_json(); name = b.get("name"); folder = _norm_path(b.get("folder"))
    if name not in BYNAME or not folder: return jsonify(ok=False), 400
    BYNAME[name]["folder"] = folder
    _add_with_ancestors(folder); save_folders()
    save_index()
    return jsonify(ok=True)

@app.route("/api/condition", methods=["POST"])
def set_condition():
    """Reassign an image's condition (and optionally its numeric value) → updates
    the DB rows so it lands in the correct summary group (no geometry change, so
    ℓ/G stay the same)."""
    b = request.get_json(); name = b.get("name"); cond = (b.get("condition") or "").strip()
    if name not in BYNAME or not cond: return jsonify(ok=False), 400
    d = BYNAME[name]; d["condition"] = cond
    if "value" in b:
        try: d["value"] = float(b["value"]) if b["value"] not in (None, "") else None
        except (TypeError, ValueError): pass
    save_index()
    with _DB_WRITE_LOCK:
        con = db(); con.execute("UPDATE intercepts SET condition=?, value=? WHERE name=?",
                            [cond, d.get("value"), name]); con.close()
    return jsonify(ok=True, condition=cond, value=d.get("value"))

@app.route("/api/geom/<name>")
def api_geom(name):
    d = BYNAME[name]; g = geometry(d)
    umpp = d.get("umpp", DEFAULT_UMPP)
    con = db()
    rows = con.execute("SELECT method,clicks,done,test_len_um FROM intercepts WHERE name=?",
                       [name]).fetchall(); con.close()
    clicks = {"circle": [], "line": []}; done = {"circle": False, "line": False}
    stored_len = {"circle": None, "line": None}
    for method, cj, dn, tl in rows:
        clicks[method] = json.loads(cj) if cj else []
        done[method] = bool(dn)
        stored_len[method] = tl
    cur_len = {"circle": round(g["circ_px"]*umpp, 1), "line": round(g["line_px"]*umpp, 1)}
    return jsonify(cx=g["cx"], cy=g["cy"], radii=g["radii"], lines=g["lines"],
                   w=g["w"], h=g["h"], umpp=umpp, clicks=clicks, done=done,
                   stored_len=stored_len, cur_len=cur_len)

@app.route("/img/<name>.jpg")
def img(name): return send_file(os.path.join(CACHE, name+".jpg"))

@app.route("/api/save", methods=["POST"])
def save():
    b = request.get_json()
    name, method, clicks = b["name"], b["method"], b["clicks"]
    c = compute(name, method, len(clicks)); d = BYNAME[name]
    # Serialize writes: two in-flight saves for the same (name, method) hit a DuckDB
    # "Conflict on update!" TransactionException and the later click is silently lost.
    with _DB_WRITE_LOCK:
        con = db()
        con.execute("INSERT OR REPLACE INTO intercepts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [name, method, d["condition"], d.get("value"), d.get("umpp", DEFAULT_UMPP),
             json.dumps(clicks), c["n"], c["L_um"], c["l_um"], c["G"],
             bool(b.get("done", False)), datetime.datetime.now()])
        con.close()
    return jsonify(c)

@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    condition = (request.form.get("condition") or "").strip()
    folder = (request.form.get("folder") or "").strip() or condition
    try: umpp = float(request.form.get("umpp") or DEFAULT_UMPP)
    except ValueError: umpp = DEFAULT_UMPP
    vraw = (request.form.get("value") or "").strip()
    try: value = float(vraw) if vraw else None
    except ValueError: value = None
    if not f or not condition:
        return jsonify(ok=False, error="need file and condition"), 400
    ext = os.path.splitext(f.filename or "")[1].lower()
    RAW_EXTS = {".nef", ".cr2", ".cr3", ".arw", ".raf", ".orf", ".rw2", ".dng", ".raw", ".srw"}
    if ext in RAW_EXTS:
        return jsonify(ok=False, error=("RAW files (%s) aren't supported — export a "
            "JPEG or TIFF from your camera/microscope software first, then import that."
            % ext)), 400
    stem = os.path.splitext(secure_filename(f.filename))[0] or "image"
    name = stem; i = 1
    while name in BYNAME:
        name = f"{stem}_{i}"; i += 1
    try:
        im = Image.open(f.stream).convert("RGB")
    except Exception as e:
        return jsonify(ok=False, error=f"bad image: {e}"), 400
    if im.size[0] < 400 or im.size[1] < 400:        # guard against embedded thumbnails
        return jsonify(ok=False, error=("image is only %d×%d px — looks like an embedded "
            "thumbnail (RAW?). Export a full-size JPEG/TIFF and re-import."
            % im.size)), 400
    im.save(os.path.join(CACHE, name+".jpg"), quality=88)
    d = dict(condition=condition, value=value, name=name, w=im.size[0], h=im.size[1],
             umpp=umpp, folder=folder)
    INDEX.append(d); BYNAME[name] = d
    if folder not in FOLDERS: FOLDERS.append(folder); save_folders()
    save_index()
    return jsonify(ok=True, name=name, condition=condition, value=value,
                   w=im.size[0], h=im.size[1], umpp=umpp)

@app.route("/api/set_umpp", methods=["POST"])
def set_umpp():
    """Recalibrate µm/px for an image (or its condition, or all images),
    e.g. from the scale-bar tool. Recomputes stored ℓ/G for affected images."""
    b = request.get_json(); name = b["name"]
    try: umpp = float(b["umpp"])
    except (KeyError, ValueError, TypeError):
        return jsonify(ok=False, error="bad umpp"), 400
    if umpp <= 0 or name not in BYNAME:
        return jsonify(ok=False, error="invalid"), 400
    scope = b.get("scope", "this"); cond = BYNAME[name]["condition"]
    targets = [d for d in INDEX if (scope == "all"
               or (scope == "condition" and d["condition"] == cond)
               or (scope == "this" and d["name"] == name))]
    for d in targets:
        d["umpp"] = umpp
    save_index()
    # Rescale stored measurements by the calibration ratio ONLY. This preserves the
    # pixel geometry each count was actually made on (frozen test_len); a umpp change
    # is a pure unit conversion, unlike a grid change which must never rescale counts.
    with _DB_WRITE_LOCK:
        con = db()
        for d in targets:
            for method, n, old_umpp, old_L in con.execute(
                    "SELECT method,n,umpp,test_len_um FROM intercepts WHERE name=?",
                    [d["name"]]).fetchall():
                if not old_umpp or not old_L:
                    continue
                new_L = old_L / old_umpp * umpp
                l = new_L / n if n else None
                g = to_G(l/1000.0) if l else None
                con.execute("""UPDATE intercepts SET umpp=?, test_len_um=?, l_um=?,
                    astm_g=? WHERE name=? AND method=?""",
                    [umpp, round(new_L, 1), round(l, 1) if l else None,
                     round(g, 2) if g else None, d["name"], method])
        con.close()
    return jsonify(ok=True, updated=len(targets), umpp=umpp)


@app.route("/api/delete", methods=["POST"])
def delete():
    name = request.get_json()["name"]
    if name not in BYNAME:
        return jsonify(ok=False, error="not found"), 404
    try: os.remove(os.path.join(CACHE, name+".jpg"))
    except FileNotFoundError: pass
    INDEX[:] = [d for d in INDEX if d["name"] != name]
    BYNAME.pop(name, None); save_index()
    with _DB_WRITE_LOCK:
        con = db(); con.execute("DELETE FROM intercepts WHERE name=?", [name]); con.close()
    return jsonify(ok=True)

@app.route("/api/grid", methods=["GET", "POST"])
def api_grid():
    # NOTE: changing the grid affects DRAWING only. Saved measurements keep the
    # test length frozen at click time — an intercept count is only valid against
    # the grid it was counted on, so a grid change must never rescale stored ℓ/G.
    # Images counted on a different grid get a "stale grid" badge in the UI.
    if request.method == "POST":
        b = request.get_json() or {}
        if b.get("circles") in CIRCLE_PRESETS: GRID["circles"] = b["circles"]
        if b.get("lines") in LINE_PRESETS:     GRID["lines"] = b["lines"]
        save_grid()
    return jsonify(grid=GRID, circle_options=list(CIRCLE_PRESETS),
                   line_options=list(LINE_PRESETS))

@app.route("/api/circle_offset", methods=["POST"])
def circle_offset():
    """Store a per-image offset for the Abrams circle grid (px from centre).
    geometry() clamps, so the saved grid always lies inside the frame."""
    b = request.get_json() or {}
    name = b.get("name")
    if name not in BYNAME: return jsonify(ok=False, error="not found"), 404
    try:
        ox, oy = float(b.get("dx") or 0), float(b.get("dy") or 0)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="bad offset"), 400
    d = BYNAME[name]
    if ox == 0 and oy == 0: d.pop("coff", None)
    else: d["coff"] = [round(ox, 1), round(oy, 1)]
    save_index()
    g = geometry(d)
    return jsonify(ok=True, cx=g["cx"], cy=g["cy"])

def render_overlay(name, method):
    d = BYNAME[name]; g = geometry(d)
    im = Image.open(os.path.join(CACHE, name+".jpg")).convert("RGB")
    dr = ImageDraw.Draw(im)
    if method == "circle":
        for r in g["radii"]:
            dr.ellipse([g["cx"]-r, g["cy"]-r, g["cx"]+r, g["cy"]+r],
                       outline=(255, 60, 60), width=3)
    else:
        for x1, y1, x2, y2 in g["lines"]:
            dr.line([x1, y1, x2, y2], fill=(255, 60, 60), width=3)
    con = db(); row = con.execute(
        "SELECT clicks FROM intercepts WHERE name=? AND method=?", [name, method]).fetchone()
    con.close()
    for x, y in (json.loads(row[0]) if row and row[0] else []):
        dr.ellipse([x-5, y-5, x+5, y+5], fill=(30, 230, 100), outline=(0, 60, 25))
    return im

@app.route("/overlay/<name>.png")
def overlay(name):
    if name not in BYNAME: abort(404)
    method = request.args.get("method", "circle")
    buf = io.BytesIO(); render_overlay(name, method).save(buf, "PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name=f"{name}_{method}_overlay.png")

@app.route("/overlays.zip")
def overlays_zip():
    import zipfile
    method = request.args.get("method", "circle")
    con = db(); rows = con.execute(
        "SELECT name FROM intercepts WHERE method=? AND n>0", [method]).fetchall()
    con.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for (nm,) in rows:
            if nm in BYNAME:
                ib = io.BytesIO(); render_overlay(nm, method).save(ib, "PNG")
                z.writestr(f"{nm}_{method}.png", ib.getvalue())
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     download_name=f"grain_overlays_{method}.zip")

@app.route("/api/summary")
def summary():
    method = request.args.get("method", "circle")
    con = db()
    rows = con.execute("""SELECT condition, MAX(value) val, COUNT(*) imgs, SUM(n) tot,
        AVG(l_um) lm, STDDEV_SAMP(l_um) sd
        FROM intercepts WHERE n>0 AND method=? GROUP BY condition
        ORDER BY val NULLS LAST, condition""", [method]).fetchall(); con.close()
    out = []
    for cond, val, imgs, tot, lm, sd in rows:
        sd = sd or 0.0
        # ASTM E112 §15.4: 95% CI = t*s/sqrt(n) with Student's t (Table 7)
        ci = t_mult(imgs)*sd/math.sqrt(imgs) if imgs > 1 else 0.0
        # ASTM E112 §15.5: %RA = 95%CI / mean * 100
        ra = (ci/lm*100.0) if (lm and imgs > 1) else None
        # ASTM E112 §18.7: average the measurement (ℓ), THEN compute G — never average G
        G = to_G(lm/1000.0)
        out.append(dict(condition=cond, value=val, imgs=imgs, tot_int=int(tot),
            l_mean=round(lm,1), l_sd=round(sd,1), l_ci95=round(ci,1),
            ra_pct=(round(ra,1) if ra is not None else None),
            G_mean=round(G,2), enough=(imgs >= 5)))
    return jsonify(out)

@app.route("/export.csv")
def export_csv():
    con = db(); rows = con.execute("""SELECT condition,value,name,method,n,umpp,
        test_len_um,l_um,astm_g,done FROM intercepts WHERE n>0
        ORDER BY value NULLS LAST,condition,name,method""").fetchall(); con.close()
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["condition","value","image","method","n_intercepts","umpp",
                "test_len_um","l_um","ASTM_G","done"])
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":"attachment;filename=grain_size_E112.csv"})

@app.route("/export.xlsx")
def export_xlsx():
    """Download a spreadsheet of the current data WITH a native grain-size chart
    (line + circle markers + 95% CI error bars)."""
    method = request.args.get("method", "circle")
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.chart.marker import Marker
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.drawing.line import LineProperties
    from openpyxl.chart.axis import ChartLines
    from openpyxl.chart.error_bar import ErrorBars
    from openpyxl.chart.data_source import NumDataSource, NumRef, AxDataSource, StrRef

    con = db()
    rows = con.execute("""SELECT condition, MAX(value), COUNT(*), SUM(n), AVG(l_um), STDDEV_SAMP(l_um)
        FROM intercepts WHERE n>0 AND method=? GROUP BY condition
        ORDER BY MAX(value) NULLS LAST, condition""", [method]).fetchall()
    per_img = con.execute("""SELECT condition, value, name, n, l_um, astm_g FROM intercepts
        WHERE n>0 AND method=? ORDER BY value NULLS LAST, condition, name""", [method]).fetchall()
    con.close()

    wb = Workbook(); ws = wb.active; ws.title = "Grain size"
    ws.append(["Condition", "Value", "Fields", "Sum intercepts",
               "Mean intercept (µm)", "SD (µm)", "95% CI (µm)", "%RA", "ASTM G"])
    for cond, val, imgs, tot, lm, sd in rows:
        sd = sd or 0.0; ci = t_mult(imgs)*sd/math.sqrt(imgs) if imgs > 1 else 0.0
        ra = round(ci/lm*100, 1) if (lm and imgs > 1) else None
        ws.append([cond, val, imgs, int(tot), round(lm, 1), round(sd, 1),
                   round(ci, 1), ra, round(to_G(lm/1000.0), 2)])
    nrow = 1 + len(rows)

    ws2 = wb.create_sheet("Per image")
    ws2.append(["Condition", "Value", "Image", "Method", "N", "ℓ (µm)", "ASTM G"])
    for cond, val, name, n, l, g in per_img:
        ws2.append([cond, val, name, method, n, l, g])

    if rows:
        have_vals = all(r[1] is not None for r in rows)   # numeric X only if every group has a value
        chart = LineChart(); chart.style = 2
        chart.title = "Grain Size (ASTM E112)"
        chart.x_axis.title = "Value" if have_vals else "Condition"
        chart.y_axis.title = "Mean lineal intercept, ℓ (µm)"
        chart.legend = None; chart.x_axis.delete = False; chart.y_axis.delete = False
        chart.x_axis.majorGridlines = ChartLines(); chart.y_axis.majorGridlines = ChartLines()
        chart.y_axis.numFmt = "0.0"
        chart.add_data(Reference(ws, min_col=5, min_row=1, max_row=nrow), titles_from_data=True)
        s = chart.series[0]; s.smooth = False
        s.marker = Marker(symbol="circle", size=9)
        s.marker.graphicalProperties = GraphicalProperties(solidFill="548235")
        s.marker.graphicalProperties.line = LineProperties(solidFill="548235")
        s.graphicalProperties = GraphicalProperties()
        s.graphicalProperties.line = LineProperties(solidFill="548235", w=22000)
        cat_col = "B" if have_vals else "A"
        s.cat = AxDataSource(strRef=StrRef(f=f"'Grain size'!${cat_col}$2:${cat_col}${nrow}"))
        ci_ref = Reference(ws, min_col=7, min_row=2, max_row=nrow)
        s.errBars = ErrorBars(errDir="y", errBarType="both", errValType="cust",
                              plus=NumDataSource(NumRef(ci_ref)), minus=NumDataSource(NumRef(ci_ref)))
        chart.width = 18; chart.height = 11
        ws.add_chart(chart, "K2")

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="grain_size_chart.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

PAGE = r"""
<!doctype html><html lang=en><head><meta charset=utf-8>
<link rel=icon type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCIgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0Ij4KIDxkZWZzPgogIDxsaW5lYXJHcmFkaWVudCBpZD0iYmciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj4KICAgPHN0b3Agb2Zmc2V0PSIwIiBzdG9wLWNvbG9yPSIjM2I4MmY2Ii8+CiAgIDxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iIzdjM2FlZCIvPgogIDwvbGluZWFyR3JhZGllbnQ+CiA8L2RlZnM+CiA8IS0tIGFwcCB0aWxlIC0tPgogPHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iMTQiIGZpbGw9InVybCgjYmcpIi8+CiA8IS0tIGdyYWluIGJvdW5kYXJpZXMgbWVldGluZyBhdCBhIHRyaXBsZSBqdW5jdGlvbiAtLT4KIDxnIHN0cm9rZT0icmdiYSgyNTUsMjU1LDI1NSwuOTIpIiBzdHJva2Utd2lkdGg9IjMiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbD0ibm9uZSI+CiAgPHBhdGggZD0iTTIgMTcgTDMxIDMwIEw2MiAxOSIvPgogIDxwYXRoIGQ9Ik0zMSAzMCBMMzIgNjIiLz4KIDwvZz4KIDwhLS0gQWJyYW1zIGludGVyY2VwdCB0ZXN0IGNpcmNsZSAtLT4KIDxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIHI9IjE2IiBmaWxsPSJub25lIiBzdHJva2U9IiNmZjRkNGQiIHN0cm9rZS13aWR0aD0iMy4yIi8+CiA8IS0tIGNvdW50ZWQgaW50ZXJjZXB0IG1hcmtzIChjaXJjbGUgeCBib3VuZGFyeSkgLS0+CiA8ZyBmaWxsPSIjMjJmZjc3IiBzdHJva2U9IiMwNjIxMGYiIHN0cm9rZS13aWR0aD0iMS4yIj4KICA8Y2lyY2xlIGN4PSIxOC4xIiBjeT0iMjQiIHI9IjMuMSIvPgogIDxjaXJjbGUgY3g9IjQ1LjkiIGN5PSIyNCIgcj0iMy4xIi8+CiAgPGNpcmNsZSBjeD0iMzIiIGN5PSI0OCIgcj0iMy4xIi8+CiA8L2c+Cjwvc3ZnPgo=">
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Grain Size Analyzer · ASTM E112</title>
<style>
 :root{
  --bg:#0e1014; --panel:#161922; --panel2:#1c2029; --border:#272d39;
  --text:#e7eaf0; --muted:#9099a8; --accent:#3b82f6; --accent2:#2563eb;
  --ok:#22c55e; --warn:#f59e0b; --danger:#ef4444; --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
 }
 *{box-sizing:border-box}
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;margin:0;background:var(--bg);color:var(--text);font-size:14px}
 /* ---- top bar ---- */
 .appbar{height:54px;display:flex;align-items:center;gap:16px;padding:0 16px;background:linear-gradient(180deg,#1a1e28,#141821);border-bottom:1px solid var(--border)}
 .brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:15px;letter-spacing:.2px}
 .brand .logo{width:26px;height:26px;border-radius:7px;background:linear-gradient(135deg,var(--accent),#7c3aed);display:flex;align-items:center;justify-content:center;font-size:15px}
 .brand small{font-weight:500;color:var(--muted);font-size:11px;display:block;margin-top:1px}
 .seg{display:flex;background:var(--panel2);border:1px solid var(--border);border-radius:9px;padding:3px;gap:2px}
 .seg button{background:transparent;color:var(--muted);border:0;padding:6px 14px;border-radius:7px;cursor:pointer;font-size:13px;font-weight:600;display:flex;align-items:center;gap:6px}
 .seg button.act{background:var(--accent);color:#fff;box-shadow:0 1px 4px rgba(59,130,246,.4)}
 .spacer{flex:1}
 .iconbtn{background:var(--panel2);border:1px solid var(--border);color:var(--text);width:34px;height:34px;border-radius:8px;cursor:pointer;font-size:15px}
 .iconbtn:hover{border-color:var(--accent)}
 /* ---- layout ---- */
 .stage{display:flex;height:calc(100vh - 54px)}
 .side{width:264px;background:var(--panel);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
 .side h3{margin:0;padding:12px 14px 8px;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
 .search{margin:0 12px 8px;padding:7px 10px;background:var(--panel2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px}
 .list{flex:1;overflow:auto;padding:0 8px}
 .grp{font-size:11px;color:var(--muted);font-weight:700;padding:10px 8px 4px;text-transform:uppercase;letter-spacing:.5px}
 .it{display:flex;align-items:center;gap:8px;padding:7px 10px;margin:2px 0;border-radius:8px;cursor:pointer;font-size:13px;user-select:none}
 .it:hover{background:var(--panel2)}
 .it.sel{background:rgba(59,130,246,.16);outline:1px solid rgba(59,130,246,.5)}
 .dot{width:8px;height:8px;border-radius:50%;background:#3a4150;flex:none}
 .it.done .dot{background:var(--ok)}
 .it .nm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .it .cnt{font-family:var(--mono);font-size:11px;color:var(--muted)}
 .folder{display:flex;align-items:center;gap:6px;padding:6px 8px;margin:2px 0;border-radius:8px;cursor:pointer;font-weight:600;font-size:13px;color:#cdd3de}
 .folder:hover{background:var(--panel2)}
 .folder.dragover{background:rgba(59,130,246,.22);outline:1px dashed var(--accent)}
 .it[draggable]{cursor:grab}.it.dragging{opacity:.4}
 .it.msel{background:rgba(245,158,11,.16);outline:1px solid var(--warn)}
 .folder .tw{width:12px;color:var(--muted);font-size:11px}
 .folder .fnm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .folder .fcount{font-family:var(--mono);font-size:11px;color:var(--muted);font-weight:400}
 .folder .facts{display:none;gap:2px;margin-left:2px}
 .folder:hover .facts{display:flex}
 .facts button{background:transparent;border:0;color:var(--muted);cursor:pointer;font-size:12px;padding:0 3px;border-radius:4px}
 .facts button:hover{color:var(--text);background:rgba(255,255,255,.08)}
 .children{margin-left:9px;border-left:1px solid var(--border);padding-left:5px}
 /* import */
 .import{border-top:1px solid var(--border);padding:12px 14px;background:var(--panel)}
 .import label{font-size:11px;color:var(--muted);display:block;margin:8px 0 3px;text-transform:uppercase;letter-spacing:.5px}
 .import input,.import select{width:100%;padding:7px 9px;background:var(--panel2);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:13px}
 .row2{display:flex;gap:8px}.row2>*{flex:1}
 /* main */
 .main{flex:1;display:flex;flex-direction:column;overflow:hidden}
 .toolbar{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--border);background:var(--panel)}
 .adjustbar{display:flex;align-items:center;gap:10px;padding:7px 14px;border-bottom:1px solid var(--border);background:var(--panel2);font-size:12px;color:var(--muted);flex-wrap:wrap}
 .adjustbar input[type=range]{width:84px;vertical-align:middle;accent-color:var(--accent)}
 .adjustbar select{padding:3px 6px;background:var(--panel);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px}
 .adjustbar label{display:inline-flex;align-items:center;gap:4px;cursor:pointer}
 .adjustbar .sep{width:1px;height:18px;background:var(--border)}
 .adjustbar .albl{font-weight:600;color:#cdd3de}
 .adjustbar button.btn{padding:4px 9px;font-size:12px}
 .adjustbar button.btn.on{background:var(--accent);border-color:var(--accent);color:#fff}
 #loupe{position:fixed;width:180px;height:180px;border:2px solid var(--accent);border-radius:50%;box-shadow:0 6px 20px rgba(0,0,0,.55);pointer-events:none;display:none;z-index:40;background:#000}
 .btn{background:var(--panel2);color:var(--text);border:1px solid var(--border);padding:7px 12px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;display:inline-flex;align-items:center;gap:6px}
 .btn:hover{border-color:var(--accent)}
 .btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
 .btn.primary:hover{background:var(--accent2)}
 .btn.ok{background:var(--ok);border-color:var(--ok);color:#06210f}
 .btn.ghost{background:transparent}
 .kbd{font-family:var(--mono);font-size:10px;background:#000;border:1px solid var(--border);border-radius:4px;padding:1px 5px;color:var(--muted)}
 .canvaswrap{flex:1;overflow:auto;background:#0a0c10;display:flex;justify-content:center;align-items:flex-start;padding:18px}
 .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.35)}
 .cardhead{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);font-size:13px}
 .cardhead .ttl{font-weight:600}.cardhead .meta{color:var(--muted);font-family:var(--mono);font-size:12px}
 canvas{display:block;cursor:crosshair}
 /* stats strip */
 .stats{display:flex;gap:0;border-top:1px solid var(--border);background:var(--panel);padding:0}
 .stat{flex:1;padding:12px 16px;border-right:1px solid var(--border);text-align:center}
 .stat:last-child{border-right:0}
 .stat .lab{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
 .stat .val{font-family:var(--mono);font-size:24px;font-weight:700;margin-top:3px}
 .stat .val.accent{color:#7dd3fc}.stat .unit{font-size:12px;color:var(--muted);font-weight:400}
 .warnN{color:var(--warn)!important}
 /* results */
 .results{border-top:1px solid var(--border);background:var(--panel);max-height:38vh;overflow:auto}
 .results .rhead{display:flex;align-items:center;gap:10px;padding:10px 16px;position:sticky;top:0;background:var(--panel)}
 .results h4{margin:0;font-size:13px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{padding:7px 14px;text-align:right;border-bottom:1px solid var(--border)}
 th{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:600;background:var(--panel2);position:sticky;top:44px}
 td:first-child,th:first-child{text-align:left}
 tr:hover td{background:rgba(255,255,255,.02)}
 .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-family:var(--mono)}
 .pill.g{background:rgba(34,197,94,.15);color:#86efac}
 /* toast */
 #toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#0b3d22;border:1px solid var(--ok);color:#bbf7d0;padding:10px 18px;border-radius:10px;font-size:13px;opacity:0;transition:opacity .3s;pointer-events:none}
 #toast.show{opacity:1}
 #toast.err{background:#3d0b0b;border-color:var(--danger);color:#fecaca}
 /* modal */
 .overlay{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;align-items:center;justify-content:center;z-index:50}
 .overlay.show{display:flex}
 .modal{background:var(--panel);border:1px solid var(--border);border-radius:14px;max-width:760px;max-height:84vh;overflow:auto;padding:26px 30px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
 .modal h2{margin:0 0 4px;font-size:20px}.modal h3{margin:20px 0 6px;font-size:15px;color:#7dd3fc}
 .modal p,.modal li{color:#cfd4de;line-height:1.55}
 .modal code{background:#000;padding:2px 6px;border-radius:5px;font-family:var(--mono);font-size:12px;color:#93c5fd}
 .formula{background:#0a0c10;border:1px solid var(--border);border-radius:8px;padding:12px 16px;font-family:var(--mono);font-size:13px;margin:8px 0;color:#e7eaf0}
 .ref{font-size:12px;color:var(--muted)}
 .modal .x{float:right;cursor:pointer;color:var(--muted);font-size:22px;line-height:1}
 .modal.small{max-width:440px;padding:22px 24px}
 .modal.small p{margin:0 0 14px;white-space:pre-line}
 .modal.small input{width:100%;padding:8px 10px;background:var(--panel2);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:14px;margin-bottom:14px}
 .dlgbtns{display:flex;gap:10px;justify-content:flex-end}
 .btn.danger{background:var(--danger);border-color:var(--danger);color:#fff}
 .autosave{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:5px}
 .autosave .d{width:7px;height:7px;border-radius:50%;background:var(--ok)}
 /* ---- guided tour (coach marks) ---- */
 #tourBackdrop{position:fixed;inset:0;z-index:90;display:none}
 #tourHi{position:fixed;z-index:91;border:2px solid var(--accent);border-radius:10px;pointer-events:none;display:none;
  box-shadow:0 0 0 9999px rgba(0,0,0,.7),0 0 22px rgba(59,130,246,.65);
  transition:left .22s ease,top .22s ease,width .22s ease,height .22s ease}
 #tourBubble{position:fixed;z-index:92;width:330px;max-width:calc(100vw - 24px);background:var(--panel);
  border:1px solid var(--border);border-radius:12px;padding:16px 18px 14px;box-shadow:0 18px 50px rgba(0,0,0,.55);display:none}
 #tourBubble h4{margin:0 24px 6px 0;font-size:15px;color:var(--text)}
 #tourBubble p{margin:0 0 12px;font-size:13px;line-height:1.55;color:#cfd4de}
 #tourBubble .tnav{display:flex;align-items:center;gap:8px}
 #tourCount{flex:1;font-family:var(--mono);font-size:11px;color:var(--muted)}
 #tourSkip{position:absolute;top:8px;right:8px;background:transparent;border:0;color:var(--muted);font-size:15px;cursor:pointer;padding:2px 6px;border-radius:5px}
 #tourSkip:hover{color:var(--text);background:rgba(255,255,255,.08)}
 #tourBackBtn:disabled{opacity:.4;cursor:default}
</style></head><body>

<div class=appbar>
 <div class=brand><span class=logo><svg viewBox="0 0 64 64" width="20" height="20" aria-hidden="true"><g stroke="rgba(255,255,255,.92)" stroke-width="4" stroke-linecap="round" fill="none"><path d="M2 17 L31 30 L62 19"/><path d="M31 30 L32 62"/></g><circle cx="32" cy="32" r="16" fill="none" stroke="#ff4d4d" stroke-width="4.2"/><g fill="#22ff77" stroke="#06210f" stroke-width="1.5"><circle cx="18.1" cy="24" r="4"/><circle cx="45.9" cy="24" r="4"/><circle cx="32" cy="48" r="4"/></g></svg></span><div>Grain Size Analyzer<small>ASTM E112 · intercept method</small></div></div>
 <div class=seg>
  <button id=tabCircle onclick="setMethod('circle')">◎ Abrams circles</button>
  <button id=tabLine onclick="setMethod('line')">▤ Heyn lines</button>
 </div>
 <div class=autosave><span class=d></span>Auto-saved</div>
 <div class=spacer></div>
 <button class=iconbtn id=tourBtn title="Take a guided tour" onclick="startTour()">🎓</button>
 <button class=iconbtn id=helpBtn title="Help & method reference" onclick="showHelp(1)">?</button>
</div>

<div class=stage>
 <!-- sidebar -->
 <div class=side>
  <div style="display:flex;align-items:center;gap:8px;padding:12px 12px 6px">
   <h3 style="padding:0;flex:1">Folders</h3>
   <button class=btn onclick="newFolder()" style="padding:4px 9px;font-size:12px">＋ Folder</button>
  </div>
  <input class=search id=search placeholder="Filter images…" oninput="renderList()">
  <div id=mselBar style="display:none;margin:0 12px 8px;padding:8px 10px;background:rgba(245,158,11,.10);border:1px solid var(--warn);border-radius:8px;font-size:12px">
   <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px"><b><span id=mselN>0</span> selected</b><span class=spacer></span><button class=btn onclick="mselClear()" style="padding:2px 8px" title="Clear selection (Esc)">✕</button></div>
   <div style="display:flex;gap:6px">
    <select id=mselMoveSel style="flex:1;padding:5px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px"></select>
    <button class=btn onclick="mselMove()" style="padding:4px 9px">Move</button>
    <button class="btn danger" onclick="mselDelete()" style="padding:4px 9px" title="Delete selected">🗑</button>
   </div>
  </div>
  <div class=list id=list></div>
  <div class=import>
   <h3 style="padding:0 0 2px">＋ Import photo</h3>
   <label>Image file(s) — pick one or many (JPEG / TIFF)</label>
   <input type=file id=fileIn accept="image/*,.tif,.tiff" multiple>
   <div class=row2>
    <div><label>Condition</label>
     <input id=condIn type=text list=condList placeholder="e.g. as-cast"></div>
    <div><label>Value (optional)</label>
     <input id=valIn type=number step=any placeholder="e.g. 300"></div>
   </div>
   <div class=row2>
    <div><label>Scale <span style="text-transform:none">µm/px</span> (microns)</label>
     <input id=umppIn type=number step=0.0000001 value=1.0></div>
    <div><label>Folder</label>
     <select id=folderIn></select></div>
   </div>
   <datalist id=condList></datalist>
   <button class="btn primary" style="width:100%;margin-top:8px;justify-content:center" onclick="doUpload()">Upload &amp; open</button>
  </div>
 </div>

 <!-- main -->
 <div class=main>
  <div class=toolbar>
   <span id=countGroup style="display:flex;align-items:center;gap:8px">
   <button class=btn onclick="undo()">↶ Undo <span class=kbd>Z</span></button>
   <button class=btn onclick="clr()">✕ Clear</button>
   <button class="btn primary" onclick="markdone()">✓ Mark done &amp; next <span class=kbd>D</span></button>
   </span>
   <span style="width:1px;height:24px;background:var(--border);margin:0 4px"></span>
   <span id=zoomGroup style="display:flex;align-items:center;gap:8px">
   <button class=btn onclick="zoom(-1)" title="Zoom out">－</button>
   <span id=zlabel style="font-family:var(--mono);font-size:12px;color:var(--muted);min-width:42px;text-align:center">fit</span>
   <button class=btn onclick="zoom(1)" title="Zoom in">＋</button>
   <button class=btn onclick="fitView()" title="Fit image to window">⤢ Fit</button>
   </span>
   <span style="width:1px;height:24px;background:var(--border);margin:0 4px"></span>
   <button class=btn id=calibBtn onclick="startCalib()">📏 Calibrate scale</button>
   <div class=spacer></div>
   <span id=exportGroup style="display:flex;align-items:center;gap:8px">
   <a class="btn ghost" href="/export.csv">⬇ CSV</a>
   <button class="btn ghost" onclick="exportXlsx()" title="Download a spreadsheet with a grain-size chart of your current data">⬇ XLSX + chart</button>
   <button class="btn ghost" onclick="exportOverlays()" title="Download annotated overlays (current method) as a zip">🖼 Overlays</button>
   </span>
  </div>

  <div class=adjustbar>
   <span class=albl>Image</span>
   <label title="Brightness">☀ <input type=range id=bright min=0.4 max=2 step=0.05 value=1 oninput="onAdj()"></label>
   <label title="Contrast">◐ <input type=range id=contrast min=0.4 max=2.6 step=0.05 value=1 oninput="onAdj()"></label>
   <label><input type=checkbox id=invert onchange="onAdj()"> invert</label>
   <button class=btn onclick="resetAdj()">reset</button>
   <span class=sep></span>
   <button class=btn id=loupeBtn onclick="toggleLoupe()">🔍 Loupe</button>
   <button class=btn id=moveBtn onclick="toggleMove()" title="Drag the Abrams circles to reposition them on this image (off-centre photos). Position is saved per image; test-line length — and so ℓ/G — is unchanged.">✥ Move circles</button>
   <button class=btn id=centerBtn onclick="centerCircles()" title="Reset the Abrams circles to the image centre">⌖ Centre</button>
   <label title="Snap each click onto the nearest test line/circle"><input type=checkbox id=snap> snap to grid</label>
   <span class=sep></span>
   <span class=albl>Grid</span>
   <span title="Locked to the canonical ASTM E112 Abrams three-circle grid (Fig. 5, radii 1:2:3)">3 circles (Abrams)</span><span>·</span>
   <select id=gridLines onchange="setGrid()" title="Heyn line density"></select><span>lines</span>
  </div>

  <div class=canvaswrap>
   <div class=card>
    <div class=cardhead><span class=ttl id=imgTitle>—</span><span class=meta id=imgMeta></span><span id=staleWarn style="color:var(--warn);font-size:12px;font-weight:600"></span>
     <span class=spacer></span>
     <span id=imgMetaCtls style="display:flex;align-items:center;gap:10px">
     <input id=condSel type=text list=condList onchange="setCondition(this.value)" title="Condition label (groups the summary)" placeholder="condition" style="width:130px;padding:5px 8px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px">
     <select id=moveSel onchange="moveCurrent(this.value)" title="Move to folder" style="padding:5px 8px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px"></select>
     </span>
     <button class=btn onclick="saveOverlay()" title="Download annotated overlay PNG" style="padding:5px 10px">🖼 Overlay</button>
     <button class=btn onclick="deleteImg()" title="Remove this image" style="padding:5px 10px">🗑 Delete</button></div>
    <div id=calib style="display:none;align-items:center;gap:10px;padding:9px 14px;background:rgba(245,158,11,.10);border-bottom:1px solid var(--border);font-size:13px">
     <b style="color:var(--warn)">📏 Click the two ends of the scale bar.</b>
     <span id=calibPx style="font-family:var(--mono);color:var(--muted)">0 px</span>
     known length <input id=calibKnown type=number value=1000 oninput="computeCalib()" style="width:80px;padding:5px 8px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;color:var(--text)"> µm
     → <b id=calibUmpp style="font-family:var(--mono);color:#7dd3fc">– µm/px</b>
     apply to <select id=calibScope style="padding:5px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;color:var(--text)">
      <option value=this>this image</option><option value=condition>this condition</option><option value=all>all images</option></select>
     <button class="btn primary" onclick="applyCalib()" style="padding:5px 12px">Apply</button>
     <button class=btn onclick="cancelCalib()" style="padding:5px 12px">Cancel</button>
    </div>
    <div id=wrap style="position:relative"><canvas id=cv></canvas></div>
    <div class=stats>
     <div class=stat><div class=lab>Intercepts (N)</div><div class="val" id=n>0</div></div>
     <div class=stat><div class=lab>Mean intercept ℓ</div><div class="val accent"><span id=l>–</span> <span class=unit>µm</span></div></div>
     <div class=stat><div class=lab>ASTM grain no. G</div><div class="val" id=g>–</div></div>
     <div class=stat><div class=lab>Test length</div><div class=val style="font-size:18px"><span id=L>–</span> <span class=unit>µm</span></div></div>
    </div>
   </div>
  </div>

  <div class=results>
   <div class=rhead><h4 id=sumTitle>Per-condition summary</h4><span class=spacer></span>
    <span class=ref id=sumNote></span></div>
   <table><thead><tr><th>Condition</th><th>Value</th><th>Fields</th><th>Σ Intercepts</th><th>ℓ (<span style="text-transform:none">µm</span>)</th><th>± SD</th><th>± 95% CI</th><th>%RA</th><th>G</th></tr></thead>
    <tbody id=sumBody></tbody></table>
  </div>
 </div>
</div>

<!-- in-app dialog (replaces browser confirm/prompt, which users may block) -->
<div class=overlay id=dlg>
 <div class="modal small">
  <p id=dlgMsg></p>
  <input id=dlgInput type=text>
  <div class=dlgbtns>
   <button class=btn id=dlgCancel>Cancel</button>
   <button class="btn danger" id=dlgOk>OK</button>
  </div>
 </div>
</div>
<canvas id=loupe width=180 height=180></canvas>
<div id=toast></div>

<!-- GUIDED TOUR (first-run coach marks) -->
<div id=tourBackdrop></div>
<div id=tourHi></div>
<div id=tourBubble>
 <button id=tourSkip title="Skip tour (Esc)">✕</button>
 <h4 id=tourTitle></h4>
 <p id=tourBody></p>
 <div class=tnav>
  <span id=tourCount></span>
  <button class=btn id=tourBackBtn>← Back</button>
  <button class="btn primary" id=tourNextBtn>Next →</button>
 </div>
</div>

<!-- HELP MODAL -->
<div class=overlay id=help>
 <div class=modal>
  <span class=x onclick="showHelp(0)">×</span>
  <h2>Grain Size Analyzer — method &amp; reference</h2>
  <p class=ref>Manual intercept grain sizing per <b>ASTM E112</b>. Calibration is per-image (µm/px); the default is <code>1.0 µm/px</code>, i.e. <b>uncalibrated</b> — set the real scale for every image, either by typing the µm/px at import or by deriving it with the 📏 scale-bar tool.</p>

  <h3>How it works</h3>
  <p>A test grid of <b>known total length</b> is drawn over the microstructure. You click every point where the grid crosses a real grain boundary (skip twins &amp; scratches — that judgment is what makes the count defensible). The mean lineal intercept length is:</p>
  <div class=formula>ℓ = L<sub>total</sub> (µm) ÷ N&nbsp;&nbsp;&nbsp;&nbsp;[ N = number of boundary intersections ]</div>
  <p>and the ASTM grain-size number G follows the E112 Table 6 relation for mean lineal intercept (ℓ in mm):</p>
  <div class=formula>G = −6.643856 · log₁₀(ℓ<sub>mm</sub>) − 3.288</div>
  <p>Higher <b>G</b> = finer grains (each whole number ≈ a doubling of grains per unit area). Negative G is valid for coarse grains (a computed G = −1 is ASTM designation “00”).</p>

  <h3>Two methods</h3>
  <ul>
   <li><b>◎ Abrams three-circle</b> (primary, the E112 referee grid): three concentric, equally-spaced circles with diameters in the canonical <b>1 : 2 : 3</b> ratio (Fig. 5). Closed loops remove orientation bias and end-point ambiguity. A test-line/boundary tangency counts as 1; a triple-junction is scored as 2 (sanctioned by E112 §14.3.2.2).</li>
   <li><b>▤ Heyn lineal</b>: four horizontal + four vertical straight lines (≥4 orientations, §13.4). Simple and traceable.</li>
  </ul>
  <p class=ref>Each method stores its own clicks per image, so you can measure a field both ways and compare.</p>

  <h3>Recommended practice (ASTM E112)</h3>
  <ul>
   <li><b>40–100 intercepts per field</b> (§14.3.2.1); aim for a total of <b>~400–500</b> over <b>≥ 5 fields</b> (§14.3.2). The N readout warns below 40.</li>
   <li>The summary reports mean ℓ, SD, <b>95% CI = t·s/√n</b> (Student's <i>t</i>, Table 7) and <b>%RA = CI/ℓ̄·100</b>. Target <b>%RA ≤ 10%</b> (§15.6) — add fields until it's met.</li>
   <li><b>G is computed from the mean ℓ</b> across fields, never by averaging G numbers (§18.7).</li>
   <li>Twin boundaries are ignored (§3.2.2). Two-phase: grain size = the matrix phase (§17.1); decide a rule and keep it.</li>
   <li>A valid CI needs ≥ 5 fields; fewer is flagged ⚠ in the table.</li>
  </ul>

  <h3>Keyboard</h3>
  <p><span class=kbd>Z</span> undo · <span class=kbd>D</span> mark done &amp; next · <span class=kbd>←/→</span> prev/next image · <span class=kbd>1/2</span> switch method · <span class=kbd>Ctrl+click</span> multi-select · <span class=kbd>Shift+click</span> select range (click first, Shift+click last) · <span class=kbd>Esc</span> clear selection</p>

  <h3>References</h3>
  <ul class=ref>
   <li>ASTM E112-13, <i>Standard Test Methods for Determining Average Grain Size</i>, ASTM International.</li>
   <li>H. Abrams, “Practical Applications of the Three-Circle Intercept Grain Size Method,” <i>Met. Trans.</i> (1971).</li>
   <li>ASTM E1382, <i>Standard Test Methods for Determining Average Grain Size Using Semiautomatic and Automatic Image Analysis</i>.</li>
   <li>G. F. Vander Voort, <i>Metallography: Principles and Practice</i>, ASM International.</li>
  </ul>
 </div>
</div>

<script>
let imgs=[],cur=null,method='circle',clicks={circle:[],line:[]},done={circle:false,line:false};
let scale=1,userScale=null,G=null,img=new Image();   // userScale=null → fit
let calibrating=false,calibPts=[];
let folders=[],expanded={};
let adj={b:1,c:1,inv:0},loupeOn=false;
function esc(s){return (s+'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;').replace(/</g,'&lt;');}
function isOpen(f){return f in expanded ? expanded[f] : true;}
// In-app confirm/prompt — browser popups may be disabled, so never use confirm()/prompt().
let dlgResolve=null,dlgHasInput=false;
function uiDialog(msg,inputVal,okLabel,danger){return new Promise(res=>{dlgResolve=res;dlgHasInput=(inputVal!==null);
 document.getElementById('dlgMsg').textContent=msg;
 let inp=document.getElementById('dlgInput');inp.style.display=dlgHasInput?'block':'none';if(dlgHasInput)inp.value=inputVal;
 let ok=document.getElementById('dlgOk');ok.textContent=okLabel;ok.className='btn '+(danger?'danger':'primary');
 document.getElementById('dlg').classList.add('show');
 if(dlgHasInput)setTimeout(()=>{inp.focus();inp.select();},60);else setTimeout(()=>ok.focus(),60);});}
function uiConfirm(msg,okLabel){return uiDialog(msg,null,okLabel||'Delete',true);}
function uiPrompt(msg,initial){return uiDialog(msg,initial||'','OK',false);}
// Multi-select: Ctrl/Cmd+click toggles; action bar offers batch Move / Delete.
let msel=new Set(),visibleOrder=[],lastClicked=null;
function itemClick(e,name){
 if(e.shiftKey){e.preventDefault();
  let a=visibleOrder.indexOf(lastClicked!==null?lastClicked:name),b=visibleOrder.indexOf(name);
  if(a<0)a=b;
  let lo=Math.min(a,b),hi=Math.max(a,b);
  if(!(e.ctrlKey||e.metaKey))msel.clear();           // Ctrl+Shift adds to selection
  for(let i=lo;i<=hi;i++)msel.add(visibleOrder[i]);
  renderList();updateMselBar();return;}
 if(e.ctrlKey||e.metaKey){if(msel.has(name))msel.delete(name);else msel.add(name);lastClicked=name;renderList();updateMselBar();return;}
 if(msel.size){msel.clear();updateMselBar();}
 lastClicked=name;
 select(name);}
function updateMselBar(){let bar=document.getElementById('mselBar');if(!bar)return;
 document.getElementById('mselN').textContent=msel.size;
 bar.style.display=msel.size?'block':'none';
 if(msel.size){let sorted=[...allPaths()].sort();
  document.getElementById('mselMoveSel').innerHTML='<option value="" disabled selected>Move to…</option>'+sorted.map(f=>`<option>${f}</option>`).join('');}}
function mselClear(){msel.clear();renderList();updateMselBar();}
async function mselMove(){let f=document.getElementById('mselMoveSel').value;if(!f){toast('Pick a destination folder first',1);return;}
 let n=msel.size;
 for(const nm of msel)await fetch('/api/folder/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nm,folder:f})});
 msel.clear();await refreshImages();updateMselBar();toast('Moved '+n+' image'+(n>1?'s':'')+' → '+f);}
async function mselDelete(){if(!msel.size)return;
 if(!await uiConfirm('Delete '+msel.size+' image'+(msel.size>1?'s':'')+' and their measurements? This cannot be undone.'))return;
 let names=[...msel];
 for(const nm of names)await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nm})});
 msel.clear();await refreshImages();updateMselBar();loadSummary();
 if(names.includes(cur)){cur=null;
  if(imgs.length)select(imgs[0].name);
  else{ctx.clearRect(0,0,cv.width,cv.height);document.getElementById('imgTitle').textContent='—';document.getElementById('imgMeta').textContent='';}}
 toast('Deleted '+names.length+' image'+(names.length>1?'s':''));}
function dlgClose(okPressed){let dlg=document.getElementById('dlg');if(!dlg.classList.contains('show'))return;
 dlg.classList.remove('show');
 let val=dlgHasInput?(okPressed?document.getElementById('dlgInput').value:null):okPressed;
 if(dlgResolve){let r=dlgResolve;dlgResolve=null;r(val);}}
document.addEventListener('DOMContentLoaded',()=>{
 document.getElementById('dlgOk').onclick=()=>dlgClose(true);
 document.getElementById('dlgCancel').onclick=()=>dlgClose(false);
 document.getElementById('dlg').onclick=e=>{if(e.target.id=='dlg')dlgClose(false);};
 document.getElementById('dlgInput').addEventListener('keydown',e=>{if(e.key=='Enter')dlgClose(true);e.stopPropagation();});});
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
function toast(m,err){let t=document.getElementById('toast');t.textContent=m;t.className='show'+(err?' err':'');setTimeout(()=>t.className='',2200);}
function setTab(){document.getElementById('tabCircle').classList.toggle('act',method=='circle');document.getElementById('tabLine').classList.toggle('act',method=='line');}
async function init(){setTab();await loadGrid();await refreshImages();if(imgs.length)select(imgs[0].name);loadSummary();}
async function refreshImages(){let data=await(await fetch('/api/images')).json();folders=data.folders;imgs=data.images;renderList();}
function allPaths(){let s=new Set(folders);imgs.forEach(d=>s.add(d.folder));
 [...s].forEach(p=>{let parts=(p||'').split('/');for(let i=1;i<parts.length;i++)s.add(parts.slice(0,i).join('/'));});
 s.delete('');return s;}
function childrenOf(prefix,paths){let pre=prefix?prefix+'/':'';let set=new Set();
 paths.forEach(p=>{if(prefix===''){if(!p.includes('/'))set.add(p);}else if(p.startsWith(pre)){let rest=p.slice(pre.length);if(rest&&!rest.includes('/'))set.add(p);}});
 return [...set].sort((a,b)=>{let la=(a.match(/(\d+)/)||[0,999])[1],lb=(b.match(/(\d+)/)||[0,999])[1];return (+la)-(+lb)||a.localeCompare(b);});}
function subtreeMatches(path,byF,paths,q){
 if((byF[path]||[]).some(d=>d.name.toLowerCase().includes(q)))return true;
 return childrenOf(path,paths).some(c=>subtreeMatches(c,byF,paths,q));}
function renderNode(path,byF,paths,q){
 let leaf=path.split('/').pop();
 if(q&&!subtreeMatches(path,byF,paths,q))return '';
 let items=(byF[path]||[]).filter(d=>!q||d.name.toLowerCase().includes(q));
 let kids=childrenOf(path,paths);
 let open=isOpen(path)||!!q;
 let ep=esc(path);
 let h=`<div class=folder onclick="toggle('${ep}')" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropImg(event,'${ep}')"><span class=tw>${(kids.length||items.length)?(open?'▾':'▸'):'·'}</span><span class=fnm>${leaf}</span><span class=fcount>${items.length||''}</span>`+
   `<span class=facts onclick="event.stopPropagation()"><button title="New subfolder" onclick="newFolder('${ep}')">＋</button><button title="Rename" onclick="renameFolder('${ep}')">✎</button><button title="Delete" onclick="delFolder('${ep}')">🗑</button></span></div>`;
 if(open){h+='<div class=children>';
  kids.forEach(c=>h+=renderNode(c,byF,paths,q));
  items.forEach(d=>{visibleOrder.push(d.name);let n=method=='circle'?d.n_circle:d.n_line;let dn=method=='circle'?d.done_circle:d.done_line;
   h+=`<div class="it ${d.name==cur?'sel':''} ${dn?'done':''} ${msel.has(d.name)?'msel':''}" draggable=true ondragstart="dragImg(event,'${d.name}')" ondragend="dragEnd(event)" onclick="itemClick(event,'${d.name}')"><span class=dot></span><span class=nm>${d.name}</span><span class=cnt>${n||''}</span></div>`;});
  h+='</div>';}
 return h;}
function renderList(){
 let q=(document.getElementById('search').value||'').toLowerCase();
 let byF={};imgs.forEach(d=>{(byF[d.folder]=byF[d.folder]||[]).push(d);});
 let paths=allPaths();
 visibleOrder=[];
 let h=childrenOf('',paths).map(r=>renderNode(r,byF,paths,q)).join('');
 document.getElementById('list').innerHTML=h||'<div style="padding:12px;color:var(--muted);font-size:13px">No images yet.</div>';
 syncFolderSelects();
}
function syncFolderSelects(){let sorted=[...allPaths()].sort();let opts=sorted.map(f=>`<option>${f}</option>`).join('');
 let fi=document.getElementById('folderIn');if(fi){let v=fi.value;fi.innerHTML='<option value="">(same as condition)</option>'+opts;if([...fi.options].some(o=>o.value==v))fi.value=v;}
 let ms=document.getElementById('moveSel');if(ms){let d=imgs.find(x=>x.name==cur);ms.innerHTML='<option value="" disabled'+(d?'':' selected')+'>Move to…</option>'+sorted.map(f=>`<option ${d&&d.folder==f?'selected':''}>${f}</option>`).join('');}
 syncCondList();}
function syncCondList(){let conds=[...new Set(imgs.map(d=>d.condition).filter(Boolean))].sort();
 let dl=document.getElementById('condList');if(dl)dl.innerHTML=conds.map(c=>`<option value="${esc(c)}">`).join('');}
function toggle(f){expanded[f]=!isOpen(f);renderList();}
async function newFolder(parent){let label=parent?('New subfolder under "'+parent+'"'):'New folder name';
 let n=await uiPrompt(label);if(!n||!n.trim())return;n=n.trim();
 let path=parent?(parent+'/'+n):n;
 let r=await(await fetch('/api/folder/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:path})})).json();
 folders=r.folders;expanded[path]=true;if(parent)expanded[parent]=true;renderList();toast('Folder created: '+path);}
async function renameFolder(f){let leaf=f.split('/').pop();let parent=f.includes('/')?f.slice(0,f.lastIndexOf('/')):'';
 let n=await uiPrompt('Rename folder',leaf);if(!n||!n.trim()||n.trim()==leaf)return;n=n.trim();
 let np=parent?(parent+'/'+n):n;
 let r=await(await fetch('/api/folder/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old:f,new:np})})).json();
 folders=r.folders;await refreshImages();toast('Renamed to '+n);}
async function delFolder(f){if(!await uiConfirm('Delete folder "'+f+'" and its subfolders?\nImages inside move back to their condition group (images are NOT deleted).'))return;
 let r=await(await fetch('/api/folder/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f})})).json();
 folders=r.folders;await refreshImages();toast('Folder deleted');}
async function moveCurrent(folder){if(!cur||!folder)return;await moveImage(cur,folder);toast('Moved to '+folder);}
async function setCondition(cond){cond=(cond||'').trim();if(!cur||!cond)return;
 let r=await(await fetch('/api/condition',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,condition:cond})})).json();
 if(r.ok){let d=imgs.find(x=>x.name==cur);if(d)d.condition=r.condition;renderList();loadSummary();toast('Condition set to '+r.condition);}else toast('Could not set condition',1);}
async function moveImage(name,folder){
 await fetch('/api/folder/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,folder})});
 let d=imgs.find(x=>x.name==name);if(d)d.folder=folder;if(!folders.includes(folder))folders.push(folder);renderList();}
// drag & drop
let dragName=null;
function dragImg(e,name){dragName=name;e.dataTransfer.setData('text/plain',name);e.dataTransfer.effectAllowed='move';e.target.classList.add('dragging');}
function dragEnd(e){e.target.classList.remove('dragging');}
function dragOver(e){e.preventDefault();e.dataTransfer.dropEffect='move';e.currentTarget.classList.add('dragover');}
function dragLeave(e){e.currentTarget.classList.remove('dragover');}
async function dropImg(e,folder){e.preventDefault();e.currentTarget.classList.remove('dragover');
 let name=dragName||e.dataTransfer.getData('text/plain');dragName=null;
 if(!name||!folder)return;
 let names=(msel.has(name)&&msel.size>1)?[...msel]:[name];
 let moved=0;
 for(const nm of names){let d=imgs.find(x=>x.name==nm);if(d&&d.folder==folder)continue;
  await fetch('/api/folder/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nm,folder})});moved++;}
 if(names.length>1){msel.clear();updateMselBar();}
 await refreshImages();
 toast('Moved '+(moved>1?moved+' images':name)+' → '+folder);}
function setMethod(m){method=m;exitMove();let dis=m!='circle';document.getElementById('moveBtn').disabled=dis;document.getElementById('centerBtn').disabled=dis;setTab();if(G)draw();renderList();loadSummary();updateStale();}
function updateStale(){let el=document.getElementById('staleWarn');if(!el)return;
 let msg='';
 if(G&&clicks[method].length&&G.stored_len&&G.stored_len[method]&&G.cur_len&&G.cur_len[method]){
  let rel=Math.abs(G.stored_len[method]-G.cur_len[method])/G.cur_len[method];
  if(rel>0.005)msg='⚠ counted on a previous grid — Clear & recount to update';}
 el.textContent=msg;}
async function select(name){cur=name;exitMove();G=await(await fetch('/api/geom/'+name)).json();
 clicks={circle:G.clicks.circle.slice(),line:G.clicks.line.slice()};done=G.done;
 let d=imgs.find(x=>x.name==name);
 document.getElementById('imgTitle').textContent=name;
 document.getElementById('imgMeta').textContent=`${G.w}×${G.h} px · ${G.umpp} µm/px · ${d?d.condition:''}`;
 let cs=document.getElementById('condSel');if(cs&&d)cs.value=d.condition||'';
 updateStale();
 img=new Image();img.onload=()=>{userScale=null;applyZoom();};img.src='/img/'+name+'.jpg';renderList();}
function fitScale(){
 let wrap=document.querySelector('.canvaswrap');
 let head=document.querySelector('.cardhead'), st=document.querySelector('.stats');
 let chrome=(head?head.offsetHeight:0)+(st?st.offsetHeight:0)+6;
 let availW=Math.max(80, wrap.clientWidth-36), availH=Math.max(80, wrap.clientHeight-36-chrome);
 return Math.min(availW/G.w, availH/G.h);
}
function curScale(){return userScale!=null?userScale:fitScale();}
function applyZoom(){let s=curScale();scale=s;cv.width=Math.round(G.w*s);cv.height=Math.round(G.h*s);
 document.getElementById('zlabel').textContent=(userScale==null?'fit · ':'')+Math.round(s*100)+'%';draw();}
function zoom(dir){if(!G)return;userScale=Math.min(3,Math.max(0.1,curScale()+dir*0.1));applyZoom();}
function fitView(){if(!G)return;userScale=null;applyZoom();}
window.addEventListener('resize',()=>{if(G&&userScale==null)applyZoom();});
function draw(){ctx.clearRect(0,0,cv.width,cv.height);
 ctx.filter=`brightness(${adj.b}) contrast(${adj.c}) invert(${adj.inv})`;
 ctx.drawImage(img,0,0,cv.width,cv.height);ctx.filter='none';
 ctx.strokeStyle='#ff4d4d';ctx.lineWidth=2;
 if(method=='circle'){G.radii.forEach(r=>{ctx.beginPath();ctx.arc(G.cx*scale,G.cy*scale,r*scale,0,7);ctx.stroke();});}
 else{G.lines.forEach(L=>{ctx.beginPath();ctx.moveTo(L[0]*scale,L[1]*scale);ctx.lineTo(L[2]*scale,L[3]*scale);ctx.stroke();});}
 ctx.fillStyle='#22ff77';ctx.strokeStyle='#06210f';ctx.lineWidth=1.5;
 clicks[method].forEach(p=>{ctx.beginPath();ctx.arc(p[0]*scale,p[1]*scale,4.5,0,7);ctx.fill();ctx.stroke();});
 if(calibrating){ctx.strokeStyle='#f59e0b';ctx.fillStyle='#f59e0b';ctx.lineWidth=2.5;
  calibPts.forEach(p=>{ctx.beginPath();ctx.arc(p[0]*scale,p[1]*scale,5,0,7);ctx.fill();});
  if(calibPts.length==2){ctx.beginPath();ctx.moveTo(calibPts[0][0]*scale,calibPts[0][1]*scale);ctx.lineTo(calibPts[1][0]*scale,calibPts[1][1]*scale);ctx.stroke();}}
 stats();}
function testLen(){if(method=='circle')return 2*Math.PI*(G.radii[0]+G.radii[1]+G.radii[2])*G.umpp;let s=0;G.lines.forEach(L=>s+=Math.hypot(L[2]-L[0],L[3]-L[1]));return s*G.umpp;}
function stats(){let n=clicks[method].length;let nel=document.getElementById('n');nel.textContent=n;nel.className='val'+(n>0&&n<40?' warnN':'');
 let L=testLen();document.getElementById('L').textContent=Math.round(L).toLocaleString();
 if(n>0){let l=L/n;document.getElementById('l').textContent=l.toFixed(1);document.getElementById('g').textContent=(-6.643856*Math.log10(l/1000)-3.288).toFixed(2);}
 else{document.getElementById('l').textContent='–';document.getElementById('g').textContent='–';}}
cv.onclick=e=>{if(moveMode)return;const r=cv.getBoundingClientRect();const x=(e.clientX-r.left)/scale,y=(e.clientY-r.top)/scale;
 if(calibrating){calibPts.push([x,y]);if(calibPts.length>2)calibPts.shift();computeCalib();draw();return;}
 let p=[x,y];if(document.getElementById('snap').checked)p=snapToGrid(x,y);
 clicks[method].push(p);draw();persist(false);};
// remove the nearest mark with right-click
cv.oncontextmenu=e=>{e.preventDefault();if(calibrating||!G)return;const r=cv.getBoundingClientRect();
 let x=(e.clientX-r.left)/scale,y=(e.clientY-r.top)/scale,arr=clicks[method],bi=-1,bd=14/scale;
 arr.forEach((p,i)=>{let dd=Math.hypot(p[0]-x,p[1]-y);if(dd<bd){bd=dd;bi=i;}});
 if(bi>=0){arr.splice(bi,1);draw();persist(false);toast('Mark removed');}};
// image adjustments
function onAdj(){adj.b=+document.getElementById('bright').value;adj.c=+document.getElementById('contrast').value;adj.inv=document.getElementById('invert').checked?1:0;draw();}
function resetAdj(){document.getElementById('bright').value=1;document.getElementById('contrast').value=1;document.getElementById('invert').checked=false;onAdj();}
// snap-to-grid helpers
function nearestOnSeg(px,py,x1,y1,x2,y2){let dx=x2-x1,dy=y2-y1,t=((px-x1)*dx+(py-y1)*dy)/((dx*dx+dy*dy)||1);t=Math.max(0,Math.min(1,t));return[x1+t*dx,y1+t*dy];}
function snapToGrid(x,y){let best=[x,y],bd=1e9;
 if(method=='circle'){G.radii.forEach(r=>{let dx=x-G.cx,dy=y-G.cy,L=Math.hypot(dx,dy)||1,px=G.cx+dx/L*r,py=G.cy+dy/L*r,d=Math.hypot(px-x,py-y);if(d<bd){bd=d;best=[px,py];}});}
 else{G.lines.forEach(L=>{let p=nearestOnSeg(x,y,L[0],L[1],L[2],L[3]),d=Math.hypot(p[0]-x,p[1]-y);if(d<bd){bd=d;best=p;}});}
 return best;}
// loupe (magnifier)
const loupe=document.getElementById('loupe'),lctx=loupe.getContext('2d');
function toggleLoupe(){loupeOn=!loupeOn;document.getElementById('loupeBtn').classList.toggle('on',loupeOn);if(!loupeOn)loupe.style.display='none';}
cv.addEventListener('mousemove',e=>{if(!loupeOn||!G)return;const r=cv.getBoundingClientRect();
 let ix=(e.clientX-r.left)/scale,iy=(e.clientY-r.top)/scale,Z=3,S=loupe.width/Z;
 lctx.clearRect(0,0,loupe.width,loupe.height);lctx.save();
 lctx.beginPath();lctx.arc(loupe.width/2,loupe.height/2,loupe.width/2,0,7);lctx.clip();
 lctx.filter=`brightness(${adj.b}) contrast(${adj.c}) invert(${adj.inv})`;
 lctx.drawImage(img,ix-S/2,iy-S/2,S,S,0,0,loupe.width,loupe.height);lctx.filter='none';
 lctx.strokeStyle='rgba(59,130,246,.9)';lctx.lineWidth=1;
 lctx.beginPath();lctx.moveTo(90-9,90);lctx.lineTo(90+9,90);lctx.moveTo(90,90-9);lctx.lineTo(90,90+9);lctx.stroke();lctx.restore();
 let lx=e.clientX+22,ly=e.clientY+22;if(lx+186>window.innerWidth)lx=e.clientX-202;if(ly+186>window.innerHeight)ly=e.clientY-202;
 loupe.style.left=lx+'px';loupe.style.top=ly+'px';loupe.style.display='block';});
cv.addEventListener('mouseleave',()=>{loupe.style.display='none';});
// middle-mouse drag to pan
let panning=false,panSX,panSY,panL,panT;
cv.addEventListener('mousedown',e=>{if(e.button!=1)return;e.preventDefault();let w=document.querySelector('.canvaswrap');panning=true;panSX=e.clientX;panSY=e.clientY;panL=w.scrollLeft;panT=w.scrollTop;});
window.addEventListener('mousemove',e=>{if(!panning)return;let w=document.querySelector('.canvaswrap');w.scrollLeft=panL-(e.clientX-panSX);w.scrollTop=panT-(e.clientY-panSY);});
window.addEventListener('mouseup',()=>{panning=false;});
// ✥ move the Abrams circle grid (per-image offset; length — and so ℓ/G — unchanged)
let moveMode=false,movingGrid=false,mvSX,mvSY,mvCX,mvCY;
function exitMove(){moveMode=false;movingGrid=false;document.getElementById('moveBtn').classList.remove('on');cv.style.cursor='';}
async function toggleMove(){if(method!='circle'){toast('Circle grid only — switch to the Abrams tab',1);return;}
 if(!cur||!G)return;
 if(moveMode){exitMove();return;}
 if(clicks.circle.length&&!await uiConfirm('This image already has '+clicks.circle.length+' circle marks, counted on the CURRENT circle position. Moving the circles invalidates those marks — clear and recount afterwards. Move anyway?','Move'))return;
 moveMode=true;document.getElementById('moveBtn').classList.add('on');cv.style.cursor='move';toast('Drag the image to reposition the circles · click ✥ again to finish');}
function clampC(){let rm=Math.max(...G.radii);
 if(2*rm<=G.w)G.cx=Math.min(Math.max(rm,G.cx),G.w-rm);else G.cx=G.w/2;
 if(2*rm<=G.h)G.cy=Math.min(Math.max(rm,G.cy),G.h-rm);else G.cy=G.h/2;}
cv.addEventListener('mousedown',e=>{if(!moveMode||e.button!=0)return;e.preventDefault();movingGrid=true;mvSX=e.clientX;mvSY=e.clientY;mvCX=G.cx;mvCY=G.cy;});
window.addEventListener('mousemove',e=>{if(!movingGrid)return;G.cx=mvCX+(e.clientX-mvSX)/scale;G.cy=mvCY+(e.clientY-mvSY)/scale;clampC();draw();});
window.addEventListener('mouseup',async()=>{if(!movingGrid)return;movingGrid=false;
 let r=await(await fetch('/api/circle_offset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,dx:G.cx-G.w/2,dy:G.cy-G.h/2})})).json();
 if(r.ok){G.cx=r.cx;G.cy=r.cy;draw();toast('Circle position saved for '+cur);}else toast('Could not save circle position',1);});
async function centerCircles(){if(method!='circle'){toast('Circle grid only — switch to the Abrams tab',1);return;}
 if(!cur||!G)return;
 if(Math.abs(G.cx-G.w/2)<0.5&&Math.abs(G.cy-G.h/2)<0.5){toast('Circles are already centred');return;}
 if(clicks.circle.length&&!await uiConfirm('This image has '+clicks.circle.length+' circle marks counted on the CURRENT circle position. Re-centre anyway?','Re-centre'))return;
 let r=await(await fetch('/api/circle_offset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,dx:0,dy:0})})).json();
 if(r.ok){G.cx=r.cx;G.cy=r.cy;draw();toast('Circles re-centred');}}
// adjustable grid density
async function loadGrid(){let g=await(await fetch('/api/grid')).json();
 document.getElementById('gridLines').innerHTML=g.line_options.map(o=>`<option ${o==g.grid.lines?'selected':''}>${o}</option>`).join('');}
async function setGrid(){let circles='3',lines=document.getElementById('gridLines').value;
 await fetch('/api/grid',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({circles,lines})});
 if(cur){G=await(await fetch('/api/geom/'+cur)).json();draw();updateStale();}loadSummary();
 toast('Lines: '+lines+' (existing counts keep their own grid)');}
// overlays
function saveOverlay(){if(!cur)return;window.open('/overlay/'+encodeURIComponent(cur)+'.png?method='+method,'_blank');}
function exportOverlays(){window.open('/overlays.zip?method='+method,'_blank');}
function exportXlsx(){window.open('/export.xlsx?method='+method,'_blank');}
function startCalib(){if(!G){toast('Open an image first',1);return;}calibrating=true;calibPts=[];document.getElementById('calib').style.display='flex';document.getElementById('calibBtn').classList.add('primary');computeCalib();draw();}
function cancelCalib(){calibrating=false;document.getElementById('calib').style.display='none';document.getElementById('calibBtn').classList.remove('primary');draw();}
function computeCalib(){let el=document.getElementById('calibUmpp');
 if(calibPts.length<2){document.getElementById('calibPx').textContent='0 px';el.textContent='– µm/px';return;}
 let px=Math.hypot(calibPts[1][0]-calibPts[0][0],calibPts[1][1]-calibPts[0][1]);
 let known=parseFloat(document.getElementById('calibKnown').value)||0;
 document.getElementById('calibPx').textContent=px.toFixed(1)+' px';
 el.textContent=(px>0&&known>0)?(known/px).toFixed(6)+' µm/px':'– µm/px';}
async function applyCalib(){if(calibPts.length<2){toast('Click both ends of the scale bar',1);return;}
 let px=Math.hypot(calibPts[1][0]-calibPts[0][0],calibPts[1][1]-calibPts[0][1]);
 let known=parseFloat(document.getElementById('calibKnown').value)||0;
 if(px<=0||known<=0){toast('Need two points and a length',1);return;}
 let umpp=known/px,scope=document.getElementById('calibScope').value;
 let r=await(await fetch('/api/set_umpp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,umpp,scope})})).json();
 if(r.ok){toast('Calibrated '+umpp.toFixed(6)+' µm/px ('+r.updated+' image'+(r.updated>1?'s':'')+')');cancelCalib();let keep=cur;await refreshImages();await select(keep);loadSummary();}else toast('Calibrate failed',1);}
async function deleteImg(){if(!cur)return;if(!await uiConfirm('Delete '+cur+' and its measurements? This cannot be undone.'))return;
 let r=await(await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur})})).json();
 if(r.ok){toast('Deleted '+cur);let i=imgs.findIndex(x=>x.name==cur);imgs=imgs.filter(x=>x.name!=cur);let nx=imgs[Math.min(i,imgs.length-1)];cur=null;renderList();if(nx)select(nx.name);else ctx.clearRect(0,0,cv.width,cv.height);loadSummary();}
 else if(r.error=='not found'){toast(cur+' was already deleted elsewhere — refreshing list');cur=null;await refreshImages();if(imgs.length)select(imgs[0].name);else ctx.clearRect(0,0,cv.width,cv.height);loadSummary();}
 else toast('Delete failed'+(r.error?': '+r.error:''),1);}
function undo(){clicks[method].pop();draw();persist(false);}
function clr(){clicks[method]=[];draw();persist(false);}
async function persist(dn){await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,method,clicks:clicks[method],done:dn})});
 if(G&&G.stored_len&&G.cur_len)G.stored_len[method]=G.cur_len[method];updateStale();
 let it=imgs.find(x=>x.name==cur);if(it){if(method=='circle'){it.n_circle=clicks.circle.length;if(dn)it.done_circle=true;}else{it.n_line=clicks.line.length;if(dn)it.done_line=true;}}}
async function markdone(){await persist(true);renderList();loadSummary();let i=imgs.findIndex(x=>x.name==cur);if(i<imgs.length-1)select(imgs[i+1].name);else toast('All images in this list reviewed');}
function step(d){let i=imgs.findIndex(x=>x.name==cur);let j=i+d;if(j>=0&&j<imgs.length)select(imgs[j].name);}
document.onkeydown=e=>{if(document.getElementById('dlg').classList.contains('show')){if(e.key=='Escape')dlgClose(false);else if(e.key=='Enter'&&!dlgHasInput)dlgClose(true);return;}
 if(e.key=='Escape'&&moveMode){exitMove();return;}
 if(e.key=='Escape'&&msel.size){mselClear();return;}
 if(e.target.tagName=='INPUT'||e.target.tagName=='SELECT')return;
 if(e.key=='z')undo();else if(e.key=='d')markdone();else if(e.key=='ArrowLeft')step(-1);else if(e.key=='ArrowRight')step(1);
 else if(e.key=='1')setMethod('circle');else if(e.key=='2')setMethod('line');};
async function doUpload(){let files=document.getElementById('fileIn').files;if(!files.length){toast('Pick image file(s) first',1);return;}
 let cond=document.getElementById('condIn').value.trim(),val=document.getElementById('valIn').value,umpp=document.getElementById('umppIn').value;
 if(!cond){toast('Enter a condition label first',1);return;}
 let fi=document.getElementById('folderIn'),folder=fi&&fi.value?fi.value:'';
 let ok=0,fail=0,first=null,failMsg='';
 for(let i=0;i<files.length;i++){
  let fd=new FormData();fd.append('file',files[i]);fd.append('condition',cond);if(val!=='')fd.append('value',val);fd.append('umpp',umpp);if(folder)fd.append('folder',folder);
  toast('Uploading '+(i+1)+' / '+files.length+' …');
  try{let r=await(await fetch('/api/upload',{method:'POST',body:fd})).json();if(r.ok){ok++;if(!first)first=r.name;}else{fail++;if(!failMsg)failMsg=r.error||'';}}catch(e){fail++;if(!failMsg)failMsg='server rejected the file ('+(e&&e.message||'network error')+')';}}
 await refreshImages();if(first)select(first);
 document.getElementById('fileIn').value='';
 if(fail&&!ok){toast(failMsg||('Upload failed ('+fail+')'),1);return;}
 let msg='Imported '+ok+' image'+(ok!=1?'s':'');
 if(fail)msg+=' · '+fail+' failed';
 toast(msg,fail&&!ok);}
async function loadSummary(){let s=await(await fetch('/api/summary?method='+method)).json();
 document.getElementById('sumTitle').textContent='Per-condition summary · '+(method=='circle'?'Abrams circles':'Heyn lines');
 document.getElementById('sumNote').textContent=s.length?'%RA ≤10% = acceptable (ASTM E112 §15); ≥5 fields needed for a valid CI':'No measurements yet — start clicking boundaries.';
 document.getElementById('sumBody').innerHTML=s.map(r=>{
   let ra=(r.ra_pct==null)?'–':(r.ra_pct+'%');
   let raCol=(r.ra_pct==null)?'#9099a8':(r.ra_pct<=10?'#86efac':'#f59e0b');
   let fld=r.enough?(''+r.imgs):`<span style="color:#f59e0b" title="ASTM E112 needs ≥5 fields for a valid confidence interval">${r.imgs} ⚠</span>`;
   return `<tr><td>${esc(r.condition)}</td><td>${r.value==null?'–':r.value}</td><td>${fld}</td><td>${r.tot_int}</td><td>${r.l_mean}</td><td>${r.l_sd}</td><td>${r.l_ci95}</td><td style="color:${raCol};font-weight:600">${ra}</td><td><span class="pill g">${r.G_mean}</span></td></tr>`;
 }).join('');}
function showHelp(v){document.getElementById('help').classList.toggle('show',!!v);}
document.getElementById('help').onclick=e=>{if(e.target.id=='help')showHelp(0);};
/* ---------- guided tour (coach marks / spotlight) ---------- */
const TOUR_STEPS=[
 {sel:null,title:'Welcome 👋',
  body:'This one-minute tour points at every tool and explains how to use it. Move with → / Enter, go back with ←, or press Esc to skip. You can replay it any time with the 🎓 button in the top bar.'},
 {sel:'.seg',place:'bottom',title:'Two counting methods',
  body:'Switch between the Abrams three-circle grid (the E112 referee method) and Heyn straight lines. Each method keeps its own clicks per image — press 1 or 2 to switch from the keyboard.'},
 {sel:'#list',place:'right',title:'Folders & images',
  body:'Your micrographs, grouped into folders. Click an image to open it, drag it onto a folder to move it, Ctrl/Shift-click to select several at once. A green dot means the image is marked done for the current method.'},
 {sel:'#search',place:'right',title:'Filter images',
  body:'Type part of an image name to filter the whole folder tree — handy once you have dozens of fields imported.'},
 {sel:'.import',place:'right',title:'Import photos',
  body:'Pick one or more JPEG/TIFF micrographs, give them a Condition label (this groups the summary and the exported chart), an optional numeric Value for ordering, the µm-per-pixel scale, and an optional folder — then Upload & open. Unknown scale? Import at 1.0 and use 📏 Calibrate later.'},
 {sel:'#wrap',place:'top',title:'Count intercepts — the core action',
  body:'A red test grid of known total length is drawn over the image. Click every point where the grid crosses a real grain boundary (skip twins and scratches). Right-click removes the nearest mark, middle-drag pans. Every click is auto-saved.'},
 {sel:'#countGroup',place:'bottom',title:'Undo · Clear · Done',
  body:'Undo (Z) removes the last click, Clear wipes this method’s marks on the current image, and Mark done & next (D) flags it complete and jumps to the next image.'},
 {sel:'#zoomGroup',place:'bottom',title:'Zoom & fit',
  body:'Zoom in or out, or Fit the image to the window. The ← / → arrow keys step between images in the list.'},
 {sel:'#calibBtn',place:'bottom',title:'Calibrate the scale',
  body:'If your micrograph has a scale bar: click 📏, click the two ends of the bar, type its known length in µm, and apply the resulting µm/px to this image, its whole condition, or all images. Stored results rescale automatically.'},
 {sel:'.adjustbar',place:'bottom',title:'See boundaries better',
  body:'Brightness, contrast and invert change the display only — never the data. The 🔍 Loupe is a 3× magnifier that follows your cursor, snap-to-grid pulls each click exactly onto the nearest test line, and the lines selector sets the Heyn grid density.'},
 {sel:'.stats',place:'top',title:'Live results',
  body:'N is the number of boundary crossings you’ve clicked (amber below the ASTM-recommended 40 per field). Mean intercept ℓ = test length ÷ N, then G is the ASTM grain-size number. Test length is the grid’s total length at this image’s calibration.'},
 {sel:'#imgMetaCtls',place:'bottom',title:'Regroup an image',
  body:'Retype the condition label to move this image into a different summary group, or use the dropdown beside it to move it to another folder. Neither changes the measurement.'},
 {sel:'#exportGroup',place:'bottom',title:'Export your data',
  body:'Download every measurement as CSV, an XLSX workbook with a native grain-size chart (mean ℓ with 95% CI error bars), or a zip of annotated overlay PNGs for the current method.'},
 {sel:'.results',place:'top',title:'Per-condition summary',
  body:'Each condition’s mean ℓ, SD, 95% CI (Student’s t) and %RA. ASTM E112 wants %RA ≤ 10% and ≥ 5 fields per condition — short rows are flagged ⚠. G is computed from the mean ℓ, never by averaging G values.'},
 {sel:'#helpBtn',place:'bottom',title:'Full method reference',
  body:'The ? button opens the built-in reference: formulas, counting rules, recommended practice and all keyboard shortcuts. Replay this tour any time with 🎓. Happy counting!'}
];
let tourIdx=0,tourOpen=false;
function startTour(){if(tourOpen)return;tourOpen=true;
 ['tourBackdrop','tourHi','tourBubble'].forEach(id=>{let el=document.getElementById(id);if(el)el.style.display='block';});
 document.addEventListener('keydown',tourKeys,true);
 window.addEventListener('resize',tourReflow);
 tourShow(0,1);}
function endTour(){if(!tourOpen)return;tourOpen=false;
 ['tourBackdrop','tourHi','tourBubble'].forEach(id=>{let el=document.getElementById(id);if(el)el.style.display='none';});
 document.removeEventListener('keydown',tourKeys,true);
 window.removeEventListener('resize',tourReflow);
 try{localStorage.setItem('gsa_tour_done','1');}catch(e){}}
function tourShow(i,dir){dir=dir||1;
 while(i>=0&&i<TOUR_STEPS.length){const s=TOUR_STEPS[i];
  if(!s.sel)break;
  let el=null;try{el=document.querySelector(s.sel);}catch(e){}
  if(el)break;
  i+=dir;}                                    // skip steps whose target is missing
 if(i>=TOUR_STEPS.length){endTour();return;}
 if(i<0){return;}
 tourIdx=i;const s=TOUR_STEPS[i];
 document.getElementById('tourTitle').textContent=s.title;
 document.getElementById('tourBody').textContent=s.body;
 document.getElementById('tourCount').textContent=(i+1)+' / '+TOUR_STEPS.length;
 document.getElementById('tourBackBtn').disabled=(i===0);
 document.getElementById('tourNextBtn').textContent=(i===TOUR_STEPS.length-1)?'Done ✓':'Next →';
 tourReflow();}
function tourNext(){if(tourIdx>=TOUR_STEPS.length-1)endTour();else tourShow(tourIdx+1,1);}
function tourBack(){if(tourIdx>0)tourShow(tourIdx-1,-1);}
function tourKeys(e){if(!tourOpen)return;         // takes over keys ONLY while open
 if(e.key==='ArrowRight'||e.key==='Enter'){e.preventDefault();e.stopImmediatePropagation();tourNext();}
 else if(e.key==='ArrowLeft'){e.preventDefault();e.stopImmediatePropagation();tourBack();}
 else if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();endTour();}
 else e.stopImmediatePropagation();}               // don't let z/d/1/2 fire underneath
function tourReflow(){if(!tourOpen)return;
 const s=TOUR_STEPS[tourIdx];let el=null;
 if(s.sel){try{el=document.querySelector(s.sel);}catch(e){}}
 const hi=document.getElementById('tourHi'),bb=document.getElementById('tourBubble');
 if(!hi||!bb)return;
 let r=null;
 if(el){try{el.scrollIntoView({block:'nearest',inline:'nearest'});}catch(e){}
  r=el.getBoundingClientRect();
  if(!(r.width>0&&r.height>0))r=null;}             // empty/zero-size target → centre bubble
 const pad=6,m=14;
 if(r){hi.style.borderWidth='2px';
  hi.style.left=(r.left-pad)+'px';hi.style.top=(r.top-pad)+'px';
  hi.style.width=(r.width+2*pad)+'px';hi.style.height=(r.height+2*pad)+'px';}
 else{hi.style.borderWidth='0px';                  // dim-only backdrop, no spotlight
  hi.style.left=(innerWidth/2)+'px';hi.style.top=(innerHeight/2)+'px';
  hi.style.width='0px';hi.style.height='0px';}
 const bw=bb.offsetWidth,bh=bb.offsetHeight;
 let x,y;
 if(!r){x=(innerWidth-bw)/2;y=(innerHeight-bh)/2;}
 else{
  const put=p=>p==='right'?[r.right+pad+m,r.top]
             :p==='left' ?[r.left-pad-m-bw,r.top]
             :p==='top'  ?[r.left,r.top-pad-m-bh]
             :[r.left,r.bottom+pad+m];
  const fits=c=>c[0]>=8&&c[1]>=8&&c[0]+bw<=innerWidth-8&&c[1]+bh<=innerHeight-8;
  const pref=s.place||'bottom';
  const order=[pref].concat(['bottom','right','top','left'].filter(p=>p!==pref));
  x=null;
  for(const p of order){const c=put(p);if(fits(c)){x=c[0];y=c[1];break;}}
  if(x===null){const c=put(pref);x=c[0];y=c[1];}   // nothing fits → clamp preferred
  x=Math.max(8,Math.min(x,innerWidth-bw-8));
  y=Math.max(8,Math.min(y,innerHeight-bh-8));}
 bb.style.left=x+'px';bb.style.top=y+'px';}
document.getElementById('tourNextBtn').onclick=tourNext;
document.getElementById('tourBackBtn').onclick=tourBack;
document.getElementById('tourSkip').onclick=endTour;
init().then(()=>{setTimeout(()=>{                  // first run only: auto-launch tour
 try{if(!localStorage.getItem('gsa_tour_done'))startTour();}catch(e){}},600);});
</script></body></html>
"""

if __name__ == "__main__":
    try:
        from waitress import serve
        print(f"Grain Size Analyzer on :{PORT} (waitress)")
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=PORT, debug=False)
