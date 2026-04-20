""""
generate_visits.py

Generates a realistic Visit log for the year 2025 and writes to visits.csv.

Realism features:
  - Visits are generated chronologically per facility per day
  - Average gap ~30 sec during peak hours (9-11am, 4-7pm), ~4 min off-peak
  - Facility 101 receives ~70% of visits; 102, 103, 104 each ~10%
  - OccupancyAtTime rises during peaks and falls off-peak
  - All timestamps fall within each facility's actual operating hours

Expected input files (same folder as this script):
    member.csv          — column: AnonID
    facility.csv        — column: FacilityID
    facility_hours.csv  — columns: FacilityID, DayOfWeek, OpenTime, CloseTime

Usage (terminal):  python generate_visits.py <N>
Usage (PyCharm):   Just run — it will prompt you for N.
"""

import sys
import csv
import random
from datetime import datetime, timedelta, date, time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MEMBERS_FILE        = "member.csv"
_FACILITIES_FILE     = "facility.csv"
_FACILITY_HOURS_FILE = "facilityHours.csv"
_OUTPUT_FILE         = "visits.csv"

_YEAR = 2025

# Facility visit weight distribution
# 70% to FAC101, ~10% each to FAC102, FAC103, FAC104
# Keys are matched against FacilityID values loaded from facility.csv
_FACILITY_WEIGHTS = {
    "FAC101": 0.70,
    "FAC102": 0.10,
    "FAC103": 0.10,
    "FAC104": 0.10,
}

# Peak hour windows (inclusive, 24h)
_PEAK_WINDOWS = [
    (time(9, 0), time(11, 0)),
    (time(16, 0), time(19, 0)),
]

# Average gap in seconds between arrivals
_GAP_PEAK_AVG    = 30    # ~30 seconds during peak
_GAP_OFFPEAK_AVG = 240   # ~4 minutes off-peak

# Gap randomness: actual gap = gaussian(avg, avg * 0.5), clamped to [5s, avg*3]
_GAP_STD_FACTOR  = 0.5

# TypeOfAccess codes
_ACCESS_TYPE_CODES = ["ENTRY", "EXIT", "REENT"]

# DayOfWeek codes (Mon=0 ... Sun=6)
_DAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# Occupancy bands — (min%, max%) of MaxOccupancy per period
_OCC_PEAK_RANGE    = (0.50, 0.95)  # 50–95% of max during peak
_OCC_OFFPEAK_RANGE = (0.05, 0.40)  # 5–40% of max off-peak


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_anon_ids(filepath=_MEMBERS_FILE):
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            ids = [row["AnonID"] for row in csv.DictReader(f)]
        if not ids:
            print(f"Error: No AnonID values found in '{filepath}'."); sys.exit(1)
        print(f"Loaded {len(ids)} AnonID(s) from '{filepath}'.")
        return ids
    except FileNotFoundError:
        print(f"Error: '{filepath}' not found."); sys.exit(1)
    except KeyError:
        print(f"Error: '{filepath}' has no 'AnonID' column."); sys.exit(1)


def load_facilities(filepath=_FACILITIES_FILE):
    """
    Returns a dict of {FacilityID: MaxOccupancy} if MaxOccupancy column exists,
    otherwise {FacilityID: 200} as a default.
    """
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            print(f"Error: No rows found in '{filepath}'."); sys.exit(1)
        facilities = {}
        for row in rows:
            fid = row["FacilityID"].strip()
            max_occ = int(row["MaxOccupancy"]) if "MaxOccupancy" in row else 200
            facilities[fid] = max_occ
        print(f"Loaded {len(facilities)} facility record(s) from '{filepath}'.")
        return facilities
    except FileNotFoundError:
        print(f"Error: '{filepath}' not found."); sys.exit(1)
    except KeyError:
        print(f"Error: '{filepath}' has no 'FacilityID' column."); sys.exit(1)


def _parse_time(time_str):
    time_str = time_str.strip()
    for fmt in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: '{time_str}'")


def load_facility_hours(filepath=_FACILITY_HOURS_FILE):
    hours = {}
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fid      = row["FacilityID"].strip()
                day_raw  = row["DayOfWeek"].strip().upper()[:3]
                open_t   = _parse_time(row["OpenTime"])
                close_t  = _parse_time(row["CloseTime"])
                hours[(fid, day_raw)] = (open_t, close_t)
        if not hours:
            print(f"Error: No hours found in '{filepath}'."); sys.exit(1)
        print(f"Loaded {len(hours)} facility-hour entries from '{filepath}'.")
        return hours
    except FileNotFoundError:
        print(f"Error: '{filepath}' not found."); sys.exit(1)
    except KeyError as e:
        print(f"Error: '{filepath}' is missing column {e}."); sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_peak(t):
    """Return True if time t falls within any peak window."""
    for start, end in _PEAK_WINDOWS:
        if start <= t <= end:
            return True
    return False


def _next_gap_seconds(t):
    """Return a randomised gap in seconds based on whether t is peak or not."""
    avg = _GAP_PEAK_AVG if _is_peak(t) else _GAP_OFFPEAK_AVG
    std = avg * _GAP_STD_FACTOR
    gap = random.gauss(avg, std)
    return max(5, min(gap, avg * 3))  # clamp between 5s and 3x avg


def _occupancy(t, max_occ):
    """Return a realistic occupancy value based on time of day."""
    low, high = _OCC_PEAK_RANGE if _is_peak(t) else _OCC_OFFPEAK_RANGE
    return int(random.uniform(low, high) * max_occ)


def _weighted_facility(facility_ids, weights):
    """
    Pick a facility_id using the configured weights.
    Any facility not in _FACILITY_WEIGHTS gets an equal share of leftover weight.
    """
    known_weight  = sum(weights.get(fid, 0) for fid in facility_ids)
    unknown_ids   = [fid for fid in facility_ids if fid not in weights]
    leftover      = max(0.0, 1.0 - known_weight)
    per_unknown   = (leftover / len(unknown_ids)) if unknown_ids else 0.0

    pool    = []
    w_list  = []
    for fid in facility_ids:
        pool.append(fid)
        w_list.append(weights.get(fid, per_unknown))

    return random.choices(pool, weights=w_list, k=1)[0]


def _generate_visit_id(index):
    return f"V{str(index).zfill(8)}"


def _all_dates_in_year(year):
    start = date(year, 1, 1)
    return [start + timedelta(days=i) for i in range(365 if year % 4 != 0 else 366)]


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------

def generate_visits(n, anon_ids, facilities, facility_hours):
    """
    Generate N visit records chronologically.

    Strategy:
      - Iterate over every date in 2025
      - Walk through each day advancing by a realistic random gap each step
      - At each arrival, independently pick a weighted random facility
        and look up its hours to verify it is open at that time
      - Emit a visit record for each valid arrival until N records are reached
    """
    facility_ids = list(facilities.keys())
    all_dates    = _all_dates_in_year(_YEAR)
    records      = []
    visit_index  = 1

    # Shuffle dates so records spread evenly across the year
    date_pool = all_dates.copy()
    random.shuffle(date_pool)
    date_idx  = 0

    # Use the earliest open time across all facilities as the day start
    day_start = time(6, 0)
    day_end   = time(23, 0)

    while visit_index <= n:
        if date_idx >= len(date_pool):
            random.shuffle(date_pool)
            date_idx = 0

        visit_date = date_pool[date_idx]
        date_idx  += 1
        day_code   = _DAY_CODES[visit_date.weekday()]

        # Walk through the day from earliest open to latest close
        current_dt = datetime.combine(visit_date, day_start)
        end_dt     = datetime.combine(visit_date, day_end)

        while current_dt <= end_dt and visit_index <= n:
            t = current_dt.time()

            # Pick a weighted random facility for this individual visit
            facility_id = None
            max_occ     = 200

            candidate = _weighted_facility(facility_ids, _FACILITY_WEIGHTS)
            key = (candidate, day_code)
            if key in facility_hours:
                open_t, close_t = facility_hours[key]
                # Only record the visit if the facility is open right now
                if open_t <= t <= close_t:
                    facility_id = candidate
                    max_occ     = facilities[candidate]

            if facility_id is not None:
                record = {
                    "VisitID":         _generate_visit_id(visit_index),
                    "AnonID":          random.choice(anon_ids),
                    "FacilityID":      facility_id,
                    "VisitTimestamp":  current_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "DayOfWeek":       day_code,
                    "TimeOfDay":       t.strftime("%H:%M:%S"),
                    "MethodOfEntry":   random.choice([True, False]),
                    "TypeOfAccess":    random.choice(_ACCESS_TYPE_CODES),
                    "OccupancyAtTime": _occupancy(t, max_occ),
                }
                records.append(record)
                visit_index += 1

            # Advance to next arrival regardless of whether a record was emitted
            gap_seconds = _next_gap_seconds(t)
            current_dt += timedelta(seconds=gap_seconds)

    return records


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def write_csv(records, filepath=_OUTPUT_FILE):
    if not records:
        print("No records to write."); return
    fieldnames = list(records[0].keys())
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"Done! {len(records)} record(s) written to '{filepath}'.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) == 2:
        try:
            n = int(sys.argv[1])
            if n < 1: raise ValueError
        except ValueError:
            print("Error: N must be a positive integer."); sys.exit(1)
    else:
        try:
            n = int(input("Enter number of records to generate (N): "))
            if n < 1: raise ValueError
        except ValueError:
            print("Error: N must be a positive integer."); sys.exit(1)

    anon_ids       = load_anon_ids()
    facilities     = load_facilities()
    facility_hours = load_facility_hours()

    print(f"\nGenerating {n} visit records for {_YEAR}...")
    records = generate_visits(n, anon_ids, facilities, facility_hours)
    write_csv(records)


if __name__ == "__main__":
    main()