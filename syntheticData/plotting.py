"""
Plotting synthetic data to diagnose volatility signal

Author: @tylerrleee
Date: 05/31/2026
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import matplotlib.dates as mdates

FIGURE_DIR = os.path.join(os.path.dirname(__file__), "figures")
VALIDATION_DIR = os.path.join(FIGURE_DIR, "validation")


# HELPERS
def _run_lengths(mask):
    """Lengths of consecutive True (missing) runs in a 1D boolean array."""
    runs, current = [], 0
    for v in mask:
        if v:
            current += 1
        elif current:
            runs.append(current); current = 0
    if current:
        runs.append(current)
    return runs

def missing_matrix(df):
    """users x prompts boolean matrix, True = missing, from a cohort df."""
    wide = df.pivot(index="user_id", columns="prompt_idx", values="ema")
    return wide.isna().to_numpy()

# gap-length histogram 
def plot_gap_histogram(df, mean_gap_length, ax=None, figsize=(7, 4)):

    gaps = [g for row in missing_matrix(df) for g in _run_lengths(row)]
    if not gaps:
        print("no gaps to plot")
        return
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    maxlen = max(gaps)
    ax.hist(gaps,
            bins = np.arange(0.5, maxlen + 1.5, 1),
            density = True,
            alpha = 0.7,
            edgecolor = "white",
            label = "observed")

    # P(end gap)
    b = 1.0 / mean_gap_length
    k = np.arange(1, maxlen + 1)
    ax.plot(k, (1 - b) ** (k - 1) * b, "o-", color="crimson",
            label=f"geometric, mean {mean_gap_length}")
    ax.axvline(np.mean(gaps), color="black", ls="--",
               label=f"observed mean {np.mean(gaps):.4f}")

    ax.set_xlabel("gap length (consecutive missed prompts)")
    ax.set_ylabel("density"); ax.set_title("Missing-run length distribution")
    ax.legend()
    fig.savefig(os.path.join(FIGURE_DIR, "gap_histogram.png"), bbox_inches="tight")

# Per-user missing rate
def plot_missing_rate_histogram(df, resp_rate, ax=None, figsize=(7, 4)):

    # Helper
    def find_avg_missing(obs: np.array):
      return obs.isna().mean()

    # For each EMA, find average missing responses
    rates = df.groupby("user_id")["ema"].apply(find_avg_missing)

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    ax.hist(rates, bins=20, alpha=0.7, edgecolor="white")
    ax.axvline(1.0 - resp_rate, color="crimson", ls="--",
               label=f"target {1.0 - resp_rate:.2f}")
    ax.axvline(rates.mean(), color="black", ls=":",
               label=f"cohort mean {rates.mean():.3f}")

    ax.set_xlabel("fraction of prompts missing (per user)")
    ax.set_ylabel("number of users"); ax.set_title("Per-user missing rate")
    ax.legend()
    fig.savefig(os.path.join(FIGURE_DIR, "missing_rate_histogram.png"), bbox_inches="tight")

# Response rate: sticky vs. scatter
# how correlated are non-responses?

def plot_response_raster(df, resp_rate, seed=1, n_show=40, figsize=(12, 5)):

    """
    Compare response randomness to clustered responses

    """
    sticky = missing_matrix(df)
    n_show = min(n_show, sticky.shape[0])
    n_prompts = sticky.shape[1]
    missing_rate = 1.0 - resp_rate

    # MCAR baseline: each prompt independently missing, no memory
    rng = np.random.default_rng(seed)
    scatter = rng.random((n_show, n_prompts)) < missing_rate

    fig, axes = plt.subplots(1, 2, figsize=figsize, sharey=True)
    for ax, mat, title in [(axes[0], sticky[:n_show], "Sticky (Current Clustered)"),
                           (axes[1], scatter,         "Scatter (MCAR baseline)")]:
        ax.imshow(mat, aspect="auto", cmap="binary", interpolation="nearest")
        ax.set_title(f"{title}\nrealized missing {mat.mean():.2f}")
        ax.set_xlabel("prompt (time)")
    axes[0].set_ylabel("user")
    fig.suptitle("Response raster, black = missing")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "response_raster.png"), bbox_inches="tight")



def plot_config_recovery(df=None, csv_path=None, figsize=(13, 6)):
    """
    True vs. recovered AR(1) parameters from the data_generation_config table.

    Two panels -- sigma and rho -- each scattering the recovered value against
    the true value with a y = x identity line (points on the line = perfect
    recovery). Each point is one (sigma, rho) grid cell, coloured by the *other*
    parameter so attenuation patterns are visible (e.g. rho recovers poorly when
    sigma is small, because Likert rounding erases the fine autocorrelation).

    Reads figures/validation/data_generation_config.csv by default, or accepts
    the DataFrame directly (as built by mssd_validation.build_config_table).
    """
    if df is None:
        if csv_path is None:
            csv_path = os.path.join(VALIDATION_DIR, "data_generation_config.csv")
        df = pd.read_csv(csv_path)

    fig, (ax_s, ax_r) = plt.subplots(1, 2, figsize=figsize)

    # sigma panel: recovered vs true, coloured by true_rho
    sc = ax_s.scatter(df["true_sigma"], df["recovered_sigma"], c=df["true_rho"],
                      cmap="viridis", s=70, edgecolor="white", zorder=3)
    s_lo = min(df["true_sigma"].min(), df["recovered_sigma"].min())
    s_hi = max(df["true_sigma"].max(), df["recovered_sigma"].max())
    ax_s.plot([s_lo, s_hi], [s_lo, s_hi], "k--", alpha=0.6, label="y = x (perfect)")
    ax_s.set_xlabel(r"true $\sigma$")
    ax_s.set_ylabel(r"recovered $\hat{\sigma}$")
    ax_s.set_title(r"$\sigma$ recovery")
    ax_s.grid(True, linestyle="--", alpha=0.4)
    ax_s.legend(loc="best", fontsize=8)
    fig.colorbar(sc, ax=ax_s, label=r"true $\rho$")

    # rho panel: recovered vs true, coloured by true_sigma
    sc2 = ax_r.scatter(df["true_rho"], df["recovered_rho"], c=df["true_sigma"],
                       cmap="plasma", s=70, edgecolor="white", zorder=3)
    r_lo = min(df["true_rho"].min(), df["recovered_rho"].min())
    r_hi = max(df["true_rho"].max(), df["recovered_rho"].max())
    ax_r.plot([r_lo, r_hi], [r_lo, r_hi], "k--", alpha=0.6, label="y = x (perfect)")
    ax_r.set_xlabel(r"true $\rho$")
    ax_r.set_ylabel(r"recovered $\hat{\rho}$")
    ax_r.set_title(r"$\rho$ recovery")
    ax_r.grid(True, linestyle="--", alpha=0.4)
    ax_r.legend(loc="best", fontsize=8)
    fig.colorbar(sc2, ax=ax_r, label=r"true $\sigma$")

    fig.suptitle("Recovered vs. true AR(1) parameters (data_generation_config)")
    fig.tight_layout()
    os.makedirs(VALIDATION_DIR, exist_ok=True)
    fig.savefig(os.path.join(VALIDATION_DIR, "param_recovery.png"), bbox_inches="tight")


def plot_heart_rate(df, figsize=(15, 6)):
    """
    Plots heart rate over time for a given DataFrame.
    """
    fig, ax = plt.subplots(figsize=figsize)

    ax.plot(df['timestamp'], df['hr'], color='tab:blue', alpha=0.6, linewidth=1, label='Heart Rate')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    fig.autofmt_xdate()

    ax.set_title("Heart Rate Over Time")
    ax.set_xlabel("Date")
    ax.set_ylabel("BPM")
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend()
    fig.tight_layout()

    fig.savefig(os.path.join(FIGURE_DIR, "heart_rate_analysis.png"), bbox_inches="tight")


def plot_stress(df, figsize=(15, 6)):
    """
    Continuous all-day Garmin stress (0-100) for a single user, with HR overlaid
    on a second axis to show that stress tracks heart rate. Expects the HR
    DataFrame (columns: timestamp, hr, stress).
    """
    fig, ax_stress = plt.subplots(figsize=figsize)

    ax_stress.plot(df['timestamp'], df['stress'], color='tab:purple',
                   alpha=0.7, linewidth=1, label='Stress (0-100)')
    ax_stress.set_ylim(0, 100)
    ax_stress.set_ylabel("Stress score", color='tab:purple')
    ax_stress.tick_params(axis='y', labelcolor='tab:purple')
    ax_stress.set_xlabel("Time")

    ax_hr = ax_stress.twinx()
    ax_hr.plot(df['timestamp'], df['hr'], color='tab:red', alpha=0.4,
               linewidth=1, label='Heart Rate (bpm)')
    ax_hr.set_ylabel("BPM", color='tab:red')
    ax_hr.tick_params(axis='y', labelcolor='tab:red')

    src = df['source'].iloc[0] if 'source' in df.columns and len(df) else 'Garmin'
    ax_stress.set_title(f"Continuous all-day stress, from HR ({src})")
    ax_stress.grid(True, linestyle='--', alpha=0.5)
    ax_stress.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "stress_analysis.png"), bbox_inches="tight")


def plot_continuous_hrv(df, figsize=(15, 6), hrv_window=30):
    """
    Continuous all-day HRV (RMSSD, ms) for a single user, derived beat-by-beat,
    with HR overlaid on a second axis to show HRV falling as HR rises. Expects
    the HR DataFrame (columns: timestamp, hr, rmssd_ms).

    The raw per-minute RMSSD is noisy, so we also draw a smoothed HRV trend (a
    `hrv_window`-minute rolling mean) -- the value a Garmin device surfaces as
    "HRV" -- as a bold line on top of the faint raw trace.
    """
    df = df.sort_values('timestamp')
    hrv_trend = df['rmssd_ms'].rolling(window=hrv_window, min_periods=1).mean()

    fig, ax_hrv = plt.subplots(figsize=figsize)

    # raw per-minute RMSSD, kept faint
    ax_hrv.plot(df['timestamp'], df['rmssd_ms'], color='tab:green',
                alpha=0.25, linewidth=0.8, label='RMSSD (per-minute)')
    # smoothed HRV trend (what Garmin reports as HRV)
    ax_hrv.plot(df['timestamp'], hrv_trend, color='tab:green',
                alpha=0.95, linewidth=2.2,
                label=f'HRV ({hrv_window}-min rolling mean)')
    ax_hrv.set_ylabel("HRV / RMSSD (ms)", color='tab:green')
    ax_hrv.tick_params(axis='y', labelcolor='tab:green')
    ax_hrv.set_xlabel("Time")

    ax_hr = ax_hrv.twinx()
    ax_hr.plot(df['timestamp'], df['hr'], color='tab:red', alpha=0.4,
               linewidth=1, label='Heart Rate (bpm)')
    ax_hr.set_ylabel("BPM", color='tab:red')
    ax_hr.tick_params(axis='y', labelcolor='tab:red')

    src = df['source'].iloc[0] if 'source' in df.columns and len(df) else 'Garmin'
    ax_hrv.set_title(f"Continuous all-day HRV (RMSSD), from beat-by-beat RR ({src})")
    ax_hrv.grid(True, linestyle='--', alpha=0.5)
    ax_hrv.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

    # combined legend across both axes (raw RMSSD, HRV trend, HR)
    lines = ax_hrv.get_lines() + ax_hr.get_lines()
    ax_hrv.legend(lines, [ln.get_label() for ln in lines], loc='upper right', fontsize=8)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "continuous_hrv_analysis.png"), bbox_inches="tight")


def plot_hrv_status(df, figsize=(13, 6)):
    """
    Nightly Garmin HRV Status for a single user: overnight RMSSD per night, the
    trailing 7-day baseline line + shaded balanced band, and status-coloured
    markers. Expects the nightly DataFrame from `generate_HRV` (columns:
    night, overnight_avg_rmssd, baseline_7d, hrv_status, source).
    """
    df = df.sort_values("night")
    nights = df["night"]
    rmssd = df["overnight_avg_rmssd"].to_numpy(dtype=float)
    base = df["baseline_7d"].to_numpy(dtype=float)
    band = np.maximum(0.5 * np.nanstd(rmssd), 5.0)  # display band ~ matches model

    status_color = {
        "Balanced": "tab:green",
        "Low": "tab:red",
        "Unbalanced": "tab:orange",
        "No Status": "tab:gray",
    }

    fig, ax = plt.subplots(figsize=figsize)

    # overnight RMSSD trace
    ax.plot(nights, rmssd, color="tab:blue", alpha=0.5, linewidth=1.2,
            zorder=1, label="overnight RMSSD")

    # 7-day baseline + balanced band
    ax.plot(nights, base, color="black", linewidth=1.5, linestyle="--",
            zorder=2, label="7-day baseline")
    ax.fill_between(nights, base - band, base + band, color="tab:green",
                    alpha=0.12, zorder=0, label="balanced band")

    # status-coloured points
    for status, color in status_color.items():
        m = df["hrv_status"] == status
        if m.any():
            ax.scatter(nights[m], rmssd[m], color=color, s=55, zorder=3,
                       edgecolor="white", label=status)

    src = df["source"].iloc[0] if "source" in df.columns and len(df) else "Garmin"
    ax.set_title(f"Overnight HRV Status ({src})")
    ax.set_xlabel("Night")
    ax.set_ylabel("RMSSD (ms)")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="best", fontsize=8, ncol=2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "hrv_status_analysis.png"), bbox_inches="tight")