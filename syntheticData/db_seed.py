"""
ETL / seed: push synthetic cohorts into the Django database via SQLAlchemy.

Synthetic users are tagged with an "@synthetic.gatorfan" email so `--reset`
can wipe a previous seed cleanly without touching real accounts.

Usage (from syntheticData/):

    # local sqlite the Django migrations created
    python db_seed.py --users 100 --days 7 --reset

    # any Django DB 
    DATABASE_URL=postgres://... python db_seed.py --users 100 --reset

Author: @tylerrleee
Date: 06/11/2026
"""

import os
import argparse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import sqlalchemy as sa

from synthetic_generator import generate_user_ids, generate_cohort, generate_HR

SYNTHETIC_DOMAIN = "synthetic.gatorfan"

# Default to the local sqlite DB the Django migrations populate. The Heroku /

_DEFAULT_SQLITE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..",
                 "HealthyGatorSportsFanDjango", "synthetic_seed.sqlite3")
)

# CSV dump of the exact row payloads, for eyeballing what gets pushed.
_DEFAULT_CSV_DIR = os.path.join(os.path.dirname(__file__), "csv_export")

# RANDOM SAMPLE NAMES
FIRST_NAMES = ["Jalen", "Riley", "Jordan", "Casey", "Morgan", "Taylor", "Quinn",
               "Reese", "Skyler", "Devon", "Harper", "Emerson", "Rowan", "Sage",
               "Parker", "Hayden", "Elliot", "Finley", "Marley", "Tatum"]
LAST_NAMES = ["Brunson", "Garcia", "Smith", "Johnson", "Williams", "Brown",
              "Jones", "Davis", "Martinez", "Lopez", "Wilson", "Anderson",
              "Thomas", "Lee", "Patel", "Kim", "Walker", "Hall", "Allen", "Young"]
GENDERS = ["male", "female", "other"]


def _chunked(rows, size = 5000):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _hr_zone(bpm, max_hr=195):
    """Map a bpm to a HeartRateSample.ZONE_CHOICES bucket (% of max HR)."""
    frac = bpm / max_hr
    if frac < 0.50:
        return "out_of_range"
    if frac < 0.70:
        return "fat_burn"
    if frac < 0.85:
        return "cardio"
    return "peak"


def _write_csvs(csv_dir, table_rows):
    """Dump each list of insert-row dicts to <csv_dir>/<table>.csv."""
    
    os.makedirs(csv_dir, exist_ok=True)
    written = {}
    for name, rows in table_rows.items():
        path = os.path.join(csv_dir, f"{name}.csv")
        pd.DataFrame(rows).to_csv(path, index=False)
        written[name] = path
    return written


def _reflect(engine):
    """
    Checking model/table exists 
    """

    md = sa.MetaData()
    names = ["app_user", "app_wearabledevice",
             "app_heartratesample", "app_ema"]
    md.reflect(bind=engine, only=names)
    missing = [n for n in names if n not in md.tables]
    if missing:
        raise RuntimeError(
            f"missing tables {missing}; run Django migrations against this DB first"
        )
    return {n: md.tables[n] for n in names}


def reset_synthetic(conn, t):
    """Delete a previous synthetic seed (children first, then parents)."""

    users       = t["app_user"]
    devices     = t["app_wearabledevice"]
    syn_users   = sa.select(users.c.user_id).where(
        users.c.email.like(f"%@{SYNTHETIC_DOMAIN}"))
    syn_devices = sa.select(devices.c.device_id).where(
        devices.c.user_id.in_(syn_users))

    for tbl, col, subq in [
        (t["app_heartratesample"], "device_id", syn_devices),
        (t["app_ema"], "user_id", syn_users),
        (t["app_wearabledevice"], "user_id", syn_users),
    ]:
        conn.execute(sa.delete(tbl).where(tbl.c[col].in_(subq)))
    conn.execute(sa.delete(users).where(users.c.email.like(f"%@{SYNTHETIC_DOMAIN}")))


def _normalize_url(url):
    """
    Heroku exports DATABASE_URL as 'postgres://...', but SQLAlchemy's
    create_engine only accepts the 'postgresql://' scheme (the 'postgres'
    alias was removed in SQLAlchemy 1.4+). Rewrite it so a Heroku URL can be
    pasted as-is.
    """
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def seed(database_url, users, days, ema_per_day, resp_rate, hr_every, seed_val,
         do_reset, csv_dir=None):
    
    """
    Generate random users information w/ distinct uuid + HR + stress EMA responses
    
    """
    engine = sa.create_engine(_normalize_url(database_url))
    t = _reflect(engine)
    rng = np.random.default_rng(seed_val)

    # Shared UUIDs so EMA and wearable data join on the same person.
    user_ids = generate_user_ids(users)
    ema_df = generate_cohort(users=users, days=days, ema_per_day=ema_per_day,
                             seed=seed_val, resp_rate=resp_rate, user_ids=user_ids)
    hr_df = generate_HR(users=users, days=days, seed=seed_val, user_ids=user_ids)

    if hr_every > 1:                       # thin the minute-level series
        hr_df = hr_df[hr_df["minute"] % hr_every == 0].copy()

    with engine.begin() as conn:
        if do_reset:
            reset_synthetic(conn, t)

        # 1. app_user 
        today = datetime(2026, 6, 11)
        user_rows = []
        for uid in user_ids:
            age_days = int(rng.integers(18 * 365, 24 * 365))
            user_rows.append({
                "email": f"{uid}@{SYNTHETIC_DOMAIN}",
                "first_name": FIRST_NAMES[rng.integers(0, len(FIRST_NAMES))],
                "last_name": LAST_NAMES[rng.integers(0, len(LAST_NAMES))],
                "birthdate": (today - timedelta(days=age_days)).date(),
                "gender": GENDERS[rng.integers(0, len(GENDERS))],
                "height_feet": str(int(rng.integers(4, 7))),
                "height_inches": str(int(rng.integers(0, 12))),
                "goal_weight": round(float(rng.uniform(120, 200)), 1),
                "goal_to_lose_weight": bool(rng.random() < 0.6),
                "goal_to_feel_better": bool(rng.random() < 0.6),
                "password": None,          # mock accounts: no usable password
            })
        conn.execute(sa.insert(t["app_user"]), user_rows)

        # map uuid -> user_id via the embedded email
        uid_map = {
            email.split("@")[0]: pk
            for pk, email in conn.execute(
                sa.select(t["app_user"].c.user_id, t["app_user"].c.email)
                .where(t["app_user"].c.email.like(f"%@{SYNTHETIC_DOMAIN}"))
            )
        }

        # 2. app_wearabledevice (one Garmin per user) 
        # each user's device model = the source flag on their HR rows
        device_model = (hr_df.groupby("user_id")["source"].first().to_dict())
        device_rows = []
        for uid in user_ids:
            device_rows.append({
                "user_id": uid_map[uid],
                "fitbit_device_id": f"garmin-{uid[:8]}",
                "device_type": "smartwatch",
                "device_name": device_model.get(uid, "Garmin Venu 3"),
                "last_synced_at": today,
                "is_active": True,
                "created_at": today,
            })
        conn.execute(sa.insert(t["app_wearabledevice"]), device_rows)

        dev_map = {
            uid: pk for pk, uid in conn.execute(
                sa.select(t["app_wearabledevice"].c.device_id,
                          t["app_wearabledevice"].c.user_id)
                .where(t["app_wearabledevice"].c.user_id.in_(uid_map.values()))
            )
        }

        # 3. app_heartratesample (bpm + HR zone only)
        hr_df = hr_df.copy()
        hr_df["device_id"] = hr_df["user_id"].map(
            lambda u: dev_map[uid_map[u]])
        ts = hr_df["timestamp"].dt.to_pydatetime()

        hr_rows = []
        for i, (dev, bpm) in enumerate(zip(
                hr_df["device_id"].to_numpy(), hr_df["hr"].to_numpy())):
            bpm_i = int(round(bpm))
            hr_rows.append({
                "device_id": int(dev), "timestamp": ts[i],
                "bpm": bpm_i, "zone": _hr_zone(bpm_i),
            })
        for batch in _chunked(hr_rows):
            conn.execute(sa.insert(t["app_heartratesample"]), batch)

        # 4. app_ema -- only answered prompts (no status column to flag misses)
        ema_rows = []
        e_ts = ema_df["timestamp"].dt.to_pydatetime()
        ema_vals = ema_df["ema"].to_numpy()
        ema_uids = ema_df["user_id"].to_numpy()
        for i in range(len(ema_df)):
            if np.isnan(ema_vals[i]):       # missed prompt -> omit
                continue
            ema_rows.append({
                "user_id": uid_map[ema_uids[i]],
                "timestamp": e_ts[i],
                "mood": int(ema_vals[i]),
                "energy": None, "stress": None,
                "physical_activity": None, "weight_lbs": None, "notes": None,
            })
        for batch in _chunked(ema_rows):
            conn.execute(sa.insert(t["app_ema"]), batch)

    # Mirror the exact pushed payloads to CSV for inspection.
    if csv_dir:
        written = _write_csvs(csv_dir, {
            "app_user": user_rows,
            "app_wearabledevice": device_rows,
            "app_heartratesample": hr_rows,
            "app_ema": ema_rows,
        })
        print(f"csv dump  : {csv_dir}")
        for path in written.values():
            print(f"  {os.path.basename(path)}")

    return {
        "users": len(user_rows),
        "devices": len(device_rows),
        "heart_rate_samples": len(hr_rows),
        "ema_answered": len(ema_rows),
        "ema_missed_omitted": int(np.isnan(ema_vals).sum()),
    }

USERS = 100
DAYS  = 7
EMA_PER_DAY = 5
RESPONSE_RATE = 0.8
KEEP_HR_PER_HOUR = 5
RNG_SEED = 42

def main():
    ap = argparse.ArgumentParser(description="Seed synthetic data into the Django DB.")
    ap.add_argument("--users", type = int, default = USERS)
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--ema-per-day", type=int, default=EMA_PER_DAY)
    ap.add_argument("--resp-rate", type=float, default=RESPONSE_RATE)
    ap.add_argument("--hr-every", type=int, default=KEEP_HR_PER_HOUR,
                    help="keep every Nth minute of HR (1 = full minute-level)")
    ap.add_argument("--seed", type=int, default=RNG_SEED)
    ap.add_argument("--reset", action="store_true",
                    help="delete a previous synthetic seed before inserting")
    ap.add_argument("--database-url", default=None,
                    help="overrides $DATABASE_URL; defaults to the local sqlite DB")
    ap.add_argument("--csv-dir", default=_DEFAULT_CSV_DIR,
                    help="directory to dump per-table CSVs of the pushed rows")
    ap.add_argument("--no-csv", action="store_true",
                    help="skip the CSV dump")
    args = ap.parse_args()

    database_url = (args.database_url or os.getenv("DATABASE_URL")
                    or f"sqlite:///{_DEFAULT_SQLITE}")
    print(f"target DB : {database_url}")

    counts = seed(database_url, args.users, args.days, args.ema_per_day,
                  args.resp_rate, args.hr_every, args.seed, args.reset,
                  csv_dir=None if args.no_csv else args.csv_dir)

    print("seeded:")
    for k, v in counts.items():
        print(f"  {k:20s}: {v}")
    print("DONE")


if __name__ == "__main__":
    main()
