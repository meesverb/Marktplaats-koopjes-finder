#!/bin/sh
# Rebuilds reference_bike_catalog.csv from scratch. Run it from an empty scratch
# directory, not from the repository: it writes a page cache and the
# intermediate JSON files to the working directory. Takes hours — every request
# is spaced out (wb.py), and the Wayback Machine is slow and sometimes offline;
# a rerun resumes from the cache.
set -e
T="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$T"
python3 "$T/prepare_lists.py"
python3 "$T/giant_harvest.py"
python3 "$T/giant_extra.py"
python3 "$T/current_nl.py"
python3 "$T/trek_specs.py"
python3 "$T/trek_api.py"
python3 "$T/trek_wayback.py"
python3 "$T/sensa_harvest.py"
python3 "$T/bikezona_harvest.py"
python3 "$T/build_catalog.py" "$T/../reference_bike_catalog.csv"
