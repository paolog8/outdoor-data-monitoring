#!/usr/bin/env python3
"""Compare what the dev database holds for some exports with what production holds.

For each export folder the time window is taken from the raw files (local time -> UTC).
Both databases are asked for the same aggregates over that window and the results are
printed side by side. Production is only read, in a read-only session, through ssh.

    scripts/compare_with_production.py data_20240222 all_20230109 data_20260908:+2 ...

A suffix like ":+2" asks production for the window shifted by that many hours. Use it for
exports that production stored with local time labelled as UTC (summer +2, winter +1);
dev holds them correctly converted.

Dev connection: PG* variables (defaults: the dev stack on localhost:5440).
Windows are the first and last raw timestamp of the export's MPP files, so they only
contain that export's rows as long as neighbouring exports do not overlap it.
"""
import datetime
import glob
import os
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg2

ROOT = Path(__file__).resolve().parent.parent / "data" / "mppt_temp_irr"
LOCAL = ZoneInfo("Europe/Berlin")
UTC = datetime.timezone.utc


def raw_window(folder: str):
    base = ROOT / folder if folder.startswith("all_") else ROOT / folder / "data"
    lo = hi = None
    for f in glob.glob(str(base / "output_board*_channel*.txt")):
        with open(f, "rb") as fh:
            lines = fh.read().splitlines()
        if not lines:
            continue
        a = lines[0].split(b"\t")[0].decode()
        b = lines[-1].split(b"\t")[0].decode()
        lo = a if lo is None or a < lo else lo
        hi = b if hi is None or b > hi else hi
    to_utc = lambda s: datetime.datetime.fromisoformat(s).replace(tzinfo=LOCAL).astimezone(UTC)
    return to_utc(lo), to_utc(hi)


def queries(lo, hi):
    w = f"timestamp >= '{lo.isoformat()}' AND timestamp <= '{hi.isoformat()}'"
    # sensor serials are trimmed so that the old import's leading space does not hide a match
    return [
        ("mpp rows / min / max / sum(power)",
         f"SELECT count(*), min(timestamp), max(timestamp), round(sum(power)::numeric, 6) FROM mpp_measurement WHERE {w}"),
        ("temperature rows / min / max",
         f"SELECT count(*), min(timestamp), max(timestamp) FROM temperature_measurement WHERE {w}"),
        ("temperature sensors in window",
         f"SELECT count(DISTINCT btrim(t.serial_number)) FROM temperature_measurement m "
         f"JOIN temperature_sensor t ON t.id = m.temperature_sensor_id WHERE m.{w}"),
        ("irradiance rows / min / max",
         f"SELECT count(*), min(timestamp), max(timestamp) FROM irradiance_measurement WHERE {w}"),
    ]


def run_dev(sql):
    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"), port=os.environ.get("PGPORT", "5440"),
        dbname=os.environ.get("PGDATABASE", "outdoor_dev"), user=os.environ.get("PGUSER", "dev"),
        password=os.environ.get("PGPASSWORD", "dev"))
    with conn, conn.cursor() as cur:
        cur.execute(sql)
        return tuple(str(v) for v in cur.fetchone())


def run_prod(sql):
    remote = ("docker exec -i -e PGOPTIONS='-c default_transaction_read_only=on' postgres sh -c "
              "'psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -X -At -F \"|\"'")
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", "outdoor-wsl", remote], input=sql + ";\n",
                         capture_output=True, text=True, check=True).stdout.strip()
    return tuple(out.split("|"))


def norm(t):  # same instant, same format on both sides
    return tuple(
        (x.replace("+00:00", "").replace("+00", "").replace("T", " ") if x not in ("None", "") else "-")
        for x in t
    )


def main(args):
    rc = 0
    for arg in args:
        folder, _, shift = arg.partition(":")
        lo, hi = raw_window(folder)
        plo, phi = (lo + datetime.timedelta(hours=int(shift)), hi + datetime.timedelta(hours=int(shift))) if shift else (lo, hi)
        note = f"   (production window shifted {shift}h)" if shift else ""
        print(f"\n== {folder}   window {lo:%Y-%m-%d %H:%M:%S} .. {hi:%Y-%m-%d %H:%M:%S} UTC{note}")
        for (label, sql), (_, psql) in zip(queries(lo, hi), queries(plo, phi)):
            d, p = norm(run_dev(sql)), norm(run_prod(psql))
            if shift:  # production's timestamps are shifted by design: compare counts and sums only
                d, p = (tuple(x for x in t if not re.match(r"\d{4}-\d{2}-\d{2} ", x)) for t in (d, p))
            same = d == p
            rc |= not same
            print(f"  {'same' if same else 'DIFF'}  {label}")
            if not same:
                print(f"        dev : {d}\n        prod: {p}")
    return rc


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
