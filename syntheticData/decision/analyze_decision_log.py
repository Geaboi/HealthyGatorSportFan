"""
Analyze decision log outputs using mssd_validation and plotting utilities.

Reads decision_log.csv from outputs/, computes per-user MSSD metrics,
and generates diagnostic plots to figures/.

Usage (from syntheticData/decision/):
    python analyze_decision_log.py

Author: @tylerrleee
Date: 06/26/2026
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mssd_validation import empirical_mssd, recover_ar1_params, plot_config_recovery
from plotting import (
    plot_gap_histogram,
    plot_missing_rate_histogram,
    plot_response_raster,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
FIGURE_DIR = os.path.join(os.path.dirname(__file__), "figures")
os.makedirs(FIGURE_DIR, exist_ok=True)


def load_decision_log(csv_path=None):
    """Load decision log CSV."""
    if csv_path is None:
        csv_path = os.path.join(OUTPUT_DIR, "decision_log.csv")
    return pd.read_csv(csv_path)


def summarize_per_user(df):
    """
    Build per-user MSSD and parameter recovery metrics from decision log.

    Returns a DataFrame with one row per user, columns:
    - user_id
    - true_sigma, true_rho, true_expected_mssd
    - empirical_mssd, rho_hat, sigma_hat
    - n_ema_answered, n_ema_total
    - send_prompt_count (number of times a prompt was actually sent)
    """
    records = []

    for uid, group in df.groupby("user_id"):
        group = group.sort_values("prompt_idx")
        ema_vals = group["ema"].to_numpy()

        n_answered = int(np.isnan(ema_vals).sum() == 0) or int((~np.isnan(ema_vals)).sum())
        if n_answered < 2:
            continue

        empirical_mssd_val = empirical_mssd(ema_vals)
        rho_hat, sigma_hat = recover_ar1_params(ema_vals)

        true_sigma = group["true_sigma"].iloc[0]
        true_rho = group["true_rho"].iloc[0]
        true_expected = group["true_expected_mssd"].iloc[0]
        send_count = int(group["send_prompt"].sum())

        records.append({
            "user_id": uid,
            "true_sigma": true_sigma,
            "true_rho": true_rho,
            "true_expected_mssd": true_expected,
            "empirical_mssd": empirical_mssd_val,
            "rho_hat": rho_hat,
            "sigma_hat": sigma_hat,
            "n_ema_answered": int((~np.isnan(ema_vals)).sum()),
            "n_ema_total": len(ema_vals),
            "send_prompt_count": send_count,
        })

    return pd.DataFrame.from_records(records)


def plot_mssd_recovery(df, figsize=(10, 7)):
    """Scatter empirical MSSD vs. ground truth with OLS fit."""
    x = df["true_expected_mssd"].to_numpy()
    y = df["empirical_mssd"].to_numpy()

    valid = ~(np.isnan(x) | np.isnan(y))
    x = x[valid]
    y = y[valid]

    if len(x) < 2:
        print("Not enough valid MSSD values for recovery plot")
        return

    slope, intercept, r, p, se = stats.linregress(x, y)
    spearman = stats.spearmanr(x, y).correlation

    fig, ax = plt.subplots(figsize=figsize)
    ax.scatter(x, y, s=30, alpha=0.6, color="tab:blue", edgecolor="white")

    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, slope * xs + intercept, color="black", lw=2.5,
            label=f"OLS: y = {slope:.2f}x + {intercept:.3f}")

    ax.set_xlabel(r"Ground-truth expected MSSD: $2\sigma^2(1-\rho)$")
    ax.set_ylabel("Empirical MSSD (observed Likert, with missingness)")
    ax.set_title("MSSD Recovery: Decision Log Analysis")
    ax.annotate(f"Pearson r = {r:.3f}\nSpearman ρ = {spearman:.3f}\np = {p:.1e}",
                xy=(0.04, 0.82), xycoords="axes fraction",
                bbox=dict(boxstyle="round", fc="white", ec="0.7"))
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "mssd_recovery_decision_log.png"), bbox_inches="tight")
    print(f"  mssd_recovery_decision_log.png")

    return slope, r, spearman


def plot_param_recovery_scatter(df, figsize=(13, 6)):
    """True vs. recovered sigma and rho scatter plots."""
    fig, (ax_s, ax_r) = plt.subplots(1, 2, figsize=figsize)

    # sigma scatter
    valid = ~(np.isnan(df["true_sigma"]) | np.isnan(df["sigma_hat"]))
    sc = ax_s.scatter(df.loc[valid, "true_sigma"], df.loc[valid, "sigma_hat"],
                      c=df.loc[valid, "true_rho"],
                      cmap="viridis", s=50, edgecolor="white", alpha=0.7)
    s_lo = min(df["true_sigma"].min(), df["sigma_hat"].min())
    s_hi = max(df["true_sigma"].max(), df["sigma_hat"].max())
    ax_s.plot([s_lo, s_hi], [s_lo, s_hi], "k--", alpha=0.6, label="perfect recovery")
    ax_s.set_xlabel(r"True $\sigma$")
    ax_s.set_ylabel(r"Recovered $\hat{\sigma}$")
    ax_s.set_title(r"$\sigma$ Recovery")
    ax_s.grid(True, linestyle="--", alpha=0.3)
    ax_s.legend(fontsize=8)
    fig.colorbar(sc, ax=ax_s, label=r"true $\rho$")

    # rho scatter
    valid = ~(np.isnan(df["true_rho"]) | np.isnan(df["rho_hat"]))
    sc2 = ax_r.scatter(df.loc[valid, "true_rho"], df.loc[valid, "rho_hat"],
                       c=df.loc[valid, "true_sigma"],
                       cmap="plasma", s=50, edgecolor="white", alpha=0.7)
    r_lo = min(df["true_rho"].min(), df["rho_hat"].min())
    r_hi = max(df["true_rho"].max(), df["rho_hat"].max())
    ax_r.plot([r_lo, r_hi], [r_lo, r_hi], "k--", alpha=0.6, label="perfect recovery")
    ax_r.set_xlabel(r"True $\rho$")
    ax_r.set_ylabel(r"Recovered $\hat{\rho}$")
    ax_r.set_title(r"$\rho$ Recovery")
    ax_r.grid(True, linestyle="--", alpha=0.3)
    ax_r.legend(fontsize=8)
    fig.colorbar(sc2, ax=ax_r, label=r"true $\sigma$")

    fig.suptitle("Parameter Recovery (Decision Log Analysis)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "param_recovery_decision_log.png"), bbox_inches="tight")
    print(f"  param_recovery_decision_log.png")


def plot_prompt_triggers(df_log, figsize=(12, 6)):
    """
    Distribution of trigger decisions and prompt send frequency.
    """
    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=figsize)

    # Left: decision reason counts
    reasons = df_log["decision_reason"].value_counts()
    ax_l.barh(range(len(reasons)), reasons.values, color="steelblue", edgecolor="black")
    ax_l.set_yticks(range(len(reasons)))
    ax_l.set_yticklabels(reasons.index, fontsize=8)
    ax_l.set_xlabel("Count")
    ax_l.set_title("Decision Reasons Distribution")
    ax_l.grid(True, axis="x", linestyle="--", alpha=0.3)

    # Right: send_prompt rate
    send_rate = df_log["send_prompt"].mean() * 100
    no_send = 100 - send_rate
    ax_r.pie([send_rate, no_send], labels=[f"Sent ({send_rate:.1f}%)", f"Not sent ({no_send:.1f}%)"],
             colors=["#2ecc71", "#e74c3c"], autopct="%1.1f%%", startangle=90)
    ax_r.set_title("Overall Prompt Send Rate")

    fig.suptitle("JITAI Decision Outcomes")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "prompt_triggers.png"), bbox_inches="tight")
    print(f"  prompt_triggers.png")


def plot_mssd_over_time(df_log, user_sample_size=5, figsize=(14, 6)):
    """
    Plot observed MSSD accumulation over time for a sample of users.
    """
    users = df_log["user_id"].unique()
    sample_users = np.random.choice(users, size=min(user_sample_size, len(users)), replace=False)

    fig, ax = plt.subplots(figsize=figsize)

    for uid in sample_users:
        user_log = df_log[df_log["user_id"] == uid].sort_values("prompt_idx")
        ax.plot(user_log["prompt_idx"], user_log["observed_mssd"],
                alpha=0.6, linewidth=1.5, marker="o", markersize=3, label=uid[:8])

    ax.set_xlabel("Prompt Index")
    ax.set_ylabel("Observed MSSD")
    ax.set_title(f"MSSD Accumulation Over Time (sample of {len(sample_users)} users)")
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "mssd_over_time_sample.png"), bbox_inches="tight")
    print(f"  mssd_over_time_sample.png")


def plot_recovery_by_data_availability(df_users, figsize=(16, 10)):
    """
    Recovery curves for MSSD, rho, and sigma by response rate and answered observations.

    A 3x2 grid showing how recovery (Pearson r) varies with:
    - Rows: MSSD recovery, rho recovery, sigma recovery
    - Columns: response rate, number of answered observations

    This validates robustness of all three volatility parameters across data scarcity.
    """
    # Add response rate column
    df_users = df_users.copy()
    df_users["response_rate"] = df_users["n_ema_answered"] / df_users["n_ema_total"]

    fig, axes = plt.subplots(3, 2, figsize=figsize)

    # Helper function to compute recovery metrics by bins
    def compute_recovery_by_response_rate(df, x_col, y_col, bins=np.linspace(0, 1, 6)):
        """Compute correlation by response rate bins."""
        centers, r_values, counts = [], [], []
        for i in range(len(bins) - 1):
            mask = (df["response_rate"] >= bins[i]) & (df["response_rate"] < bins[i + 1])
            if mask.sum() < 3:
                continue
            subset = df[mask]
            x = subset[x_col].to_numpy()
            y = subset[y_col].to_numpy()
            valid = ~(np.isnan(x) | np.isnan(y))
            x, y = x[valid], y[valid]
            if len(x) >= 3:
                r = stats.pearsonr(x, y)[0]
                centers.append((bins[i] + bins[i + 1]) / 2)
                r_values.append(r)
                counts.append(mask.sum())
        return centers, r_values, counts

    def compute_recovery_by_answered_obs(df, x_col, y_col):
        """Compute correlation by answered observations bins."""
        ans_bins = np.linspace(df["n_ema_answered"].min() - 1, df["n_ema_answered"].max() + 1, 6)
        centers, r_values, counts, bin_ranges = [], [], [], []
        for i in range(len(ans_bins) - 1):
            mask = (df["n_ema_answered"] >= ans_bins[i]) & (df["n_ema_answered"] < ans_bins[i + 1])
            if mask.sum() < 3:
                continue
            subset = df[mask]
            x = subset[x_col].to_numpy()
            y = subset[y_col].to_numpy()
            valid = ~(np.isnan(x) | np.isnan(y))
            x, y = x[valid], y[valid]
            if len(x) >= 3:
                r = stats.pearsonr(x, y)[0]
                centers.append((ans_bins[i] + ans_bins[i + 1]) / 2)
                r_values.append(r)
                counts.append(mask.sum())
                bin_ranges.append((int(ans_bins[i]), int(ans_bins[i + 1])))
        return centers, r_values, counts, bin_ranges

    # Row 0: MSSD Recovery
    mssd_resp_x, mssd_resp_r, mssd_resp_n = compute_recovery_by_response_rate(
        df_users, "true_expected_mssd", "empirical_mssd")
    axes[0, 0].plot(mssd_resp_x, mssd_resp_r, "o-", linewidth=2.5, markersize=8,
                    color="tab:blue", markerfacecolor="white", markeredgewidth=2)
    axes[0, 0].axhline(0.7, color="green", linestyle="--", alpha=0.5)
    axes[0, 0].axhline(0.5, color="orange", linestyle="--", alpha=0.5)
    axes[0, 0].set_ylabel("Pearson r", fontsize=10)
    axes[0, 0].set_title("MSSD Recovery by Response Rate", fontsize=11, fontweight="bold")
    axes[0, 0].set_ylim([0, 1])
    axes[0, 0].grid(True, linestyle="--", alpha=0.3)
    for x, y, n in zip(mssd_resp_x, mssd_resp_r, mssd_resp_n):
        axes[0, 0].annotate(f"n={n}", xy=(x, y), xytext=(0, 5), textcoords="offset points",
                           ha="center", fontsize=7, alpha=0.7)

    mssd_ans_x, mssd_ans_r, mssd_ans_n, _ = compute_recovery_by_answered_obs(
        df_users, "true_expected_mssd", "empirical_mssd")
    axes[0, 1].plot(mssd_ans_x, mssd_ans_r, "s-", linewidth=2.5, markersize=8,
                    color="tab:red", markerfacecolor="white", markeredgewidth=2)
    axes[0, 1].axhline(0.7, color="green", linestyle="--", alpha=0.5)
    axes[0, 1].axhline(0.5, color="orange", linestyle="--", alpha=0.5)
    axes[0, 1].set_title("MSSD Recovery by Answered Observations", fontsize=11, fontweight="bold")
    axes[0, 1].set_ylim([0, 1])
    axes[0, 1].grid(True, linestyle="--", alpha=0.3)
    for x, y, n in zip(mssd_ans_x, mssd_ans_r, mssd_ans_n):
        axes[0, 1].annotate(f"n={n}", xy=(x, y), xytext=(0, 5), textcoords="offset points",
                           ha="center", fontsize=7, alpha=0.7)

    # Row 1: Rho Recovery
    rho_resp_x, rho_resp_r, rho_resp_n = compute_recovery_by_response_rate(
        df_users, "true_rho", "rho_hat")
    axes[1, 0].plot(rho_resp_x, rho_resp_r, "o-", linewidth=2.5, markersize=8,
                    color="tab:blue", markerfacecolor="white", markeredgewidth=2)
    axes[1, 0].axhline(0.7, color="green", linestyle="--", alpha=0.5)
    axes[1, 0].axhline(0.5, color="orange", linestyle="--", alpha=0.5)
    axes[1, 0].set_ylabel("Pearson r", fontsize=10)
    axes[1, 0].set_title("ρ Recovery by Response Rate", fontsize=11, fontweight="bold")
    axes[1, 0].set_ylim([0, 1])
    axes[1, 0].grid(True, linestyle="--", alpha=0.3)
    for x, y, n in zip(rho_resp_x, rho_resp_r, rho_resp_n):
        axes[1, 0].annotate(f"n={n}", xy=(x, y), xytext=(0, 5), textcoords="offset points",
                           ha="center", fontsize=7, alpha=0.7)

    rho_ans_x, rho_ans_r, rho_ans_n, _ = compute_recovery_by_answered_obs(
        df_users, "true_rho", "rho_hat")
    axes[1, 1].plot(rho_ans_x, rho_ans_r, "s-", linewidth=2.5, markersize=8,
                    color="tab:red", markerfacecolor="white", markeredgewidth=2)
    axes[1, 1].axhline(0.7, color="green", linestyle="--", alpha=0.5)
    axes[1, 1].axhline(0.5, color="orange", linestyle="--", alpha=0.5)
    axes[1, 1].set_title("ρ Recovery by Answered Observations", fontsize=11, fontweight="bold")
    axes[1, 1].set_ylim([0, 1])
    axes[1, 1].grid(True, linestyle="--", alpha=0.3)
    for x, y, n in zip(rho_ans_x, rho_ans_r, rho_ans_n):
        axes[1, 1].annotate(f"n={n}", xy=(x, y), xytext=(0, 5), textcoords="offset points",
                           ha="center", fontsize=7, alpha=0.7)

    # Row 2: Sigma Recovery
    sigma_resp_x, sigma_resp_r, sigma_resp_n = compute_recovery_by_response_rate(
        df_users, "true_sigma", "sigma_hat")
    axes[2, 0].plot(sigma_resp_x, sigma_resp_r, "o-", linewidth=2.5, markersize=8,
                    color="tab:blue", markerfacecolor="white", markeredgewidth=2)
    axes[2, 0].axhline(0.7, color="green", linestyle="--", alpha=0.5)
    axes[2, 0].axhline(0.5, color="orange", linestyle="--", alpha=0.5)
    axes[2, 0].set_xlabel("Response Rate (fraction of EMA answered)", fontsize=10)
    axes[2, 0].set_ylabel("Pearson r", fontsize=10)
    axes[2, 0].set_title("σ Recovery by Response Rate", fontsize=11, fontweight="bold")
    axes[2, 0].set_ylim([0, 1])
    axes[2, 0].grid(True, linestyle="--", alpha=0.3)
    for x, y, n in zip(sigma_resp_x, sigma_resp_r, sigma_resp_n):
        axes[2, 0].annotate(f"n={n}", xy=(x, y), xytext=(0, 5), textcoords="offset points",
                           ha="center", fontsize=7, alpha=0.7)

    sigma_ans_x, sigma_ans_r, sigma_ans_n, _ = compute_recovery_by_answered_obs(
        df_users, "true_sigma", "sigma_hat")
    axes[2, 1].plot(sigma_ans_x, sigma_ans_r, "s-", linewidth=2.5, markersize=8,
                    color="tab:red", markerfacecolor="white", markeredgewidth=2)
    axes[2, 1].axhline(0.7, color="green", linestyle="--", alpha=0.5)
    axes[2, 1].axhline(0.5, color="orange", linestyle="--", alpha=0.5)
    axes[2, 1].set_xlabel("Number of Answered EMA Observations", fontsize=10)
    axes[2, 1].set_title("σ Recovery by Answered Observations", fontsize=11, fontweight="bold")
    axes[2, 1].set_ylim([0, 1])
    axes[2, 1].grid(True, linestyle="--", alpha=0.3)
    for x, y, n in zip(sigma_ans_x, sigma_ans_r, sigma_ans_n):
        axes[2, 1].annotate(f"n={n}", xy=(x, y), xytext=(0, 5), textcoords="offset points",
                           ha="center", fontsize=7, alpha=0.7)

    fig.suptitle("Parameter Recovery Robustness: Sensitivity to Data Availability", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURE_DIR, "recovery_by_data_availability.png"), bbox_inches="tight", dpi=100)
    print(f"  recovery_by_data_availability.png")



def main():
    print("Loading decision log...")
    df_log = load_decision_log()
    print(f"  loaded {len(df_log)} decision records from {len(df_log['user_id'].unique())} users")

    print("\nSummarizing per-user metrics...")
    df_users = summarize_per_user(df_log)
    print(f"  {len(df_users)} users with sufficient EMA data")

    print("\nGenerating figures...")
    print("  Plots:")
    slope, r, spearman = plot_mssd_recovery(df_users)
    plot_param_recovery_scatter(df_users)
    plot_prompt_triggers(df_log)
    plot_mssd_over_time(df_log)
    plot_recovery_by_data_availability(df_users)

    # Summary statistics
    print("\n" + "=" * 70)
    print("MSSD RECOVERY STATISTICS")
    print("=" * 70)
    print(f"Users analyzed        : {len(df_users)}")
    print(f"OLS slope             : {slope:.3f}")
    print(f"Pearson r             : {r:.3f}")
    print(f"Spearman ρ            : {spearman:.3f}")
    print(f"Mean empirical MSSD   : {df_users['empirical_mssd'].mean():.3f}")
    print(f"Mean true expected    : {df_users['true_expected_mssd'].mean():.3f}")
    print(f"\nDECISION STATISTICS")
    print(f"Total decisions       : {len(df_log)}")
    print(f"Prompts sent          : {df_log['send_prompt'].sum()} ({df_log['send_prompt'].mean()*100:.1f}%)")
    print(f"Prompts not sent      : {(~df_log['send_prompt']).sum()} ({(~df_log['send_prompt']).mean()*100:.1f}%)")
    print(f"\nFigures written to    : {FIGURE_DIR}")
    print("=" * 70)

    # Save per-user summary
    summary_path = os.path.join(FIGURE_DIR, "per_user_summary.csv")
    df_users.to_csv(summary_path, index=False)
    print(f"Per-user summary      : {summary_path}")


if __name__ == "__main__":
    main()
