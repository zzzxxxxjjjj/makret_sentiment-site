from __future__ import annotations

import json
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy.stats import spearmanr


BASE_DIR = Path(__file__).resolve().parent
SPLIT_DATE = pd.Timestamp("2023-01-01")


def rolling_percentile_last(values):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values[-1]):
        return np.nan
    valid = values[np.isfinite(values)]
    return np.mean(valid <= values[-1]) * 100 if len(valid) else np.nan


def rsi_wilder(prices, period=14):
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100)
    result = result.mask((avg_gain == 0) & (avg_loss > 0), 0)
    return result


def rank_auc(positive, negative):
    positive = pd.Series(positive).dropna().to_numpy()
    negative = pd.Series(negative).dropna().to_numpy()
    if not len(positive) or not len(negative):
        return np.nan
    combined = pd.Series(np.r_[positive, negative])
    ranks = combined.rank(method="average").to_numpy()
    rank_sum = ranks[: len(positive)].sum()
    return (rank_sum - len(positive) * (len(positive) + 1) / 2) / (
        len(positive) * len(negative)
    )


def safe_spearman(left, right):
    paired = pd.concat([pd.Series(left), pd.Series(right)], axis=1).dropna()
    if len(paired) < 30 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
        return np.nan
    return float(spearmanr(paired.iloc[:, 0], paired.iloc[:, 1]).statistic)


def turning_lag(price, score):
    price_smoothed = np.log(price).rolling(5, center=True, min_periods=3).mean()
    score_smoothed = score.rolling(5, center=True, min_periods=3).mean()
    valid = price_smoothed.notna() & score_smoothed.notna()
    price_values = price_smoothed[valid].to_numpy()
    score_values = score_smoothed[valid].to_numpy()
    dates = price_smoothed[valid].index

    price_peaks, _ = find_peaks(price_values, distance=35, prominence=0.055)
    price_troughs, _ = find_peaks(-price_values, distance=35, prominence=0.055)
    score_peaks, _ = find_peaks(score_values, distance=20, prominence=10)
    score_troughs, _ = find_peaks(-score_values, distance=20, prominence=10)

    signed_lags = []
    matched = 0
    total = len(price_peaks) + len(price_troughs)
    for price_turns, score_turns in ((price_peaks, score_peaks), (price_troughs, score_troughs)):
        for price_index in price_turns:
            candidates = score_turns[np.abs(score_turns - price_index) <= 30]
            if len(candidates):
                nearest = candidates[np.argmin(np.abs(candidates - price_index))]
                signed_lags.append(int(nearest - price_index))
                matched += 1
    return {
        "turns": total,
        "matched": matched,
        "matchRate": matched / total if total else np.nan,
        "medianAbsLag": float(np.median(np.abs(signed_lags))) if signed_lags else np.nan,
        "medianSignedLag": float(np.median(signed_lags)) if signed_lags else np.nan,
        "lags": signed_lags,
        "dates": [dates[index].strftime("%Y-%m-%d") for index in np.r_[price_peaks, price_troughs]],
    }


def evaluate(frame, score_column):
    score = frame[score_column]
    cycle_position = frame["cyclePosition"]
    price = frame["windAll"]
    top = cycle_position >= 90
    bottom = cycle_position <= 10
    level_corr = safe_spearman(score, cycle_position)
    lead_corr_5 = safe_spearman(score, cycle_position.shift(-5))
    lead_corr_10 = safe_spearman(score, cycle_position.shift(-10))
    extreme_auc = rank_auc(score[top], score[bottom])
    phase_change = score.diff(10)
    price_change = price.pct_change(10)
    phase_mask = phase_change.abs() >= 3
    phase_agreement = (
        np.sign(phase_change[phase_mask]) == np.sign(price_change[phase_mask])
    ).mean()
    separation = score[top].mean() - score[bottom].mean()
    objective = (
        0.30 * level_corr
        + 0.25 * lead_corr_5
        + 0.20 * lead_corr_10
        + 0.15 * extreme_auc
        + 0.10 * phase_agreement
    )
    turns = turning_lag(price, score)
    return {
        "observations": int(score.notna().sum()),
        "levelCorrelation": float(level_corr),
        "leadCorrelation5D": float(lead_corr_5),
        "leadCorrelation10D": float(lead_corr_10),
        "topBottomAuc": float(extreme_auc),
        "topBottomSeparation": float(separation),
        "phaseAgreement10D": float(phase_agreement),
        "objective": float(objective),
        "turningPoints": turns,
        "topMean": float(score[top].mean()),
        "bottomMean": float(score[bottom].mean()),
    }


def finite(value, digits=4):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def clean_metrics(metrics):
    cleaned = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            cleaned[key] = {
                child_key: (
                    [finite(item, 2) for item in child_value]
                    if child_key == "lags"
                    else child_value
                    if child_key == "dates"
                    else finite(child_value, 4)
                    if isinstance(child_value, (float, np.floating))
                    else child_value
                )
                for child_key, child_value in value.items()
            }
        elif isinstance(value, (float, np.floating)):
            cleaned[key] = finite(value, 4)
        else:
            cleaned[key] = value
    return cleaned


def main():
    cache = json.loads(
        (BASE_DIR / "broad-sentiment-page-cache.json").read_text(encoding="utf-8")
    )["payload"]
    points = cache["cycleComparison"]["points"]
    base = pd.DataFrame(points)
    base["date"] = pd.to_datetime(base["date"])
    base = base.set_index("date").sort_index()
    if "originalBreadthSentiment" in base.columns:
        base["sentiment"] = base["originalBreadthSentiment"].fillna(
            base["sentiment"]
        )
    base = base[["sentiment", "windAll"]].apply(pd.to_numeric, errors="coerce")

    erp = pd.DataFrame(
        json.loads(
            (BASE_DIR / "erp-risk-premium-history.json").read_text(encoding="utf-8")
        )
    )
    erp["date"] = pd.to_datetime(erp["date"])
    erp = erp.set_index("date").sort_index()
    erp["erpPercentile5Y"] = erp["equityRiskPremium"].rolling(
        1250, min_periods=250
    ).apply(rolling_percentile_last, raw=True)
    erp["erpHeat"] = (100 - erp["erpPercentile5Y"]).ewm(
        span=20, adjust=False, min_periods=10
    ).mean()

    frame = base.join(erp[["equityRiskPremium", "erpHeat"]], how="left")
    frame["rsi14"] = rsi_wilder(frame["windAll"], 14)
    frame["rsiHeat"] = frame["rsi14"].ewm(span=3, adjust=False, min_periods=2).mean()
    centered_min = frame["windAll"].rolling(61, center=True, min_periods=41).min()
    centered_max = frame["windAll"].rolling(61, center=True, min_periods=41).max()
    frame["cyclePosition"] = (
        (frame["windAll"] - centered_min) / (centered_max - centered_min) * 100
    )
    frame = frame.dropna(
        subset=["sentiment", "windAll", "erpHeat", "rsiHeat", "cyclePosition"]
    )

    grid = []
    for rsi_weight, erp_weight in product(
        np.arange(0, 0.251, 0.05), np.arange(0, 0.251, 0.05)
    ):
        if rsi_weight + erp_weight > 0.30:
            continue
        name = f"rsi{rsi_weight:.2f}_erp{erp_weight:.2f}"
        frame[name] = (
            frame["sentiment"] * (1 - rsi_weight - erp_weight)
            + frame["rsiHeat"] * rsi_weight
            + frame["erpHeat"] * erp_weight
        )
        train_metrics = evaluate(frame[frame.index < SPLIT_DATE], name)
        grid.append(
            {
                "name": name,
                "rsiWeight": float(rsi_weight),
                "erpWeight": float(erp_weight),
                "train": train_metrics,
            }
        )

    baseline_name = "rsi0.00_erp0.00"
    baseline = next(item for item in grid if item["name"] == baseline_name)
    best = max(grid, key=lambda item: item["train"]["objective"])
    rsi_only = max(
        (item for item in grid if item["erpWeight"] == 0),
        key=lambda item: item["train"]["objective"],
    )
    erp_only = max(
        (item for item in grid if item["rsiWeight"] == 0),
        key=lambda item: item["train"]["objective"],
    )

    selected = {
        "baseline": baseline,
        "lowDose": next(
            item
            for item in grid
            if np.isclose(item["rsiWeight"], 0.10)
            and np.isclose(item["erpWeight"], 0.05)
        ),
        "balanced": next(
            item
            for item in grid
            if np.isclose(item["rsiWeight"], 0.15)
            and np.isclose(item["erpWeight"], 0.05)
        ),
        "rsi15Only": next(
            item
            for item in grid
            if np.isclose(item["rsiWeight"], 0.15)
            and np.isclose(item["erpWeight"], 0)
        ),
        "rsi20Erp05": next(
            item
            for item in grid
            if np.isclose(item["rsiWeight"], 0.20)
            and np.isclose(item["erpWeight"], 0.05)
        ),
        "rsi20Only": next(
            item
            for item in grid
            if np.isclose(item["rsiWeight"], 0.20)
            and np.isclose(item["erpWeight"], 0)
        ),
        "rsiOnly": rsi_only,
        "erpOnly": erp_only,
        "bestCombined": best,
    }
    result = {
        "asOf": frame.index.max().strftime("%Y-%m-%d"),
        "sample": {
            "start": frame.index.min().strftime("%Y-%m-%d"),
            "end": frame.index.max().strftime("%Y-%m-%d"),
            "trainEnd": "2022-12-31",
            "outOfSampleStart": "2023-01-01",
            "observations": len(frame),
        },
        "definitions": {
            "rsi": "万得全A 14日Wilder RSI，3日指数平滑",
            "erp": "Excel风险溢价的5年滚动历史分位倒序，20日指数平滑",
            "cyclePosition": "万得全A在前后各30个交易日价格区间内的位置，仅用于事后验证",
            "weightLimit": "RSI与ERP新增权重合计不超过30%",
        },
        "selected": {},
        "gridTopTrain": [],
    }
    test = frame[frame.index >= SPLIT_DATE]
    for key, item in selected.items():
        result["selected"][key] = {
            "rsiWeight": item["rsiWeight"],
            "erpWeight": item["erpWeight"],
            "train": clean_metrics(item["train"]),
            "outOfSample": clean_metrics(evaluate(test, item["name"])),
            "outOfSampleByYear": {
                str(year): clean_metrics(
                    evaluate(test[test.index.year == year], item["name"])
                )
                for year in sorted(test.index.year.unique())
            },
        }
    for item in sorted(grid, key=lambda row: row["train"]["objective"], reverse=True)[:10]:
        result["gridTopTrain"].append(
            {
                "rsiWeight": item["rsiWeight"],
                "erpWeight": item["erpWeight"],
                "trainObjective": finite(item["train"]["objective"], 4),
                "outOfSampleObjective": finite(
                    evaluate(test, item["name"])["objective"], 4
                ),
            }
        )

    output_path = BASE_DIR / "erp-rsi-test-results.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
