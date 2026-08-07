"""
Scenario-based simulator skeleton for REACT volatility detection

Author: Celia Mercier
"""

import os
import pandas as pd
from datetime import datetime, timedelta

from decision_engine import calculate_mssd, apply_decision_rules


BASE_DIR = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")


class VolatilityScenario:
    def __init__(self, name, ema_values, expected_behavior, late_minutes=None):
        self.name = name
        self.ema_values = ema_values
        self.expected_behavior = expected_behavior
        self.late_minutes = late_minutes

    def build_dataframe(self):
        rows = []
        start_time = datetime(2026, 6, 1, 9, 0)

        if self.late_minutes is None:
            self.late_minutes = [0] * len(self.ema_values)

        for i in range(len(self.ema_values)):
            scheduled_time = start_time + timedelta(hours=i)
            actual_time = scheduled_time + timedelta(minutes=self.late_minutes[i])

            rows.append({
                "user_id": self.name,
                "timestamp": actual_time,
                "scheduled_timestamp": scheduled_time,
                "prompt_idx": i,
                "day": 0,
                "ema": self.ema_values[i],
                "minutes_late": self.late_minutes[i],
            })

        return pd.DataFrame(rows)


class VolatilitySimulator:
    def __init__(self, threshold_quantile=0.80, cooldown_minutes=60, max_prompts_per_day=4):
        self.threshold_quantile = threshold_quantile
        self.cooldown_minutes = cooldown_minutes
        self.max_prompts_per_day = max_prompts_per_day

    def run(self, scenario):
        df = scenario.build_dataframe()

        df = calculate_mssd(df, window=3)

        df = apply_decision_rules(
            df,
            threshold_quantile=self.threshold_quantile,
            cooldown_minutes=self.cooldown_minutes,
            max_prompts_per_day=self.max_prompts_per_day,
        )

        df["scenario"] = scenario.name
        df["expected_behavior"] = scenario.expected_behavior

        return df


def run_test_scenarios():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    scenarios = [
        VolatilityScenario(
            name="low_volatility",
            ema_values=[3, 3, 3, 3, 3, 3],
            expected_behavior="Expected: no prompts because EMA responses are stable.",
        ),

        VolatilityScenario(
            name="high_volatility",
            ema_values=[1, 5, 1, 5, 1, 5],
            expected_behavior="Expected: prompts should be triggered because EMA responses change sharply, while cooldown rules limit repeated prompts.",
        ),

        VolatilityScenario(
            name="missing_and_late",
            ema_values=[3, None, 5, 1, None, 4],
            late_minutes=[0, 0, 45, 90, 0, 120],
            expected_behavior="Expected: missing values should not crash the simulator; late responses should be tracked.",
        ),
    ]

    simulator = VolatilitySimulator(
        threshold_quantile=0.80,
        cooldown_minutes=60,
        max_prompts_per_day=4,
    )

    all_results = []

    for scenario in scenarios:
        result = simulator.run(scenario)
        all_results.append(result)

        print("\nSCENARIO:", scenario.name)
        print(scenario.expected_behavior)
        print(result[[
            "timestamp",
            "scheduled_timestamp",
            "minutes_late",
            "ema",
            "observed_mssd",
            "user_threshold",
            "send_prompt",
            "decision_reason"
        ]])

    final_df = pd.concat(all_results, ignore_index=True)

    final_df.to_csv(
        os.path.join(OUTPUT_DIR, "scenario_test_outputs.csv"),
        index=False
    )

    print("\nDONE RUNNING SCENARIO TESTS")


if __name__ == "__main__":
    run_test_scenarios()