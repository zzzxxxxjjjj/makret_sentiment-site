from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from test_erp_rsi_effect import clean_metrics, evaluate, rsi_wilder, rolling_percentile_last


BASE_DIR = Path(__file__).resolve().parent
SPLIT_DATE = pd.Timestamp("2023-01-01")


def load_frame():
    breadth = json.loads(
        (BASE_DIR / "rqdata-breadth-sentiment.json").read_text(encoding="utf-8")
    )
    market = json.loads(
        (BASE_DIR / "rqdata-broad-sentiment.json").read_text(encoding="utf-8")
    )
    frame = pd.DataFrame(breadth["points"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    components = pd.json_normalize(frame["components"]).set_index(frame.index)
    metrics = pd.json_normalize(frame["metrics"]).set_index(frame.index)
    metrics = metrics.rename(
        columns={
            "nhnlBreadth": "nhnlRaw",
            "aboveMaBreadth": "aboveMaRaw",
        }
    )
    prices = next(
        item for item in market["series"] if item.get("id") == "allshare-close"
    )
    price = pd.DataFrame(prices["points"])
    price["date"] = pd.to_datetime(price["date"])
    price = price.set_index("date")["value"].rename("windAll")
    frame = components.join(
        metrics[["newLowBreadth", "nhnlRaw", "aboveMaRaw"]]
    ).join(price, how="inner")
    frame = frame.apply(pd.to_numeric, errors="coerce")
    price_change_20 = frame["windAll"].pct_change(20) * 100
    nhnl_change_20 = frame["nhnlRaw"].diff(20)
    above_ma_change_20 = frame["aboveMaRaw"].diff(20)
    frame["priceBreadthDivergence"] = (
        price_change_20.rolling(750, min_periods=120).apply(
            rolling_percentile_last, raw=True
        )
        - (
            nhnl_change_20.rolling(750, min_periods=120).apply(
                rolling_percentile_last, raw=True
            )
            + above_ma_change_20.rolling(750, min_periods=120).apply(
                rolling_percentile_last, raw=True
            )
        )
        / 2
    )
    frame["newLowContraction5"] = (
        frame["newLowBreadth"].shift(5) - frame["newLowBreadth"]
    )
    frame["newLowContractionScore"] = frame["newLowContraction5"].rolling(
        750, min_periods=120
    ).apply(rolling_percentile_last, raw=True)
    frame["rsiHeat"] = rsi_wilder(frame["windAll"], 14).ewm(
        span=3, adjust=False, min_periods=2
    ).mean()
    centered_min = frame["windAll"].rolling(61, center=True, min_periods=41).min()
    centered_max = frame["windAll"].rolling(61, center=True, min_periods=41).max()
    frame["cyclePosition"] = (
        (frame["windAll"] - centered_min) / (centered_max - centered_min) * 100
    )
    return frame


def add_candidate(frame, name, weights, rsiWeight, span):
    raw = sum(frame[column] * weight for column, weight in weights.items())
    breadth = raw.ewm(span=span, adjust=False).mean()
    frame[name] = breadth * (1 - rsiWeight) + frame["rsiHeat"] * rsiWeight


def lead_objective(metrics):
    lag = metrics["turningPoints"]["medianAbsLag"]
    return (
        metrics["leadCorrelation5D"] * 0.35
        + metrics["leadCorrelation10D"] * 0.30
        + metrics["topBottomAuc"] * 0.15
        + metrics["phaseAgreement10D"] * 0.10
        + metrics["turningPoints"]["matchRate"] * 0.10
        - min(lag, 20) / 20 * 0.05
    )


def main():
    frame = load_frame()
    candidates = {
        "current": {
            "weights": {
                "nhnlBreadth": 0.35,
                "aboveMaBreadth": 0.35,
                "nhnlChange": 0.15,
                "aboveMaChange": 0.15,
            },
            "rsiWeight": 0.20,
            "span": 3,
        },
        "change40_rsi10": {
            "weights": {
                "nhnlBreadth": 0.30,
                "aboveMaBreadth": 0.30,
                "nhnlChange": 0.20,
                "aboveMaChange": 0.20,
            },
            "rsiWeight": 0.10,
            "span": 3,
        },
        "contraction10_rsi10": {
            "weights": {
                "nhnlBreadth": 0.30,
                "aboveMaBreadth": 0.30,
                "nhnlChange": 0.15,
                "aboveMaChange": 0.15,
                "newLowContractionScore": 0.10,
            },
            "rsiWeight": 0.10,
            "span": 3,
        },
        "contraction10_fast": {
            "weights": {
                "nhnlBreadth": 0.30,
                "aboveMaBreadth": 0.30,
                "nhnlChange": 0.15,
                "aboveMaChange": 0.15,
                "newLowContractionScore": 0.10,
            },
            "rsiWeight": 0.10,
            "span": 2,
        },
    }
    add_candidate(frame, "current", **candidates["current"])
    divergence = frame["priceBreadthDivergence"]
    frame["divergence_tilt_05"] = (
        frame["current"] + (-divergence * 0.05).clip(-2, 2)
    ).clip(0, 100)
    frame["divergence_tilt_075"] = (
        frame["current"] + (-divergence * 0.075).clip(-2.5, 2.5)
    ).clip(0, 100)
    frame["divergence_tilt_10"] = (
        frame["current"] + (-divergence * 0.10).clip(-3, 3)
    ).clip(0, 100)
    frame["trend_projection_10"] = (
        frame["current"]
        + ((frame["current"] - frame["current"].shift(5)) * 0.10).clip(-2, 2)
    ).clip(0, 100)
    frame["trend_projection_20"] = (
        frame["current"]
        + ((frame["current"] - frame["current"].shift(5)) * 0.20).clip(-3, 3)
    ).clip(0, 100)
    frame["trend_projection_30"] = (
        frame["current"]
        + ((frame["current"] - frame["current"].shift(5)) * 0.30).clip(-4, 4)
    ).clip(0, 100)
    for name, strength, cap in [
        ("divergence_tilt_05", 0.05, 2.0),
        ("divergence_tilt_075", 0.075, 2.5),
        ("divergence_tilt_10", 0.10, 3.0),
    ]:
        candidates[name] = {
            "derived": "current - clipped(priceBreadthDivergence × strength)",
            "strength": strength,
            "cap": cap,
        }
    for name, strength, cap in [
        ("trend_projection_10", 0.10, 2.0),
        ("trend_projection_20", 0.20, 3.0),
        ("trend_projection_30", 0.30, 4.0),
    ]:
        candidates[name] = {
            "derived": "current + clipped(5-day score change × strength)",
            "strength": strength,
            "cap": cap,
        }
    required = ["windAll", "cyclePosition", "rsiHeat"]
    rows = []
    for name, config in candidates.items():
        if "weights" in config and name != "current":
            add_candidate(frame, name, **config)
        sample = frame.dropna(subset=[name, *required])
        train_metrics = evaluate(sample[sample.index < SPLIT_DATE], name)
        test_metrics = evaluate(sample[sample.index >= SPLIT_DATE], name)
        rows.append(
            {
                "name": name,
                "config": config,
                "trainLeadObjective": round(lead_objective(train_metrics), 4),
                "train": clean_metrics(train_metrics),
                "outOfSample": clean_metrics(test_metrics),
            }
        )
    selected = max(rows, key=lambda item: item["trainLeadObjective"])
    result = {
        "sample": {
            "start": frame.index.min().strftime("%Y-%m-%d"),
            "end": frame.index.max().strftime("%Y-%m-%d"),
            "outOfSampleStart": SPLIT_DATE.strftime("%Y-%m-%d"),
        },
        "selectedByTraining": selected["name"],
        "candidates": rows,
    }
    (BASE_DIR / "leading-tilt-test-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
