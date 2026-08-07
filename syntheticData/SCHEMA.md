# Synthetic Data — I/O Schema

Reference for the inputs and outputs of the `syntheticData/` generator. All
generators live in `synthetic_generator.py`; `main.py` is the diagnostic entry
point, `db_seed.py` pushes the data into the Django DB, and `mssd_validation.py`
is the MSSD construct-validity harness.

All series start at **2026-06-01 00:00**. EMA and HR rows are at **1-minute**
frequency; HRV is **one row per night**. 

---

## 1. Inputs

### Top-level knobs (`main.py:22-26`)

| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `USERS` | int | 100 | number of synthetic users |
| `DAYS` | int | 21 | days generated per user |
| `EMA_PER_DAY` | int | 5 | EMA prompts per day |
| `RESP_RATE` | float | 0.80 | fraction of prompts answered (1 − missing rate); range [0, 1] |
| `SEED` | int | 42 | RNG seed (one `np.random.default_rng(seed)` per generator) |

### EMA per-user latent parameters (`generate_user`, `synthetic_generator.py:22-30`)

Drawn at random per user unless pinned by the caller (the validation harness pins them).

| Name | Type | Default / draw | Meaning |
|------|------|----------------|---------|
| `mu` | float | `U(2.0, 4.0)` | mean Likert level |
| `sigma` | float | `U(0.3, 1.5)` | latent volatility (AR(1) stationary SD); 0 = always at mean |
| `rho` | float | `U(0.1, 0.8)` | AR(1) autocorrelation between successive points |
| `mean_gap_length` | int | 3 | average run length of consecutive missed prompts (≥ 1) |

Latent process (AR(1)): `z[0] ~ N(0, σ)`, `z[t] = ρ·z[t-1] + N(0, σ·√(1−ρ²))`,
then `ema = clip(round(μ + z), 1, 5)`. Missingness is a clustered two-state
Markov mask (`_clustered_missing_mask`) whose long-run missing rate is `1 − resp_rate`.

### Heart-rate parameters (`_generate_heart_rate`, `synthetic_generator.py:350-360`)

| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `resting_hr` | float | draw `U(60, 100)` | per-user baseline bpm; also anchors HRV amplitude |
| `circadian_amp` | float | 6.0 | daily rhythm amplitude (bpm); lowest ~4am, highest ~4pm |
| `noise_std` | float | 2.0 | minute-to-minute white-noise SD (bpm) |
| `bouts_per_day` | (int, int) | (0, 3) | activity bouts per day, inclusive range |
| `bout_minutes` | (int, int) | (20, 60) | per-bout duration range (minutes) |
| `bout_intensity` | (float, float) | (15, 40) | per-bout HR elevation range (bpm) |
| `source` | str | `"Garmin Venu 3"` | device model; cohort draws from `GARMIN_DEVICES` (Venu 3 / Vivoactive 5 / Vivoactive 6) |

`hr = clip(resting_hr + circadian + noise + activity, 40, 200)`.

### Continuous HRV / stress (derived from the HR trace)

`_generate_stress` (`:184-187`): `stress_window = (55.0, 130.0)` HR band mapped onto
0–100, `stress_noise_std = 4.0`.

`_generate_continuous_hrv` (`:213-218`): beat-by-beat RR simulation → per-minute
RMSSD. `base_rr_sd = 30.0` (RR SD in ms at rest), `rr_sd_clip = (3.0, 150.0)`,
`rmssd_clip = (3.0, 200.0)`.

### Overnight HRV (`generate_HRV` / `_generate_overnight_hrv`, `:315-323, 470-475`)

| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `baseline_range` | (float, float) | (35.0, 75.0) | per-user overnight RMSSD baseline draw (ms) |
| `phi` | float | 0.5 | night-to-night AR(1) drift coefficient |
| `night_sd` | float | 6.0 | night-to-night variability (ms) |
| `load_coef` | float | 5.0 | coupling: subtract `load_coef · load_z` (hard day → lower recovery) |
| `extra_noise_std` | float | 2.0 | additive overnight RMSSD noise (ms) |
| `rmssd_clip` | (float, float) | (15.0, 120.0) | physiological clamp on overnight RMSSD (ms) |

---

## 2. Outputs (DataFrames)

### EMA frame — `generate_cohort` (`:133`) → one row per prompt per user

| Column | Type | Meaning |
|--------|------|---------|
| `user_id` | str (UUID) | user identifier |
| `timestamp` | Timestamp | prompt time (1-min freq from 2026-06-01) |
| `prompt_idx` | int | 0 … `days*ema_per_day - 1` |
| `day` | int | day index (`prompt_idx // ema_per_day`) |
| `ema` | float | 1–5 Likert response, or `NaN` if missed |
| `true_sigma` | float | ground-truth latent σ |
| `true_rho` | float | ground-truth latent ρ |
| `true_expected_mssd` | float | `2·σ²·(1−ρ)` — expected MSSD |

Rows: `USERS × DAYS × EMA_PER_DAY` (NaN = missed prompt).

### HR frame — `generate_HR` (`:424`) → one row per minute per user

| Column | Type | Meaning |
|--------|------|---------|
| `user_id` | str (UUID) | user identifier |
| `timestamp` | Timestamp | minute time |
| `minute` | int | 0 … `days*1440 - 1` |
| `day` | int | day index |
| `hr` | float | heart rate (bpm), clipped [40, 200] |
| `stress` | float | continuous Garmin-style stress (0–100) |
| `rmssd_ms` | float | continuous all-day RMSSD (ms), per minute |
| `hr_from_rr` | float | bpm recovered from simulated RR (`60000/RR`); sanity trace ≈ `hr` |
| `source` | str | Garmin device model |

Rows: `USERS × DAYS × 1440`.

### Daily-load frame — `daily_load_from_hr` (`:451`) → one row per user per day

| Column | Type | Meaning |
|--------|------|---------|
| `user_id` | str (UUID) | user identifier |
| `day` | int | day index |
| `load_z` | float | day's mean `stress`, z-scored within each user |

Feeds `generate_HRV` to couple overnight recovery to daytime load. (Returns
`user_id, day, load_z` only — the intermediate `load` mean is dropped.)

### Overnight-HRV frame — `generate_HRV` (`:470`) → one row per user per night

| Column | Type | Meaning |
|--------|------|---------|
| `user_id` | str (UUID) | user identifier |
| `night` | Timestamp | night date |
| `overnight_avg_rmssd` | float | overnight RMSSD (ms), rounded 0.1 |
| `baseline_7d` | float | trailing 7-night mean RMSSD (shifted so a night excludes itself), rounded 0.1 |
| `hrv_status` | str | `Balanced` / `Low` / `Unbalanced` / `No Status` |
| `source` | str | Garmin device model |

HRV-status rule (`_hrv_status`): band = `max(0.5·rolling_std, 5.0)`; `No Status`
until ≥ 3 nights of history; else `Low` if `rmssd < baseline − band`,
`Unbalanced` if `> baseline + band`, otherwise `Balanced`.

---

## 3. Validation / recovery outputs (`mssd_validation.py`)

`build_validation_cohort` (`:116`) pins each `(σ, ρ)` grid cell
(σ ∈ {0.3, 0.6, 0.9, 1.2, 1.5} × ρ ∈ {0.2, 0.5, 0.8}, 12 users/cell), then
recovers parameters per user via `recover_ar1_params` (σ̂ = sample SD,
ρ̂ = lag-1 autocorrelation over consecutive answered pairs).

### Per-user frame (in memory) → `figures/validation/param_recovery_per_user.csv`

Exported columns (true/recovered adjacent):
`user_id, group, n_answered, true_sigma, recovered_sigma, true_rho,
recovered_rho, true_expected_mssd, empirical_mssd`.
(`recovered_sigma`/`recovered_rho` are the per-user `sigma_hat`/`rho_hat`.)
`group` ∈ {Stable, Mid, Volatile} from the expected-MSSD label.

### Per-cell frame — `build_config_table` (`:167`) → `figures/validation/data_generation_config.csv`

`true_sigma, true_rho, recovered_sigma, recovered_rho, sigma_recovery_pct,
rho_recovery_pct, n_users` — recovered σ̂/ρ̂ averaged across each cell's users;
`*_recovery_pct = 100 · recovered / true` (100% = perfect recovery).

Figures (all under `figures/validation/`): `mssd_recovery.png`,
`mssd_group_separation.png`, `param_recovery.png` (recovered-vs-true scatter).

---

## 4. Database seed outputs (`db_seed.py`)

`python db_seed.py --users N --days D [--reset]` generates EMA + HR and inserts
into the Django DB (defaults to the local `synthetic_seed.sqlite3`). Defaults:
`USERS=100, DAYS=7, EMA_PER_DAY=5, RESPONSE_RATE=0.8, KEEP_HR_PER_HOUR=5`
(`--hr-every` keeps every Nth minute), `RNG_SEED=42`. Synthetic accounts use
`<uuid>@synthetic.gatorfan` emails so `--reset` wipes only seeded rows. Pushed
payloads are mirrored to `csv_export/<table>.csv` unless `--no-csv`.

| Table | Key fields |
|-------|-----------|
| `app_user` | `email` (`<uuid>@synthetic.gatorfan`), `first_name`, `last_name`, `birthdate` (18–24 yo), `gender`, `height_feet`, `height_inches`, `goal_weight`, `goal_to_lose_weight`, `goal_to_feel_better`, `password=None` |
| `app_wearabledevice` | `user_id` (FK), `fitbit_device_id` (`garmin-<uuid[:8]>`), `device_type="smartwatch"`, `device_name` (Garmin model = HR `source`), `last_synced_at`, `is_active`, `created_at` |
| `app_heartratesample` | `device_id` (FK), `timestamp`, `bpm` (int), `zone` (`out_of_range`/`fat_burn`/`cardio`/`peak` by % of max HR via `_hr_zone`) |
| `app_ema` | `user_id` (FK), `timestamp`, `mood` (1–5, answered prompts only — missed omitted), `energy`/`stress`/`physical_activity`/`weight_lbs`/`notes` = None |

---

## 5. Pipeline flow (`main.py`)

```
generate_user_ids(USERS)                         # shared UUIDs
  → generate_cohort(...)        → ema_df
  → generate_HR(...)            → hr_df          (hr + stress + rmssd_ms)
  → daily_load_from_hr(hr_df)   → load_df        (user_id, day, load_z)
  → generate_HRV(..., load_df)  → hrv_df         (overnight RMSSD + status)
  → plot_* diagnostics → figures/
```

Reproducibility: identical `seed` + shared `user_ids` make EMA / HR / HRV align
per user. MSSD validation is a separate entry point (`python mssd_validation.py`).
