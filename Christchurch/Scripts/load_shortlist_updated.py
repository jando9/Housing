#!/usr/bin/env python3
"""
Load a CSV of houses you've shortlisted into PostGIS, geocoded against the LINZ
NZ Street Address layer (loaded as linz.nz_street_address, geometry column 'geom', EPSG:2193).

    pip install "psycopg[binary]"
    Set PASSWORD in the repository-root .env file, then run the batch file.
    python load_shortlist.py shortlist.csv

CSV columns (header row required; only 'address' is mandatory):
    address, suburb, listing_id, price_display, asking_price, bedrooms, bathrooms,
    floor_area_m2, land_area_m2, notes

The Trade Me URL is built for you from suburb + listing_id, e.g.
    https://www.trademe.co.nz/a/property/residential/sale/canterbury/christchurch-city/sydenham/listing/1234567890
'suburb' can be written as "St Albans" or "st-albans". It is also used to help match
the street address against LINZ. 'listing_id' may be the bare number or a pasted URL.

Rows whose address can't be matched confidently are printed so you can fix the
spelling and re-run. Re-running is safe: rows are upserted on the matched address.
"""
import csv
import os
import re
import sys
from pathlib import Path

print(f"load_shortlist.py starting (Python {sys.version.split()[0]}, "
      f"file {os.path.abspath(__file__)})", flush=True)

import psycopg

ADDR_TABLE = "linz.nz_street_address"   # change here if you loaded it under another name


def load_database_password():
    password = os.environ.get("PASSWORD")
    if password is None:
        env_path = Path(__file__).resolve().parents[2] / ".env"
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            sys.exit(f"Could not read database password from {env_path}: {exc}")

        for line in lines:
            key, separator, value = line.partition("=")
            if separator and key.strip() == "PASSWORD":
                password = value.strip()
                break

    if password is not None and len(password) >= 2:
        if password[0] == password[-1] and password[0] in {"'", '"'}:
            password = password[1:-1]
    if not password:
        sys.exit("Set PASSWORD in the repository-root .env file.")
    return password


SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS nz_street_address_trgm_ix
    ON {ADDR_TABLE} USING gin (full_address gin_trgm_ops);

CREATE TABLE IF NOT EXISTS shortlist (
    shortlist_id   serial PRIMARY KEY,
    address_id     integer UNIQUE,            -- LINZ address_id
    address_input  text,
    matched_address text,
    match_score    real,
    url            text,                      -- built from suburb + listing_id
    listing_id     bigint,
    suburb         text,
    city           text,
    price_display  text,
    asking_price   numeric,
    bedrooms       smallint,
    bathrooms      smallint,
    floor_area_m2  integer,
    land_area_m2   integer,
    notes          text,
    added_at       timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    geom           geometry(Point, 2193)
);
CREATE INDEX IF NOT EXISTS shortlist_geom_gix ON shortlist USING gist (geom);

-- in case the table was created by an earlier version of this script
ALTER TABLE shortlist ADD COLUMN IF NOT EXISTS listing_id bigint;
ALTER TABLE shortlist ADD COLUMN IF NOT EXISTS suburb text;
ALTER TABLE shortlist ADD COLUMN IF NOT EXISTS city text;
CREATE INDEX IF NOT EXISTS shortlist_listing_id_ix ON shortlist (listing_id);
"""

CANDIDATES_SQL = f"""
SELECT address_id, full_address,
       GREATEST(similarity(full_address, %s), similarity(full_address, %s),
                similarity(full_address, %s)) AS score
FROM {ADDR_TABLE}
WHERE full_address %% %s OR full_address %% %s OR full_address %% %s
ORDER BY score DESC
LIMIT 40
"""

UPSERT_SQL = f"""
INSERT INTO shortlist (
    address_id, address_input, matched_address, match_score, url, listing_id, suburb, city, price_display,
    asking_price, bedrooms, bathrooms, floor_area_m2, land_area_m2, notes, geom
)
SELECT %(address_id)s, %(address_input)s, a.full_address, %(score)s, %(url)s, %(listing_id)s, %(suburb)s, %(city)s, %(price_display)s,
       %(asking_price)s, %(bedrooms)s, %(bathrooms)s, %(floor_area_m2)s, %(land_area_m2)s, %(notes)s, a.geom
FROM {ADDR_TABLE} a
WHERE a.address_id = %(address_id)s
ON CONFLICT (address_id) DO UPDATE SET
    address_input = EXCLUDED.address_input,
    match_score = EXCLUDED.match_score,
    url = EXCLUDED.url,
    listing_id = EXCLUDED.listing_id,
    suburb = EXCLUDED.suburb,
    city = EXCLUDED.city,
    price_display = EXCLUDED.price_display,
    asking_price = EXCLUDED.asking_price,
    bedrooms = EXCLUDED.bedrooms,
    bathrooms = EXCLUDED.bathrooms,
    floor_area_m2 = EXCLUDED.floor_area_m2,
    land_area_m2 = EXCLUDED.land_area_m2,
    notes = EXCLUDED.notes,
    updated_at = now();
"""


def clean(value):
    value = (value or "").strip()
    return value or None


def to_int(value):
    value = clean(value)
    if value is None:
        return None
    try:
        return int(float(re.sub(r"[^\d.]", "", value)))
    except ValueError:
        return None


def parse_address_parts(text: str):
    """Return (unit, street number, normalised text) for common NZ address formats."""
    value = (text or "").lower().strip()
    value = re.sub(r"\b(apartment|apt|unit|flat)\s*#?\s*([a-z0-9-]+)", r"unit \2", value)
    for long, short in [
        ("street", "st"), ("road", "rd"), ("avenue", "ave"),
        ("terrace", "tce"), ("parade", "pde"), ("place", "pl"),
        ("crescent", "cres"), ("drive", "dr"), ("lane", "ln"),
        ("highway", "hwy"), ("boulevard", "blvd")
    ]:
        value = re.sub(r"\b" + long + r"\b", short, value)
    value = re.sub(r"[,;]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    unit = street_no = None
    # Prefix formats: 2/15 Street, Unit 2 15 Street, Flat 2/15 Street.
    m = re.match(r"^(?:unit\s+)?([a-z]?\d+[a-z]?)\s*/\s*(\d+[a-z]?)\b\s*(.*)$", value)
    if m:
        unit, street_no, rest = m.groups()
        value = f"unit {unit} {street_no} {rest}"
    else:
        m = re.match(r"^unit\s+([a-z]?\d+[a-z]?)\s+(\d+[a-z]?)\b\s*(.*)$", value)
        if m:
            unit, street_no, rest = m.groups()
            value = f"unit {unit} {street_no} {rest}"
        else:
            # Unit may be a suffix, e.g. "15 Example Street, Unit 2".
            m = re.search(r"\bunit\s+([a-z]?\d+[a-z]?)\s*$", value)
            if m:
                unit = m.group(1)
                value = value[:m.start()].strip()
            m = re.match(r"^(\d+[a-z]?)\b\s*(.*)$", value)
            if m:
                street_no, rest = m.groups()
                value = f"{street_no} {rest}"

    if unit is None:
        m = re.match(r"^unit\s+([a-z]?\d+[a-z]?)\s+(\d+[a-z]?)\b", value)
        if m:
            unit, street_no = m.groups()
    if street_no is None:
        m = re.match(r"^(\d+[a-z]?)\b", value)
        street_no = m.group(1) if m else None

    # Canonicalise suffix unit notation to the same form as prefix notation.
    if unit and not value.startswith("unit "):
        m = re.match(r"^(\\d+[a-z]?)\\b\\s*(.*)$", value)
        if m:
            street_no, rest = m.groups()
            value = f"unit {unit} {street_no} {rest}"

    normal = re.sub(r"[^a-z0-9]+", " ", value)
    normal = re.sub(r"\s+", " ", normal).strip()
    return (unit.upper() if unit else None,
            street_no.upper() if street_no else None, normal)


def address_variants(address: str):
    """Return useful search strings without discarding unit information."""
    unit, street_no, _ = parse_address_parts(address)
    variants = [address]
    if unit and street_no:
        # Common LINZ / property-listing representations.
        tail = re.sub(r"^.*?\b" + re.escape(street_no) + r"\b", "", address, count=1, flags=re.I).strip(" ,")
        variants.extend([f"Unit {unit}, {street_no} {tail}", f"{unit}/{street_no} {tail}"])
    return list(dict.fromkeys(v.strip() for v in variants if v and v.strip()))


CHCH_URL_BASE = "https://www.trademe.co.nz/a/property/residential/sale/canterbury/christchurch-city"
DUNEDIN_URL_BASE = "https://www.trademe.co.nz/a/property/residential/sale/otago/dunedin"


def slugify(text: str) -> str:
    """'St Albans' / "st-albans" -> 'st-albans'."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def parse_listing_id(value):
    """Accepts '1234567890' or a pasted URL ending in the ID; returns int or None."""
    value = clean(value)
    if value is None:
        return None
    m = re.search(r"(\d{6,})\D*$", value)
    return int(m.group(1)) if m else None


def listing_url(suburb, listing_id, city):
    if not (suburb and listing_id):
        return None

    city_key = (city or "Christchurch").strip().casefold()
    if city_key == "christchurch":
        url_base = CHCH_URL_BASE
    elif city_key == "dunedin":
        url_base = DUNEDIN_URL_BASE
    else:
        return None

    return f"{url_base}/{slugify(suburb)}/listing/{listing_id}"


def search_address(address: str, suburb) -> str:
    """Append the suburb to the address text if it isn't already there (helps the LINZ match)."""
    if suburb and slugify(suburb) not in slugify(address):
        return f"{address}, {suburb}"
    return address


def find_match(cur, address: str):
    variants = address_variants(address)
    variants = (variants + [address] * 3)[:3]
    cur.execute(CANDIDATES_SQL, (*variants, *variants))
    candidates = cur.fetchall()
    want_unit, want_street_no, want_norm = parse_address_parts(address)

    from difflib import SequenceMatcher
    ranked = []
    for address_id, full_address, score in candidates:
        got_unit, got_street_no, got_norm = parse_address_parts(full_address)
        # Do not allow a fuzzy match to change the street number or unit.
        if want_street_no and got_street_no != want_street_no:
            continue
        if want_unit is not None and got_unit != want_unit:
            continue
        # A unit-less input is ambiguous in a multi-unit building, so don't
        # arbitrarily attach it to one of the units.
        if want_unit is None and got_unit is not None:
            continue
        canonical_score = SequenceMatcher(None, want_norm, got_norm).ratio()
        combined_score = max(float(score), canonical_score)
        ranked.append((address_id, full_address, combined_score))

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[2], reverse=True)
    best = ranked[0]
    # Avoid silently choosing between near-identical candidate records.
    if len(ranked) > 1 and ranked[1][0] != best[0] and ranked[1][2] >= best[2] - 0.025:
        return None
    return best if best[2] >= 0.42 else None


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python load_shortlist.py shortlist.csv")
    password = load_database_password()

    with open(sys.argv[1], newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"Read {len(rows)} rows from {sys.argv[1]}. Connecting to the database...", flush=True)
    loaded, unmatched, weak = 0, [], []
    with psycopg.connect(
        host="localhost",
        port=5432,
        dbname="housing",
        user="postgres",
        password=password,
    ) as conn:
        with conn.cursor() as cur:
            print("Preparing tables and trigram index (first run can take a minute)...")
            cur.execute(SCHEMA_SQL)

            for row in rows:
                address = clean(row.get("address"))
                if not address:
                    continue
                suburb = clean(row.get("suburb"))
                city = clean(row.get("city")) or "Christchurch"
                listing_id = parse_listing_id(row.get("listing_id"))
                if clean(row.get("listing_id")) and listing_id is None:
                    print(f"  note: couldn't read a listing ID from '{row.get('listing_id')}' ({address})")
                if listing_id and not suburb:
                    print(f"  note: no suburb for {address}, so no Trade Me URL was built")
                elif listing_id and city.casefold() not in ("christchurch", "dunedin"):
                    print(f"  note: unsupported city '{city}' for {address}, so no Trade Me URL was built")
                match = find_match(cur, search_address(address, suburb))
                if not match:
                    unmatched.append(address)
                    continue
                address_id, full_address, score = match
                if score < 0.5:
                    weak.append((address, full_address, round(score, 2)))
                cur.execute(UPSERT_SQL, {
                    "address_id": address_id,
                    "address_input": address,
                    "score": score,
                    "url": listing_url(suburb, listing_id, city),
                    "listing_id": listing_id,
                    "suburb": suburb,
                    "city": city,
                    "price_display": clean(row.get("price_display")),
                    "asking_price": to_int(row.get("asking_price")),
                    "bedrooms": to_int(row.get("bedrooms")),
                    "bathrooms": to_int(row.get("bathrooms")),
                    "floor_area_m2": to_int(row.get("floor_area_m2")),
                    "land_area_m2": to_int(row.get("land_area_m2")),
                    "notes": clean(row.get("notes")),
                })
                loaded += 1
        conn.commit()

    print(f"\nLoaded {loaded} of {len(rows)} rows.")
    if weak:
        print("\nLoaded, but check these matches (low similarity):")
        for given, matched, score in weak:
            print(f"  '{given}'  ->  '{matched}'  (score {score})")
    if unmatched:
        print("\nNo match found (check spelling, suburb or unit/flat numbers):")
        for a in unmatched:
            print(f"  {a}")


if __name__ == "__main__":
    main()