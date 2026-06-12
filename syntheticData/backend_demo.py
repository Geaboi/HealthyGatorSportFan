"""
Post a reduced synthetic cohort to the deployed Django backend.

This targets the currently deployed 0024 schema through public API endpoints:
    POST /user/
    POST /telemetry/ingest/

It intentionally drops synthetic fields that require migration 0025, including
stress samples, HRV RMSSD, source, and EMA status.
"""

import argparse
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

from synthetic_generator import generate_HR, generate_cohort, generate_user_ids


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body) if response_body else {}
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        raise RuntimeError(f"POST {url} failed with {exc.code}: {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"POST {url} failed: {exc}") from exc


def iso_timestamp(value):
    timestamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.isoformat().replace("+00:00", "Z")


def zone_for_bpm(bpm):
    if bpm >= 150:
        return "peak"
    if bpm >= 120:
        return "cardio"
    if bpm >= 90:
        return "fat_burn"
    return "out_of_range"


def build_user_payload(uid, index, rng, run_label):
    return {
        "email": f"{uid}.{run_label}@synthetic.gatorfan",
        "password": "SyntheticPass123",
        "first_name": f"Synthetic{index + 1}",
        "last_name": "Gator",
        "birthdate": "2000-01-01",
        "gender": rng.choice(["male", "female", "other"]).item(),
        "height_feet": str(int(rng.integers(5, 7))),
        "height_inches": str(int(rng.integers(0, 12))),
        "goal_weight": str(round(float(rng.uniform(130, 200)), 1)),
        "goal_to_lose_weight": bool(rng.random() < 0.6),
        "goal_to_feel_better": bool(rng.random() < 0.6),
    }


def build_telemetry_payload(app_user_id, uid, hr_df, ema_df):
    heart_rate_samples = []
    for row in hr_df.itertuples(index=False):
        bpm = int(round(row.hr))
        heart_rate_samples.append(
            {
                "timestamp": iso_timestamp(row.timestamp),
                "bpm": bpm,
                "zone": zone_for_bpm(bpm),
            }
        )

    emas = []
    for row in ema_df.itertuples(index=False):
        if np.isnan(row.ema):
            emas.append(
                {
                    "mood": None,
                    "energy": None,
                    "stress": None,
                    "physical_activity": None,
                    "weight_lbs": None,
                    "notes": "Synthetic missed EMA prompt.",
                }
            )
        else:
            emas.append(
                {
                    "mood": int(row.ema),
                    "energy": None,
                    "stress": None,
                    "physical_activity": None,
                    "weight_lbs": None,
                    "notes": "",
                }
            )

    return {
        "user_id": app_user_id,
        "wearable_device": {
            "fitbit_device_id": f"synthetic-{uid[:8]}",
            "device_type": "smartwatch",
            "device_name": "Garmin Venu 3",
            "is_active": True,
        },
        "heart_rate_samples": heart_rate_samples,
        "emas": emas,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Post reduced synthetic telemetry to a deployed HealthyGator backend."
    )
    parser.add_argument(
        "--api",
        default="https://healthygatorsportfan-ab9271b02569.herokuapp.com",
        help="Base URL for the deployed backend.",
    )
    parser.add_argument("--users", type=int, default=3)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--ema-per-day", type=int, default=5)
    parser.add_argument("--resp-rate", type=float, default=0.80)
    parser.add_argument(
        "--hr-every",
        type=int,
        default=30,
        help="Keep every Nth minute of HR data before posting.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--run-label",
        default=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        help="Unique label embedded in synthetic emails to avoid duplicate users.",
    )
    args = parser.parse_args()

    base_url = args.api.rstrip("/")
    rng = np.random.default_rng(args.seed)
    user_ids = generate_user_ids(args.users)
    ema_df = generate_cohort(
        users=args.users,
        days=args.days,
        ema_per_day=args.ema_per_day,
        seed=args.seed,
        resp_rate=args.resp_rate,
        user_ids=user_ids,
    )
    hr_df = generate_HR(users=args.users, days=args.days, seed=args.seed, user_ids=user_ids)
    if args.hr_every > 1:
        hr_df = hr_df[hr_df["minute"] % args.hr_every == 0].copy()

    totals = {
        "users": 0,
        "heart_rate_samples": 0,
        "emas": 0,
    }

    for index, uid in enumerate(user_ids):
        user_payload = build_user_payload(uid, index, rng, args.run_label)
        user_response = post_json(f"{base_url}/user/", user_payload)
        app_user_id = user_response["user_id"]
        totals["users"] += 1

        user_hr = hr_df[hr_df["user_id"] == uid]
        user_ema = ema_df[ema_df["user_id"] == uid]
        telemetry_payload = build_telemetry_payload(app_user_id, uid, user_hr, user_ema)
        telemetry_response = post_json(f"{base_url}/telemetry/ingest/", telemetry_payload)
        totals["heart_rate_samples"] += telemetry_response["counts"]["heart_rate_samples"]
        totals["emas"] += telemetry_response["counts"]["emas"]

        print(
            f"posted user {index + 1}/{args.users}: "
            f"user_id={app_user_id}, "
            f"hr={telemetry_response['counts']['heart_rate_samples']}, "
            f"ema={telemetry_response['counts']['emas']}"
        )

    print("DONE")
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
