#!/usr/bin/env python3
"""
Hours of direct sun from a DSM, for a single day.

Usage:
    python sun_hours.py dsm.tif --dem dem.tif --out sun_hours.tif
    python sun_hours.py dsm.tif --date 2026-12-21 --pm-start 12 --pm-end 16

Install:
    pip install rasterio numpy pandas pvlib

Outputs (each a 2-band GeoTIFF):
    band 1 = hours of direct sun over the whole day
    band 2 = hours of direct sun between --pm-start and --pm-end (local clock time)

    <out>            includes roofs/treetops
    <out>_ground.tif same, but cells above --ground-threshold m over the DEM
                     (buildings/trees) are set to nodata, if --dem is given
"""
import os

# Avoid a clash with the PROJ database that ships with PostgreSQL/PostGIS.
# This must happen before rasterio is imported.
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd
import rasterio
from pvlib import solarposition
from rasterio.warp import transform as warp_transform


def sun_positions(lat, lon, day, interval_min, tz):
    """Sun azimuth/elevation and local clock hour across one local day."""
    start = pd.Timestamp(day.isoformat(), tz=tz)
    end = pd.Timestamp((day + timedelta(days=1)).isoformat(), tz=tz)
    times = pd.date_range(start, end, freq=f"{interval_min}min", inclusive="left")
    pos = solarposition.get_solarposition(times, lat, lon)
    local_hour = np.asarray(times.hour + times.minute / 60.0)
    keep = pos["apparent_elevation"].to_numpy() > 2.0  # ignore sun skimming the horizon
    return (pos["azimuth"].to_numpy()[keep],
            pos["apparent_elevation"].to_numpy()[keep],
            local_hour[keep])


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


def write_two_band(path, profile, total, pm, pm_label):
    prof = profile.copy()
    prof.update(dtype="float32", count=2, nodata=-9999, compress="deflate")
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(total.astype("float32"), 1)
        dst.write(pm.astype("float32"), 2)
        dst.set_band_description(1, "Direct sun hours (whole day)")
        dst.set_band_description(2, f"Direct sun hours ({pm_label})")


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
    ap.add_argument("--tz", default="Pacific/Auckland",
                    help="timezone used for the afternoon window (handles daylight saving)")
    ap.add_argument("--pm-start", type=float, default=12.0, help="afternoon window start (local hour)")
    ap.add_argument("--pm-end", type=float, default=16.0, help="afternoon window end (local hour)")
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

    az, el, local_hour = sun_positions(lat, lon, day, args.interval, args.tz)
    in_pm = (local_hour >= args.pm_start) & (local_hour < args.pm_end)
    pm_label = f"{args.pm_start:g}:00-{args.pm_end:g}:00 local"
    print(f"{len(az)} sun positions above the horizon, {int(in_pm.sum())} in the {pm_label} window")

    sunny_total = np.zeros(dsm.shape, dtype="float32")
    sunny_pm = np.zeros(dsm.shape, dtype="float32")
    for i, (a, e, is_pm) in enumerate(zip(az, el, in_pm), 1):
        sunny = ~shadow_mask(dsm, a, e, res, args.maxdist)
        sunny_total += sunny
        if is_pm:
            sunny_pm += sunny
        if i % 5 == 0 or i == len(az):
            print(f"  {i}/{len(az)}", end="\r")
    print()

    step_h = args.interval / 60.0
    total = sunny_total * step_h
    pm = sunny_pm * step_h
    total[~valid] = -9999
    pm[~valid] = -9999

    write_two_band(args.out, profile, total, pm, pm_label)
    print(f"Wrote {args.out}")

    if args.dem:
        with rasterio.open(args.dem) as d:
            if d.shape != dsm.shape or d.transform != profile["transform"]:
                raise SystemExit("DEM is not aligned with the DSM. Resample/clip it to match first.")
            dem = d.read(1).astype("float32")
            if d.nodata is not None:
                dem[dem == d.nodata] = np.nan
        elevated = (dsm - dem) > args.ground_threshold
        total_g, pm_g = total.copy(), pm.copy()
        total_g[elevated] = -9999
        pm_g[elevated] = -9999
        out_ground = args.out.replace(".tif", "_ground.tif")
        write_two_band(out_ground, profile, total_g, pm_g, pm_label)
        print(f"Wrote {out_ground}")


if __name__ == "__main__":
    main()