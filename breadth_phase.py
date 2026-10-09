from __future__ import annotations


PHASE_LABELS = {
    "rising": "上行",
    "top": "顶部",
    "falling": "下行",
    "bottom": "底部",
    "neutral": "蓄势",
}


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_optimized_phases(points, top_threshold=70, bottom_threshold=25):
    """Relabel breadth-cycle phases without changing the sentiment score.

    The top rule stays level-heavy because it was more stable out of sample.
    The bottom rule requires a rebound from an extreme plus breadth repair,
    which materially improved bottom recall in the post-2023 validation.
    """
    previous = "neutral"
    last_bottom_confirmation = -1000
    for index, point in enumerate(points):
        score = number(point.get("sentiment"))
        if score is None or index < 10:
            phase = "neutral"
        else:
            score5 = number(points[index - 5].get("sentiment"))
            score10 = number(points[index - 10].get("sentiment"))
            slope5 = score - score5 if score5 is not None else 0.0
            slope10 = score - score10 if score10 is not None else 0.0
            recent_scores = [
                number(item.get("sentiment"))
                for item in points[max(0, index - 9):index + 1]
            ]
            recent_scores = [value for value in recent_scores if value is not None]
            recent_min = min(recent_scores) if recent_scores else score

            current_metrics = point.get("metrics", {})
            prior_metrics = points[index - 5].get("metrics", {})
            nhnl_now = number(current_metrics.get("nhnlBreadth"))
            nhnl_prior = number(prior_metrics.get("nhnlBreadth"))
            above_now = number(current_metrics.get("aboveMaBreadth"))
            above_prior = number(prior_metrics.get("aboveMaBreadth"))
            new_low_now = number(current_metrics.get("newLowBreadth"))
            new_low_prior = number(prior_metrics.get("newLowBreadth"))
            repair_confirmations = sum(
                (
                    nhnl_now is not None and nhnl_prior is not None and nhnl_now > nhnl_prior,
                    above_now is not None and above_prior is not None and above_now > above_prior,
                    new_low_now is not None and new_low_prior is not None and new_low_now < new_low_prior,
                )
            )

            # A low score alone is not a bottom. Confirmation requires a
            # five-day rebound from a recent extreme and at least one breadth
            # repair signal.
            bottom_confirmed = (
                recent_min <= bottom_threshold
                and slope5 >= 5
                and repair_confirmations >= 1
                and index - last_bottom_confirmation >= 15
            )
            # A high score is trend strength, not automatically a top. Keep the
            # more stable rollover rule from the prior out-of-sample test.
            top_confirmed = score >= top_threshold and slope10 <= 0

            if top_confirmed:
                phase = "top"
            elif bottom_confirmed:
                phase = "bottom"
                last_bottom_confirmation = index
            elif slope10 > 1:
                phase = "rising"
            elif slope10 < -1:
                phase = "falling"
            elif score >= top_threshold:
                phase = "top"
            else:
                phase = previous if previous in ("rising", "falling") else "neutral"

        point["phase"] = phase
        point["phaseLabel"] = PHASE_LABELS[phase]
        previous = phase
    return points
