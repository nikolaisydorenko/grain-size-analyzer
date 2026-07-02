#!/usr/bin/env python3
"""
Build the display cache (cache/*.jpg + cache/index.json) the app serves, from a
folder of micrographs (TIFF/JPEG/PNG). Run it once per group of images, giving
the group a free-text --condition label (e.g. an alloy, heat treatment, batch,
or sample name) and, optionally, a numeric --value used to order the summary
table and as the X-axis of the exported chart.

Examples
--------
  python3 scripts/prepare_cache.py "/imgs/as-cast" --condition as-cast
  python3 scripts/prepare_cache.py "/imgs/annealed" --condition annealed-300C --value 300 --append
  python3 scripts/prepare_cache.py "/imgs/batch1" --condition "Batch 1" --umpp 0.53 --append
"""
import argparse, json, os, sys, glob
from PIL import Image

EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "cache")
DEFAULT_UMPP = 1.0


def main():
    ap = argparse.ArgumentParser(description="Build cache/ + index.json from a folder of micrographs")
    ap.add_argument("folder", help="folder of source images")
    ap.add_argument("--condition", required=True,
                    help="condition label for all images (e.g. 'as-cast', 'annealed-300C')")
    ap.add_argument("--value", type=float, default=None,
                    help="optional numeric value for the condition (orders the summary; chart X-axis)")
    ap.add_argument("--umpp", type=float, default=DEFAULT_UMPP,
                    help=f"calibration µm/px (default {DEFAULT_UMPP} = uncalibrated; "
                         "set the real scale, or calibrate later in the app)")
    ap.add_argument("--quality", type=int, default=88, help="JPEG quality (default 88)")
    ap.add_argument("--append", action="store_true", help="add to an existing index.json instead of replacing")
    args = ap.parse_args()

    os.makedirs(CACHE, exist_ok=True)
    idx_path = os.path.join(CACHE, "index.json")
    index = json.load(open(idx_path)) if (args.append and os.path.exists(idx_path)) else []
    have = {d["name"] for d in index}

    files = [f for f in sorted(glob.glob(os.path.join(args.folder, "*")))
             if f.lower().endswith(EXTS)]
    if not files:
        sys.exit(f"no images found in {args.folder}")

    added = 0
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        name = stem
        i = 1
        while name in have:
            name = f"{stem}_{i}"; i += 1
        try:
            im = Image.open(f).convert("RGB")
        except Exception as e:
            print(f"  skip {os.path.basename(f)}: {e}"); continue
        im.save(os.path.join(CACHE, name + ".jpg"), quality=args.quality)
        index.append(dict(condition=args.condition, value=args.value, name=name,
                          w=im.size[0], h=im.size[1], umpp=args.umpp,
                          folder=args.condition))
        have.add(name); added += 1
        print(f"  + {name}  [{args.condition}]  {im.size[0]}x{im.size[1]}  {args.umpp} µm/px")

    json.dump(index, open(idx_path, "w"))
    print(f"\nwrote {idx_path}: {added} added, {len(index)} total")


if __name__ == "__main__":
    main()
