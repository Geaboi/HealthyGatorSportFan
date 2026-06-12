# syntheticData

*Tyler Le*

*Date: 06/02/2026*

[GITHUB](<https://github.com/Geaboi/HealthyGatorSportFan/tree/synthetic-data>)

Synthetic data generation for EMA (Ecological Momentary Assessment) and heart rate (HR) signals, used to validate MSSD (Mean of Squared Successive Differences) as a measure of temporal instability.

# Scope

We are focusing on qualitative (EMA) and quantitative simulation (HR + HRV + stress), so other quantitative values (steps, sleep, etc,..) are omitted for the purpose of simulation concept review and simplicity of debugging.

The wearable profile simulates the **Garmin** line (Venu 3 / Vivoactive 5/6) rather than Fitbit: heart-rate samples carry a `source` flag and an HRV value, and a Garmin-style 0–100 stress score is derived from continuous HR.

## Quick start

```bash
pip install -r requirements.txt

python main.py             # generate a cohort + diagnostic plots -> figures/
python mssd_validation.py  # MSSD construct-validity check  -> figures/validation/
python db_seed.py --help   # push a cohort into the Django DB (see Phase 3 below)
```

## Files

### `main.py`

Generates a cohort of 100 synthetic users over 7 days, producing both EMA and heart rate DataFrames (DF). Runs all diagnostic plots and saves them to `figures/`.

In scope: Parameters can be tweaked to simulate different cohorts, producing a distinct DF. 

Out of scope: DF does not save. 

### `synthetic_generator.py`

Core data generation module. Contains two generators:

- **EMA Generator** : Produces per-user EMA time series with known latent volatility using an AR(1) process (see below about why AR(1)). 
    - Each user gets randomly drawn parameters (`mu`, `sigma`, `rho`) that serve as ground truth for validating MSSD. EMA values are mapped to a 1-5 Likert scale (for now). Missingness or no response is injected via randomness (`_clustered_missing_mask`) that produces realistic clustered gaps rather than random dropout.
    - No response are clustered, instead of purely random. Although this missingness can be controlled, it helps simualate the prolonged responsiveness of certain individuals
        - e.g. phone is on DND, has an exam, watching the Knicks winning NBA Finals, etc,..
    
  - `generate_user_ids()` : Creates unique UUIDs for each user.
  - `generate_user()` : Generates one user's EMA series with known latent parameters.
  - `generate_cohort()` : Generates the full cohort DataFrame.

  - `generate_user()` now accepts optional `mu` / `sigma` / `rho` so a caller can pin the latent volatility to a *known* value. This is how `mssd_validation.py` builds Stable vs. Volatile sub-cohorts.

- **Heart Rate + Stress Generator** : Produces minute-level HR data per user (random Gaussian noise + activity bouts), plus a continuous all-day stress score. Resting HR is estimated from [60,100] for young adults.
  - `_generate_heart_rate()` : Generates one user's minute-level HR series, plus a `stress` and a Garmin `source` column.
  - `_generate_stress()` : Garmin's all-day **stress** (0–100) is genuinely continuous, so it's derived directly from HR: HR is normalised over a resting→exertion band and mapped to 0–100 (higher HR → higher stress). Activity bouts already in the HR trace therefore produce stress spikes.
  - `generate_HR()` : Generates HR + stress for the full cohort, assigning each user a Garmin device model (`GARMIN_DEVICES`).

- **HRV Status Generator (overnight)** : Garmin's **HRV Status is measured during sleep**, one value per night, *not* continuously coupled to HR. Each night gets an overnight average RMSSD, a trailing **7-day baseline**, and a status label (`Balanced` / `Unbalanced` / `Low`, or `No Status` during the warm-up window).
  - `_generate_overnight_hrv()` : per-user baseline RMSSD (young-adult range) with night-to-night AR(1) drift, nudged lower after high-load days.
  - `daily_load_from_hr()` : per-user/day load proxy (that day's mean stress, z-scored) used to couple a hard day --> lower overnight HRV.
  - `generate_HRV()` : nightly cohort DataFrame: `user_id, night, overnight_avg_rmssd, baseline_7d, hrv_status, source`.
  - Note: HRV and stress are **analysis-only** -- they are generated for figures/inspection but **not** persisted (the live Django schema has no columns for them; see `db_seed.py`).
    - Parameters are tweakable in `synthetic_generator.py`

$$
  RMSSD = \sqrt{\frac{1}{N-1}\sum_{i=1}^{N-1}(RR_{i+1} - RR_i)^2} 
$$
$$
  BPM = \frac{60,000}{RR interval (ms)}
$$
  

  Constraint: RR measures the exact time (in milliseconds) between individual heartbeats, in which requires beat-to-beat HR recording assumption. 

  Hence, given that HR is measured in minute0level, we guess a baseline HR , where $baseline ~ Uniform(35,75)$ with:

$$
  z_d = \phi * z_{d-1} + e_d
$$


  where coefficient $\phi$ is how we want to scale different demographics. 

### `mssd_validation.py`

Construct-validity harness for MSSD (Phase 1). Generates sub-cohorts with **known** latent parameters across a (sigma, rho) grid, computes the empirical MSSD on the realised 1–5 Likert series (honouring the missingness mask — successive differences spanning a missed prompt are dropped), and regresses empirical MSSD against the ground-truth expected MSSD `2σ²(1-ρ)`. A strong positive correlation (Pearson r ≈ 0.94) is the construct-validity defence: MSSD recovers latent volatility despite Likert rounding and missingness. Writes plots to `figures/validation/`.

```bash
python mssd_validation.py
```

### `db_seed.py`

ETL / seed script (Phase 3). Uses **SQLAlchemy reflection** to bulk-insert a synthetic cohort into the **Django database** (the app owns the schema; run its migrations first), targeting the **original** Django schema — no schema changes are required. Inserts respect foreign-key order:

```
app_user → app_wearabledevice → app_heartratesample   (bpm + HR zone)
app_user → app_ema                                    (mood = 1–5 Likert)
```

HRV/stress are generated for analysis (see the generator + figures) but are **not** pushed, since the live schema has no columns for them. Missed EMA prompts are simply **omitted** (there's no `status` column). Each row also lands in `csv_export/<table>.csv` for inspection (`--no-csv` to skip).

Synthetic users are tagged with an `@synthetic.gatorfan` email so `--reset` wipes a previous seed without touching real accounts. Target DB comes from `DATABASE_URL` (e.g. Heroku Postgres) or defaults to the local sqlite DB the Django migrations create.

```bash
# from HealthyGatorSportsFanDjango/, create the tables once:
#   DATABASE_URL=sqlite:///$(pwd)/synthetic_seed.sqlite3 python manage.py migrate

# then seed 100 mock users (downsamples HR to every 5th minute by default):
python db_seed.py --users 100 --days 7 --reset
DATABASE_URL=postgres://... python db_seed.py --users 100 --reset   # any Django DB
```

### First-Order Autoregressive Model

*['Autoregressions', Economics-With-R](<https://www.econometrics-with-r.org/14.3-autoregressions.html>)*

An autoregressive model relates a time series variable to its past values.

In our case, the goal is to 'model' a person's fluctuating psychological state, which is **dependent on the previous state**.

Formula:

$$
z_t = \rho * z_{t-1} + e_t
$$

$z_t$: User's state

$z_{t-1}$: User's state at the previous time step

$e_t$ : Random noise that influence user's state (e.g. FSU just scored, just took some cognac, hitting a PR)

e_t ~ $Normal(0, \sigma_{e^2})$ : random noise is Normally distributed.
  - On average, most noise are close to the mean, 0, but sometimes, depending $\sigma_{e^2}$, it can be influential

### `plotting.py`

Diagnostic visualizations for validating the synthetic data. All figures are saved to `figures/`.

- `plot_gap_histogram()` — Distribution of missing-run lengths vs. the expected geometric distribution.
- `plot_missing_rate_histogram()` — Per-user missing rate distribution compared to the target response rate.
- `plot_response_raster()` — Side-by-side raster comparing clustered (sticky) missingness against an MCAR baseline.
- `plot_heart_rate()` — Heart rate over time for a single user.

### `notebook/Tien_Le_MSSD_v1_0.ipynb`

Research notebook documenting the MSSD methodology

### `figures/`

Output directory for saved plots:

- `gap_histogram.png` - Missing-run length distribution.

![1](./figures/gap_histogram.png)

- `missing_rate_histogram.png` - Per-user missing rate histogram.

![2](./figures/missing_rate_histogram.png)

- `heart_rate_analysis.png` - Sample heart rate time series.

![3](./figures/heart_rate_analysis.png)

- `response_raster.png` - Sticky vs. scatter missingness raster.

![4](./figures/response_raster.png)

- `stress_analysis.png` - Continuous all-day Garmin stress (from HR) for one user.

![5](./figures/stress_analysis.png)

- `hrv_status_analysis.png` - Overnight HRV Status for one user: nightly RMSSD, 7-day baseline band, and status-coloured points.

![5b](./figures/hrv_status_analysis.png)

### `figures/validation/`

MSSD construct-validity output (`mssd_validation.py`):

- `mssd_recovery.png` - Empirical MSSD vs. ground-truth expected MSSD, with OLS fit and Pearson/Spearman correlations.

![6](./figures/validation/mssd_recovery.png)

- `mssd_group_separation.png` - Empirical MSSD distributions for Stable / Mid / Volatile cohorts.

![7](./figures/validation/mssd_group_separation.png)

