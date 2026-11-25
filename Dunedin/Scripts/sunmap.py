#!/usr/bin/env python3
"""
Hours of direct sun from a DSM, for a single day.

Usage:
    python sun_hours.py dsm.tif --dem dem.tif --out sun_hours.tif
    python sun_hours.py dsm.tif --date 2026-12-21 --interval 15 --maxdist 150

Install:
    pip install rasterio numpy pandas pvlib

Outputs:
    <out>                  hours of direct sun per cell (includes roofs/treetops)
    <out>_ground.tif       same, but cells >2 m above the DEM (buildings/trees)
                           are set to nodata, if --dem is given
"""
import argparse
from datetime import date

import os
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

import numpy as np
import pandas as pd
import rasterio
from pvlib import solarposition
from rasterio.warp import transform as warp_transform


def sun_positions(lat, lon, day, interval_min):
    """Sun azimuth/elevation across the local solar day (no timezone needed)."""
    # Start 'lon/15' hours before UTC midnight so the 24 h window matches the local day
    start = pd.Timestamp(day, tz="UTC") - pd.Timedelta(hours=lon / 15.0)
    times = pd.date_range(start, periods=int(24 * 60 / interval_min), freq=f"{interval_min}min")
    pos = solarposition.get_solarposition(times, lat, lon)
    pos = pos[pos["apparent_elevation"] > 2.0]  # ignore sun skimming the horizon
    return pos["azimuth"].to_numpy(), pos["apparent_elevation"].to_numpy()


def shadow_mask(dsm, az_deg, el_deg, res, maxdist):
    """True where a cell is in shadow for one sun position.

    For each step along the ray towards the sun, compare the DSM at that
    offset with this cell. If it rises above the sun's ray, the cell is shaded.
    """
    rows, cols = dsm.shape
    shadow = np.zeros(dsm.shape, dtype=bool)
    tan_el = np.tan(np.radians(el_deg))
    zrange = np.nanmax(dsm) - np.nanmin(dsm)
    sx = np.sin(np.radians(az_deg))    # east component of direction to the sun
    sy = np.cos(np.radians(az_deg))    # north component

    for k in range(1, int(maxdist / res) + 1):
        dc = int(round(k * sx))        # +columns = east
        dr = int(round(-k * sy))       # +rows = south, so north is negative
        if dr == 0 and dc == 0:
            continue
        dist = np.hypot(dr, dc) * res
        if dist * tan_el > zrange:     # nothing in the scene is tall enough to matter
            break
        r0, r1 = max(0, -dr), min(rows, rows - dr)
        c0, c1 = max(0, -dc), min(cols, cols - dc)
        if r0 >= r1 or c0 >= c1:
            break
        target = dsm[r0:r1, c0:c1]
        source = dsm[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
        with np.errstate(invalid="ignore"):
            shadow[r0:r1, c0:c1] |= (source - target) > dist * tan_el
    return shadow


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dsm")
    ap.add_argument("--dem", help="optional DEM, used to make a ground-only output")
    ap.add_argument("--out", default="sun_hours.tif")
    ap.add_argument("--date", help="YYYY-MM-DD (default: winter solstice for your hemisphere)")
    ap.add_argument("--interval", type=int, default=30, help="minutes between sun positions")
    ap.add_argument("--maxdist", type=float, default=150.0, help="max shadow length to check (m)")
    ap.add_argument("--ground-threshold", type=float, default=2.0,
                    help="nDSM height (m) above which a cell counts as building/tree")
    args = ap.parse_args()

    with rasterio.open(args.dsm) as src:
        dsm = src.read(1).astype("float32")
        profile = src.profile
        nodata = src.nodata
        res = abs(src.transform.a)
        if abs(abs(src.transform.e) - res) > 1e-6:
            raise SystemExit("Non-square pixels: resample the DSM first.")
        if src.crs is None or src.crs.is_geographic:
            raise SystemExit("DSM must be in a projected CRS (metres).")
        # Centre of the raster -> lat/lon
        cx, cy = src.transform * (src.width / 2, src.height / 2)
        lon, lat = (v[0] for v in warp_transform(src.crs, "EPSG:4326", [cx], [cy]))

    if nodata is not None:
        dsm[dsm == nodata] = np.nan
    valid = ~np.isnan(dsm)

    if args.date:
        day = date.fromisoformat(args.date)
    else:
        day = date(date.today().year, 6, 21) if lat < 0 else date(date.today().year, 12, 21)
    print(f"Centre: {lat:.4f}, {lon:.4f}  |  date: {day}  |  resolution: {res} m")

    az, el = sun_positions(lat, lon, day, args.interval)
    print(f"{len(az)} sun positions above the horizon")

    sunny_steps = np.zeros(dsm.shape, dtype="float32")
    for i, (a, e) in enumerate(zip(az, el), 1):
        sunny_steps += ~shadow_mask(dsm, a, e, res, args.maxdist)
        if i % 5 == 0 or i == len(az):
            print(f"  {i}/{len(az)}", end="\r")
    print()

    hours = sunny_steps * (args.interval / 60.0)
    hours[~valid] = -9999

    profile.update(dtype="float32", count=1, nodata=-9999, compress="deflate")
    with rasterio.open(args.out, "w", **profile) as dst:
        dst.write(hours.astype("float32"), 1)
    print(f"Wrote {args.out}")

    if args.dem:
        with rasterio.open(args.dem) as d:
            if d.shape != dsm.shape or d.transform != profile["transform"]:
                raise SystemExit("DEM is not aligned with the DSM. Resample/clip it to match first.")
            dem = d.read(1).astype("float32")
            if d.nodata is not None:
                dem[dem == d.nodata] = np.nan
        ndsm = dsm - dem
        ground = hours.copy()
        ground[ndsm > args.ground_threshold] = -9999
        out_ground = args.out.replace(".tif", "_ground.tif")
        with rasterio.open(out_ground, "w", **profile) as dst:
            dst.write(ground.astype("float32"), 1)
        print(f"Wrote {out_ground}")


if __name__ == "__main__":
    main()