"""
Luck Check — was a run of trades skill or variance?

For each selected trade the user supplies entry IV. From IV we derive the
expected move over the holding window, convert the actual realized return to a
z-score, then beta-adjust against the better-correlated market proxy (SPY or
QQQ) — stripping the market's contribution from BOTH the return (mean) and the
volatility (variance). The per-trade residual z's are then combined.

The statistics, plainly:
  - IV is an annualized 1-sigma. Divide by sqrt(252) for daily sigma, scale by
    sqrt(trading_days_held) for the holding window (variance adds over days).
  - z_raw = actual_return / sigma_hold.
  - Beta strip: r_resid = r_actual - beta * r_market. This removes the part of
    the gain that was just the stock following the market.
  - Variance strip: sigma_resid = sigma_hold * sqrt(1 - rho^2). When we remove
    the market's push on the return we must also remove the market's share of
    the normal wobble, or the z is measured against the wrong yardstick.
  - z_adj = r_resid / sigma_resid.
  - Combine with Stouffer: Z = sum(z_adj) / sqrt(n), which under the null is
    itself standard normal.

Why Stouffer and not Fisher (which this module used previously):
  Fisher's method combines p-values and answers "is AT LEAST ONE of these
  trades unusual?" — a single lucky outlier drags the whole result significant
  while direction is discarded, so a big winner and an equally big loser both
  push toward "significant". The question this tool actually asks is "does the
  average market-adjusted return beat zero?", which is a test on the MEAN.
  Stouffer answers exactly that, respects sign (losers correctly cancel
  winners), and is not hijacked by one outlier. Fisher is still reported as a
  secondary diagnostic.

On reporting: the strength band is taken from the TWO-tailed p, so a run is not
called significant merely because we picked the direction after seeing it. A
consistently bad run is now reported as such instead of being scored
"unremarkable", which the old one-tailed test did — six 15% losses returned a
p of exactly 1.0.

What the p-value is NOT: it is P(results at least this extreme | no edge). It
is NOT the probability that the run was luck. Nothing here should be presented
as "X% chance this was luck" — that inverts the conditional.

beta and rho are estimated from trailing daily history (not typed). The
benchmark is auto-picked per trade as whichever of SPY/QQQ correlates higher
with that stock over the estimation window.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np

TRADING_DAYS_YEAR = 252
BETA_LOOKBACK = "1y"          # window for estimating beta/rho
MIN_BETA_OBS = 60             # need enough overlapping days to trust beta/rho

# Cap on |rho| used in the variance strip. sigma_resid = sigma_hold*sqrt(1-rho^2)
# collapses toward zero as |rho| -> 1, and z_adj = r_resid/sigma_resid explodes
# with it: at rho=0.999 a mundane +0.5% move scores z=+4.5 (p<0.0001) purely
# because the denominator vanished. rho is ESTIMATED from a year of noisy daily
# returns, so trusting it past ~0.95 reads estimation error as skill.
RHO_CAP = 0.95


# ---- Normal CDF without scipy (erf is in the stdlib) ----

def _norm_cdf(z: float) -> float:
    """Standard normal CDF via erf — no scipy dependency."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _trading_days_between(entry: str, exit: str) -> int:
    """Count trading days between entry and exit using numpy's busday count.

    Weekends excluded (holidays are not — a minor overcount). Minimum of 1 so a
    same-day or one-session trade still has a positive window for sqrt(t).
    """
    d0 = np.datetime64(entry, "D")
    d1 = np.datetime64(exit, "D")
    n = int(np.busday_count(d0, d1))
    return max(1, n)


def _fetch_closes(ticker: str, lookback: str = BETA_LOOKBACK):
    """Trailing daily closes as a pandas Series indexed by date. None on fail."""
    try:
        import yfinance as yf
        d = yf.download(ticker, period=lookback, interval="1d",
                        progress=False, auto_adjust=True)
        if d is not None and len(d) > 0:
            return d["Close"].squeeze().dropna()
    except Exception:
        pass
    return None


def _returns(series):
    """Daily simple returns from a close series."""
    import pandas as pd  # noqa
    return series.pct_change().dropna()


def _beta_rho(stock_ret, bench_ret):
    """OLS beta and Pearson rho of stock vs benchmark on aligned daily returns.

    beta = cov(s,b)/var(b); rho = corr(s,b). Returns (beta, rho, n_obs).
    """
    joined = stock_ret.to_frame("s").join(bench_ret.to_frame("b"), how="inner").dropna()
    n = len(joined)
    if n < MIN_BETA_OBS:
        return None, None, n
    s = joined["s"].to_numpy()
    b = joined["b"].to_numpy()
    var_b = float(np.var(b, ddof=1))
    if var_b == 0:
        return None, None, n
    cov = float(np.cov(s, b, ddof=1)[0, 1])
    beta = cov / var_b
    sd_s = float(np.std(s, ddof=1))
    sd_b = float(np.std(b, ddof=1))
    rho = cov / (sd_s * sd_b) if sd_s > 0 and sd_b > 0 else 0.0
    return beta, rho, n


def _window_return(series, entry: str, exit: str):
    """Realized return of a close series over [entry, exit], nearest-prior fill.

    Resolves each endpoint to the last close on or before that date, so a date
    landing on a weekend/holiday still resolves.
    """
    if series is None or len(series) == 0:
        return None
    idx = [d.strftime("%Y-%m-%d") for d in series.index]
    vals = series.to_numpy(dtype=float)

    def price_on(target):
        chosen = None
        for d, v in zip(idx, vals):
            if d <= target:
                chosen = v
            else:
                break
        return chosen

    p0 = price_on(entry)
    p1 = price_on(exit)
    if p0 is None or p1 is None or p0 == 0:
        return None
    return p1 / p0 - 1.0


# cache benchmark series across trades in one calculate() call
def _bench_cache():
    return {}


# ---------------------------------------------------------------------------
# Shared with engine.alpha.
#
# Both tools beta-adjust against SPY, and they must agree: if Luck Check says a
# trade's market-explained return was X, the Ledger's alpha must strip the same
# X. Publishing these as aliases keeps one implementation rather than two that
# can drift apart.
# ---------------------------------------------------------------------------

fetch_closes = _fetch_closes
daily_returns = _returns
beta_rho = _beta_rho
window_return = _window_return


def score_trade(trade: dict, bench_series: dict) -> dict:
    """Score a single trade. `trade` carries:
        ticker, entryDate, exitDate, entryPrice, exitPrice, iv (decimal, e.g. .92)
    `bench_series` is a shared {symbol: closeSeries} cache for SPY/QQQ.

    Returns a dict with the full breakdown (everything the UI shows).
    """
    ticker = trade["ticker"]
    entry = trade["entryDate"]
    exit = trade["exitDate"]
    iv = float(trade["iv"])
    r_actual = float(trade["exitPrice"]) / float(trade["entryPrice"]) - 1.0

    out = {
        "ticker": ticker,
        "entryDate": entry,
        "exitDate": exit,
        "iv": iv,
        "r_actual": r_actual,
        # Always present so the frontend never hits an undefined field, even on
        # an error/short-circuit row.
        "trading_days": None,
        "sigma_hold": None,
        "z_raw": None,
        "benchmark": None,
        "beta": None,
        "rho": None,
        "rho_used": None,
        "rho_capped": False,
        "r_market": None,
        "r_resid": None,
        "sigma_resid": None,
        "z_adj": None,
        "p": None,
        "adjusted": False,
        "note": None,
        "error": None,
    }

    t_days = _trading_days_between(entry, exit)
    out["trading_days"] = t_days

    # Expected move from IV over the holding window.
    sigma_daily = iv / math.sqrt(TRADING_DAYS_YEAR)
    sigma_hold = sigma_daily * math.sqrt(t_days)
    out["sigma_hold"] = sigma_hold
    if sigma_hold <= 0:
        out["error"] = "Non-positive sigma (check IV)."
        return out

    out["z_raw"] = r_actual / sigma_hold

    # Estimate beta/rho vs both benchmarks; auto-pick higher |rho|.
    stock_close = _fetch_closes(ticker)
    chosen = None
    if stock_close is not None and len(stock_close) > MIN_BETA_OBS:
        stock_ret = _returns(stock_close)
        best = None
        for sym in ("SPY", "QQQ"):
            bser = bench_series.get(sym)
            if bser is None:
                bser = _fetch_closes(sym)
                bench_series[sym] = bser
            if bser is None:
                continue
            bret = _returns(bser)
            beta, rho, n = _beta_rho(stock_ret, bret)
            if beta is None:
                continue
            if best is None or abs(rho) > abs(best["rho"]):
                # market return over THIS trade's window, from the benchmark series
                r_market_bench = _window_return(bser, entry, exit)
                best = {"sym": sym, "beta": beta, "rho": rho, "n": n,
                        "r_bench": r_market_bench}
        chosen = best

    def _unadjusted(note: str):
        """Fall back to the un-adjusted z, flagged, rather than inventing one."""
        out["r_resid"] = r_actual
        out["sigma_resid"] = sigma_hold
        out["z_adj"] = out["z_raw"]
        out["p"] = 1.0 - _norm_cdf(out["z_adj"])
        out["adjusted"] = False
        out["note"] = note
        return out

    if chosen is None or chosen["r_bench"] is None:
        return _unadjusted("No market estimate; showing un-adjusted z.")

    # Trading the benchmark itself: there is no residual to measure, and
    # rho == 1 would collapse sigma_resid to near zero and manufacture a huge
    # z out of rounding noise. Report it honestly instead.
    if ticker.strip().upper() == chosen["sym"]:
        out["benchmark"] = chosen["sym"]
        out["beta"] = chosen["beta"]
        out["rho"] = chosen["rho"]
        out["bench_return"] = chosen["r_bench"]
        out["beta_obs"] = chosen["n"]
        return _unadjusted(
            f"Traded instrument is the benchmark ({chosen['sym']}); "
            "no market adjustment is meaningful."
        )

    beta = chosen["beta"]
    rho_raw = chosen["rho"]
    # Cap before the variance strip — see RHO_CAP.
    rho_used = max(-RHO_CAP, min(RHO_CAP, rho_raw))
    capped = abs(rho_raw) > RHO_CAP

    r_market = beta * chosen["r_bench"]
    r_resid = r_actual - r_market
    sigma_resid = sigma_hold * math.sqrt(1.0 - rho_used * rho_used)

    out["benchmark"] = chosen["sym"]
    out["beta"] = beta
    out["rho"] = rho_raw
    out["rho_used"] = rho_used
    out["rho_capped"] = capped
    out["bench_return"] = chosen["r_bench"]
    out["r_market"] = r_market
    out["r_resid"] = r_resid
    out["sigma_resid"] = sigma_resid
    out["beta_obs"] = chosen["n"]
    if capped:
        out["note"] = (
            f"rho {rho_raw:.3f} capped to {rho_used:.2f} — this name tracks "
            f"{chosen['sym']} so closely that the residual is mostly estimation noise."
        )

    # Both z's: adjusted (headline) and beta-on-mean-only (for comparison).
    out["z_adj"] = r_resid / sigma_resid if sigma_resid > 0 else 0.0
    out["z_mean_only"] = r_resid / sigma_hold if sigma_hold > 0 else 0.0
    out["p"] = 1.0 - _norm_cdf(out["z_adj"])
    out["p_raw"] = 1.0 - _norm_cdf(out["z_raw"])
    out["adjusted"] = True
    return out


def _band(p_two: float) -> str:
    """Strength of evidence from the TWO-tailed p. Direction is applied by the
    caller — this is only how far from chance the run sits."""
    if p_two < 1e-4:
        return "extraordinary"
    if p_two < 1e-3:
        return "very_strong"
    if p_two < 1e-2:
        return "strong"
    if p_two < 0.05:
        return "moderate"
    if p_two < 0.2:
        return "weak"
    return "none"


_VERDICT_ABOVE = {
    "extraordinary": "Extraordinary evidence of edge",
    "very_strong": "Very strong evidence of edge",
    "strong": "Strong evidence of edge",
    "moderate": "Moderate evidence of edge",
    "weak": "Weak hint of edge",
    "none": "No evidence of edge",
}
_VERDICT_BELOW = {
    "extraordinary": "Extraordinarily worse than chance",
    "very_strong": "Far worse than chance",
    "strong": "Significantly worse than chance",
    "moderate": "Moderately worse than chance",
    "weak": "Weak hint of underperformance",
    "none": "No evidence of edge",
}


def _detail(band: str, direction: str, p_dir: float, n: int) -> str:
    """One honest sentence about frequency. Deliberately phrased as 'how often
    chance does this', never as 'probability this was luck'."""
    if band == "none":
        return (
            f"Across {n} trade{'s' if n != 1 else ''} your market-adjusted returns sit "
            "about where chance alone would put them. That is not a verdict of "
            "'no skill' — it means this sample is too ordinary to show one either way."
        )
    word = "good" if direction == "above" else "poor"
    if p_dir <= 0:
        freq = "less than 1 in 1,000,000 times"
    elif p_dir >= 0.5:
        freq = f"about {p_dir * 100:.0f}% of the time"
    else:
        n_in = round(1.0 / p_dir)
        freq = f"about 1 in {n_in:,} times" if n_in < 1_000_000 else "less than 1 in 1,000,000 times"
    return (
        f"A run at least this {word}, after stripping out the market, happens "
        f"{freq} by chance alone."
    )


# ---- Sample-size read -------------------------------------------------------
#
# The verdict alone is not enough to act on, because "No evidence of edge" means
# two completely different things at n=6 and at n=200. At n=6 it means the test
# is structurally blind; at n=200 it means a real edge would have shown up. So
# every result also carries a plain-language note about what THIS sample can and
# cannot resolve, computed rather than looked up in a table.
#
#   detection floor : |mean_z| must exceed 1.96/sqrt(n) to reach p<0.05 here.
#   trades needed   : (2.80/|mean_z|)^2 gives 80% power at p<0.05 for the effect
#                     size actually observed. 2.80 = 1.96 (alpha) + 0.84 (power).

MIN_USEFUL_N = 10          # below this the floor exceeds any realistic edge
PROVISIONAL_N = 30         # above this a clearing result stops being fragile
IMPLAUSIBLE_MEAN_Z = 0.8   # per-trade edges this big usually mean a bad IV
N_NEEDED_CAP = 2000        # past here, quoting a precise number is silly


def _effect_label(mz: float) -> str:
    """Magnitude only — these words also follow 'negative tilt', so they must
    describe size without implying the result is good ('a solid negative tilt'
    reads as praise for a bad outcome)."""
    a = abs(mz)
    if a < 0.05:
        return "flat"
    if a < 0.15:
        return "very slight"
    if a < 0.30:
        return "modest"
    if a < 0.50:
        return "sizeable"
    if a < IMPLAUSIBLE_MEAN_Z:
        return "large"
    return "extreme"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _sample_guidance(n: int, mean_z: float, p_two: float) -> dict:
    """What this sample size can resolve, in words. Returns the structured
    numbers too so the UI can show them without recomputing."""
    floor = 1.96 / math.sqrt(n) if n > 0 else None
    a = abs(mean_z)
    n_needed = math.ceil((2.80 / a) ** 2) if a > 1e-6 else None
    label = _effect_label(mean_z)
    tilt = "positive tilt" if mean_z > 0 else "negative tilt" if mean_z < 0 else "result"
    plural = "s" if n != 1 else ""

    def needed_phrase() -> str:
        if n_needed is None or n_needed > N_NEEDED_CAP:
            return (
                "An effect this small is not realistically confirmable — you would "
                f"need well over {N_NEEDED_CAP:,} trades."
            )
        return f"Confirming an effect this size would take roughly {n_needed:,} trades."

    # 1. Sample too small for the test to see anything realistic.
    if n < MIN_USEFUL_N:
        note = (
            f"With only {n} trade{plural}, this test can just about detect a "
            f"{floor:.2f} sigma per-trade edge — far bigger than any real edge looks. "
            "Read the verdict as 'not enough data yet', not as a finding. "
            "Around 30–50 trades is where it starts to carry weight."
        )
        return {"detection_floor": floor, "n_for_power": n_needed,
                "effect_label": label, "resolvable": False, "sample_note": note}

    # 2. Result clears the bar for this sample size.
    if p_two < 0.05:
        extra = ""
        if n < PROVISIONAL_N:
            extra = (
                f" At {n} trades this is still provisional — the same effect over "
                "50+ trades would be much harder to argue with."
            )
        if label == "extreme":
            extra += (
                " A per-trade edge this large is unusual; it is worth re-checking "
                "the IVs you typed, since every number scales off them."
            )
        note = (
            f"Your {n} trades show {_article(label)} {label} {tilt} (mean z {mean_z:+.3f}), "
            f"which clears the {floor:.2f} threshold a sample this size can resolve.{extra}"
        )
        return {"detection_floor": floor, "n_for_power": n_needed,
                "effect_label": label, "resolvable": True, "sample_note": note}

    # 3. Measured effect is essentially zero — a meaningful finding on its own.
    if label == "flat":
        note = (
            f"Your {n} trades measure essentially flat (mean z {mean_z:+.3f}) — you "
            "captured almost exactly what the options market priced, once the "
            f"market's own move is stripped out. This sample resolves edges above "
            f"{floor:.2f}; anything smaller stays invisible no matter how it is read."
        )
        return {"detection_floor": floor, "n_for_power": n_needed,
                "effect_label": label, "resolvable": False, "sample_note": note}

    # 4. Something is there, but the sample cannot separate it from noise.
    note = (
        f"Your {n} trades show {_article(label)} {label} {tilt} (mean z {mean_z:+.3f}), but at this "
        f"sample size the test only resolves edges above {floor:.2f} — so this sits "
        "inside the noise floor. That is not evidence of edge, and equally not "
        f"evidence against one. {needed_phrase()}"
    )
    return {"detection_floor": floor, "n_for_power": n_needed,
            "effect_label": label, "resolvable": False, "sample_note": note}


def calculate(trades: list[dict]) -> dict:
    """Score all trades and combine. `trades` each carry ticker/dates/prices/iv."""
    bench_series = _bench_cache()
    scored = [score_trade(t, bench_series) for t in trades]

    valid = [s for s in scored if s.get("error") is None and s.get("z_adj") is not None]
    n = len(valid)

    n_winners = sum(1 for s in valid if s["r_actual"] > 0)
    n_losers = sum(1 for s in valid if s["r_actual"] <= 0)
    all_winners = bool(valid) and n_losers == 0

    if n == 0:
        return {
            "trades": scored,
            "n": 0,
            "n_winners": 0,
            "n_losers": 0,
            "all_winners": False,
            "z_combined": None,
            "p_two_tailed": None,
            "p_directional": None,
            "direction": None,
            "band": "none",
            "verdict": "Nothing to score",
            "detail": "No trade produced a usable score.",
            "fisher_p": None,
            "mean_z": None,
            "detection_floor": None,
            "n_for_power": None,
            "effect_label": None,
            "resolvable": False,
            "sample_note": "No trade produced a usable score.",
            "caveats": _CAVEATS,
        }

    # ---- Stouffer: Z = sum(z_i)/sqrt(n), standard normal under the null ----
    z_sum = sum(s["z_adj"] for s in valid)
    z_combined = z_sum / math.sqrt(n)
    mean_z = z_sum / n

    p_upper = 1.0 - _norm_cdf(z_combined)
    p_lower = _norm_cdf(z_combined)
    direction = "above" if z_combined >= 0 else "below"
    p_directional = p_upper if direction == "above" else p_lower
    # Two-tailed, so calling a run significant doesn't depend on having picked
    # the direction after seeing the data.
    p_two = min(1.0, 2.0 * min(p_upper, p_lower))

    band = _band(p_two)
    verdict = (_VERDICT_ABOVE if direction == "above" else _VERDICT_BELOW)[band]
    detail = _detail(band, direction, p_directional, n)

    # Fisher retained as a secondary diagnostic only — it answers a different
    # question (is any single trade unusual) and is outlier-driven.
    chi = -2.0 * sum(math.log(max(1e-12, s["p"])) for s in valid)
    fisher_p = _chi2_sf(chi, 2 * n)

    guide = _sample_guidance(n, mean_z, p_two)

    return {
        "trades": scored,
        "n": n,
        "n_winners": n_winners,
        "n_losers": n_losers,
        "all_winners": all_winners,
        "z_combined": z_combined,
        "mean_z": mean_z,
        "p_two_tailed": p_two,
        "p_directional": p_directional,
        "direction": direction,
        "band": band,
        "verdict": verdict,
        "detail": detail,
        "fisher_p": fisher_p,
        # What this sample size can and cannot resolve — see _sample_guidance.
        "detection_floor": guide["detection_floor"],
        "n_for_power": guide["n_for_power"],
        "effect_label": guide["effect_label"],
        "resolvable": guide["resolvable"],
        "sample_note": guide["sample_note"],
        "caveats": _CAVEATS,
    }


_CAVEATS = [
    "This is a p-value: how often chance alone produces a run like yours. It is NOT the probability that your run was luck — that is a different quantity and this tool cannot compute it.",
    "Assumes returns are normal — understates fat-tail moves, especially on short holds, so the true p is a little higher than shown.",
    "Valid only if losers are included. Selecting winners only guarantees a flattering number by construction.",
    "Assumes trades are independent. Positions held over the same market days are correlated, which makes the combined figure look more significant than it is.",
    "IV is your typed entry IV, taken at face value. A wrong IV moves every number downstream of it.",
]


def _chi2_sf(x: float, k: int) -> float:
    """Survival function (1 - CDF) of chi-square with k dof, via the regularized
    upper incomplete gamma Q(k/2, x/2). Implemented with a series/continued-
    fraction split — no scipy.
    """
    if x <= 0:
        return 1.0
    return _gammaincc(k / 2.0, x / 2.0)


def _gammaincc(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a,x) = 1 - P(a,x)."""
    if x < 0 or a <= 0:
        return 1.0
    if x < a + 1.0:
        # series for P(a,x), then complement
        return 1.0 - _gammainc_series(a, x)
    else:
        return _gammainc_cf(a, x)


def _gammainc_series(a: float, x: float) -> float:
    """Lower regularized P(a,x) via series expansion."""
    ap = a
    s = 1.0 / a
    delta = s
    for _ in range(500):
        ap += 1.0
        delta *= x / ap
        s += delta
        if abs(delta) < abs(s) * 1e-12:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gammainc_cf(a: float, x: float) -> float:
    """Upper regularized Q(a,x) via continued fraction (Lentz)."""
    tiny = 1e-30
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
