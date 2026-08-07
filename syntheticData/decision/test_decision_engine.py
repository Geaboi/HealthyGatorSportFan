import pandas as pd
from synthetic_generator import generate_user_ids, generate_cohort
from decision_engine import (
    calculate_mssd,
    apply_decision_rules,
    summarize_decisions,
    validate_prompt_counts_vary,
)




def spread_ema_timestamps(df, ema_per_day):
    df = df.copy()
    base_date = pd.Timestamp("2026-06-01")
    hours_by_prompt = [9, 12, 15, 18, 21]


    def make_timestamp(row):
        day_offset = int(row["prompt_idx"]) // ema_per_day
        prompt_in_day = int(row["prompt_idx"]) % ema_per_day
        hour = hours_by_prompt[prompt_in_day]
        return base_date + pd.Timedelta(days=day_offset, hours=hour)


    df["timestamp"] = df.apply(make_timestamp, axis=1)
    return df




def make_test_cohort():
    user_ids = generate_user_ids(100)
    cohort_parts = []


    for i, user_id in enumerate(user_ids):
        resp_rate = 0.65 + (i % 8) * 0.04


        user_df = generate_cohort(
            users=1,
            days=7,
            ema_per_day=5,
            seed=42 + i,
            resp_rate=resp_rate,
            user_ids=[user_id],
        )


        cohort_parts.append(user_df)


    ema_df = pd.concat(cohort_parts, ignore_index=True)
    return spread_ema_timestamps(ema_df, 5)




def test_prompt_counts_vary_across_users():
    ema_df = make_test_cohort()


    decision_df = calculate_mssd(ema_df, window=3)


    decision_df = apply_decision_rules(
        decision_df,
        threshold_quantile=0.80,
        cooldown_minutes=60,
        max_prompts_per_day=4,
    )


    summary_df = summarize_decisions(decision_df)


    assert validate_prompt_counts_vary(summary_df)




def test_send_prompt_matches_decision_reason():
    ema_df = make_test_cohort()


    decision_df = calculate_mssd(ema_df, window=3)


    decision_df = apply_decision_rules(
        decision_df,
        threshold_quantile=0.80,
        cooldown_minutes=60,
        max_prompts_per_day=4,
    )


    assert (
        decision_df["send_prompt"]
        == (decision_df["decision_reason"] == "prompt sent")
    ).all()




def test_missing_ema_never_sends_prompt():
    ema_df = pd.DataFrame({
        "user_id": ["user_1"] * 6,
        "timestamp": pd.to_datetime([
            "2026-06-01 09:00",
            "2026-06-01 12:00",
            "2026-06-01 15:00",
            "2026-06-01 18:00",
            "2026-06-01 21:00",
            "2026-06-02 09:00",
        ]),
        "ema": [3, 3, 3, None, 5, 1],
    })


    decision_df = calculate_mssd(ema_df, window=3)
    decision_df = apply_decision_rules(decision_df)


    missing_rows = decision_df[decision_df["ema"].isna()]


    assert not missing_rows["send_prompt"].any()
    assert (missing_rows["decision_reason"] == "missing or insufficient EMA data").all()
