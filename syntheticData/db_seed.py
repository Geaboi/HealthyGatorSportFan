"""
ETL / seed: push synthetic cohorts into the Django database via SQLAlchemy.

The Django app owns the schema (run its migrations first); this script only
*writes* rows, using SQLAlchemy reflection so it never re-declares the tables.
Data is inserted in foreign-key order:

    app_user -> app_wearabledevice -> app_heartratesample
                                   -> app_stresssample
    app_user -> app_ema

Synthetic users are tagged with an "@synthetic.gatorfan" email so `--reset`
can wipe a previous seed cleanly without touching real accounts.

Usage (from syntheticData/):

    # local sqlite the Django migrations created
    python db_seed.py --users 100 --days 7 --reset

    # any Django DB (e.g. Heroku Postgres)
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
# Postgres path is selected by exporting DATABASE_URL.
_DEFAULT_SQLITE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..",
                 "HealthyGatorSportsFanDjango", "synthetic_seed.sqlite3")
)

# RANDOM SAMPLE NAMES
FIRST_NAMES = ["Jalen", "Riley", "Jordan", "Casey", "Morgan", "Taylor", "Quinn",
               "Reese", "Skyler", "Devon", "Harper", "Emerson", "Rowan", "Sage",
               "Parker", "Hayden", "Elliot", "Finley", "Marley", "Tatum"]
LAST_NAMES = ["Brunson", "Garcia", "Smith", "Johnson", "Williams", "Brown",
              "Jones", "Davis", "Martinez", "Lopez", "Wilson", "Anderson",
              "Thomas", "Lee", "Patel", "Kim", "Walker", "Hall", "Allen", "Young"]
GENDERS = ["male", "female", "other"]


def _chunked(rows, size=5000):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _reflect(engine):
    md = sa.MetaData()
    names = ["app_user", "app_wearabledevice",
             "app_heartratesample", "app_stresssample", "app_ema"]
    md.reflect(bind=engine, only=names)
    missing = [n for n in names if n not in md.tables]
    if missing:
        raise RuntimeError(
            f"missing tables {missing}; run Django migrations against this DB first"
        )
    return {n: md.tables[n] for n in names}


def reset_synthetic(conn, t):
    """Delete a previous synthetic seed (children first, then parents)."""
    users = t["app_user"]
    devices = t["app_wearabledevice"]
    syn_users = sa.select(users.c.user_id).where(
        users.c.email.like(f"%@{SYNTHETIC_DOMAIN}"))
    syn_devices = sa.select(devices.c.device_id).where(
        devices.c.user_id.in_(syn_users))

    for tbl, col, subq in [
        (t["app_heartratesample"], "device_id", syn_devices),
        (t["app_stresssample"], "device_id", syn_devices),
        (t["app_ema"], "user_id", syn_users),
        (t["app_wearabledevice"], "user_id", syn_users),
    ]:
        conn.execute(sa.delete(tbl).where(tbl.c[col].in_(subq)))
    conn.execute(sa.delete(users).where(users.c.email.like(f"%@{SYNTHETIC_DOMAIN}")))


def seed(database_url, users, days, ema_per_day, resp_rate, hr_every, seed_val,
         do_reset):
    engine = sa.create_engine(database_url)
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

        # ---- 1. app_user -------------------------------------------------
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

        # ---- 2. app_wearabledevice (one Garmin per user) ----------------
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
        # user_id -> uuid, to translate device owner back to a uuid key
        pk_to_uuid = {pk: uid for uid, pk in uid_map.items()}

        # ---- 3. app_heartratesample + app_stresssample ------------------
        hr_df = hr_df.copy()
        hr_df["device_id"] = hr_df["user_id"].map(
            lambda u: dev_map[uid_map[u]])
        ts = hr_df["timestamp"].dt.to_pydatetime()

        hr_rows, stress_rows = [], []
        for i, (dev, bpm, rmssd, stress, src) in enumerate(zip(
                hr_df["device_id"].to_numpy(), hr_df["hr"].to_numpy(),
                hr_df["hrv_rmssd"].to_numpy(), hr_df["stress"].to_numpy(),
                hr_df["source"].to_numpy())):
            when = ts[i]
            hr_rows.append({
                "device_id": int(dev), "timestamp": when,
                "bpm": int(round(bpm)), "zone": "",
                "hrv_rmssd": round(float(rmssd), 2), "source": str(src),
            })
            stress_rows.append({
                "device_id": int(dev), "timestamp": when,
                "stress_score": int(round(stress)), "source": str(src),
            })
        for batch in _chunked(hr_rows):
            conn.execute(sa.insert(t["app_heartratesample"]), batch)
        for batch in _chunked(stress_rows):
            conn.execute(sa.insert(t["app_stresssample"]), batch)

        # ---- 4. app_ema (missed prompts written explicitly) -------------
        ema_rows = []
        e_ts = ema_df["timestamp"].dt.to_pydatetime()
        ema_vals = ema_df["ema"].to_numpy()
        ema_uids = ema_df["user_id"].to_numpy()
        for i in range(len(ema_df)):
            answered = not np.isnan(ema_vals[i])
            ema_rows.append({
                "user_id": uid_map[ema_uids[i]],
                "timestamp": e_ts[i],
                "status": "answered" if answered else "missed",
                "mood": int(ema_vals[i]) if answered else None,
                "energy": None, "stress": None,
                "physical_activity": None, "weight_lbs": None, "notes": None,
            })
        for batch in _chunked(ema_rows):
            conn.execute(sa.insert(t["app_ema"]), batch)

    return {
        "users": len(user_rows),
        "devices": len(device_rows),
        "heart_rate_samples": len(hr_rows),
        "stress_samples": len(stress_rows),
        "ema": len(ema_rows),
        "ema_missed": int(np.isnan(ema_vals).sum()),
    }


def main():
    ap = argparse.ArgumentParser(description="Seed synthetic data into the Django DB.")
    ap.add_argument("--users", type=int, default=100)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--ema-per-day", type=int, default=5)
    ap.add_argument("--resp-rate", type=float, default=0.80)
    ap.add_argument("--hr-every", type=int, default=5,
                    help="keep every Nth minute of HR/stress (1 = full minute-level)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true",
                    help="delete a previous synthetic seed before inserting")
    ap.add_argument("--database-url", default=None,
                    help="overrides $DATABASE_URL; defaults to the local sqlite DB")
    args = ap.parse_args()

    database_url = (args.database_url or os.getenv("DATABASE_URL")
                    or f"sqlite:///{_DEFAULT_SQLITE}")
    print(f"target DB : {database_url}")

    counts = seed(database_url, args.users, args.days, args.ema_per_day,
                  args.resp_rate, args.hr_every, args.seed, args.reset)

    print("seeded:")
    for k, v in counts.items():
        print(f"  {k:20s}: {v}")
    print("DONE")


if __name__ == "__main__":
    main()
