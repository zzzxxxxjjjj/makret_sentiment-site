from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from test_erp_rsi_effect import clean_metrics, evaluate, rsi_wilder


BASE_DIR = Path(__file__).resolve().parent
SPLIT_DATE = pd.Timestamp("2023-01-01")


def main():
    cache = json.loads(
        (BASE_DIR / "broad-sentiment-page-cache.json").read_text(encoding="utf-8")
    )["payload"]
    frame = pd.DataFrame(cache["cycleComparison"]["points"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    if "originalBreadthSentiment" in frame.columns:
        frame["sentiment"] = frame["originalBreadthSentiment"].fillna(
            frame["sentiment"]
        )
    frame = frame[["sentiment", "windAll"]].apply(pd.to_numeric, errors="coerce")
    frame["rsi14"] = rsi_wilder(frame["windAll"], 14)
    frame["rsiHeat"] = frame["rsi14"].ewm(
        span=3, adjust=False, min_periods=2
    ).mean()
    centered_min = frame["windAll"].rolling(61, center=True, min_periods=41).min()
    centered_max = frame["windAll"].rolling(61, center=True, min_periods=41).max()
    frame["cyclePosition"] = (
        (frame["windAll"] - centered_min) / (centered_max - centered_min) * 100
    )
    frame = frame.dropna(
        subset=["sentiment", "windAll", "rsiHeat", "cyclePosition"]
    )
    train = frame[frame.index < SPLIT_DATE]
    test = frame[frame.index >= SPLIT_DATE]

    baseline_low_share = float((train["sentiment"] <= 30).mean())
    baseline_high_share = float((train["sentiment"] >= 70).mean())
    rows = []
    for weight_integer in range(0, 36, 5):
        weight = weight_integer / 100
        column = f"rsi_{weight_integer:02d}"
        frame[column] = frame["sentiment"] * (1 - weight) + frame["rsiHeat"] * weight
        train = frame[frame.index < SPLIT_DATE]
        test = frame[frame.index >= SPLIT_DATE]
        low_threshold = float(train[column].quantile(baseline_low_share))
        high_threshold = float(train[column].quantile(1 - baseline_high_share))
        rows.append(
            {
                "rsiWeight": weight,
                "baseWeight": 1 - weight,
                "train": clean_metrics(evaluate(train, column)),
                "outOfSample": clean_metrics(evaluate(test, column)),
                "outOfSampleByYear": {
                    str(year): clean_metrics(
                        evaluate(test[test.index.year == year], column)
                    )
                    for year in sorted(test.index.year.unique())
                },
                "fixedThresholdFrequency": {
                    "below30": round(float((test[column] <= 30).mean()), 4),
                    "above70": round(float((test[column] >= 70).mean()), 4),
                },
                "recalibratedThresholds": {
                    "bottom": round(low_threshold, 1),
                    "top": round(high_threshold, 1),
                },
            }
        )

    best_train = max(rows, key=lambda item: item["train"]["objective"])
    result = {
        "asOf": frame.index.max().strftime("%Y-%m-%d"),
        "sample": {
            "start": frame.index.min().strftime("%Y-%m-%d"),
            "end": frame.index.max().strftime("%Y-%m-%d"),
            "trainEnd": "2022-12-31",
            "outOfSampleStart": "2023-01-01",
            "observations": len(frame),
        },
        "definition": "新分数＝原广度情绪×(1-RSI权重)＋万得全A 14日Wilder RSI的3日平滑×RSI权重",
        "baselineTailFrequencyTrain": {
            "below30": round(baseline_low_share, 4),
            "above70": round(baseline_high_share, 4),
        },
        "bestByTrainingSample": {
            "rsiWeight": best_train["rsiWeight"],
            "baseWeight": best_train["baseWeight"],
        },
        "weights": rows,
    }
    (BASE_DIR / "rsi-only-test-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
