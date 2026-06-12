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