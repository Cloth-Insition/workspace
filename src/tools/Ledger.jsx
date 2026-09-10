import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, Area, ComposedChart, BarChart, Bar, Cell, ReferenceArea
} from 'recharts';
import {
  TrendingUp, TrendingDown, Plus, Download, Edit3, Trash2,
  BarChart3, List, X, AlertTriangle, CheckCircle2, LayoutDashboard,
  BookOpen, Sparkles, Activity, Dices, Scale, Target, Flame,
  Calendar, ChevronDown, Info, RefreshCw
} from 'lucide-react';

/* ───────────────────────── SEED DATA ───────────────────────── */

const SEED_TRADES = [
  {
    id: "cat-2026-05-27",
    ticker: "CAT",
    entryDate: "2026-05-27",
    exitDate: "2026-05-28",
    entryPrice: 904.0,
    exitPrice: 886.0,
    accountValueAtEntry: 2550.0,
    positionDollars: 600.0,
    conviction: 3,
    setupType: "breakout",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "meta-2026-05-28",
    ticker: "META",
    entryDate: "2026-05-28",
    exitDate: "2026-05-29",
    entryPrice: 639.05,
    exitPrice: 625.4,
    accountValueAtEntry: 2538.05,
    positionDollars: 550.0,
    conviction: 3,
    setupType: "bounce",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "rs-2026-05-28",
    ticker: "RS",
    entryDate: "2026-05-28",
    exitDate: "2026-06-03",
    entryPrice: 377.73,
    exitPrice: 392.68,
    accountValueAtEntry: 2538.05,
    positionDollars: 599.0,
    conviction: 3,
    setupType: "bounce",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "jpm-2026-05-29",
    ticker: "JPM",
    entryDate: "2026-05-29",
    exitDate: "2026-06-01",
    entryPrice: 298.61,
    exitPrice: 295.94,
    accountValueAtEntry: 2526.31,
    positionDollars: 650.0,
    conviction: 3,
    setupType: "dip_buy",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "cat-2026-06-01",
    ticker: "CAT",
    entryDate: "2026-06-01",
    exitDate: "2026-06-03",
    entryPrice: 866.16,
    exitPrice: 925.07,
    accountValueAtEntry: 2520.49,
    positionDollars: 450.0,
    conviction: 2,
    setupType: "dip_buy",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "rig-2026-06-08",
    ticker: "RIG",
    entryDate: "2026-06-08",
    exitDate: "2026-06-09",
    entryPrice: 6.218,
    exitPrice: 5.84,
    accountValueAtEntry: 2445.0,
    positionDollars: 650.0,
    conviction: 3,
    setupType: "dip_buy",
    scaledInOut: false,
    followedRules: true,
    notes: "Wasn't available to sell when my alert was hit and the stock dropped 6% total. Looking back, oil, which is headline heavy, was not a smart decision to trade.",
  },
  {
    id: "mu-2026-06-11",
    ticker: "MU",
    entryDate: "2026-06-11",
    exitDate: "2026-06-15",
    entryPrice: 942.54,
    exitPrice: 1075.65,
    accountValueAtEntry: 2405.49,
    positionDollars: 549.0,
    conviction: 3,
    setupType: "bounce",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "cat-2026-06-11",
    ticker: "CAT",
    entryDate: "2026-06-11",
    exitDate: "2026-06-16",
    entryPrice: 890.34,
    exitPrice: 956.72,
    accountValueAtEntry: 2405.49,
    positionDollars: 530.0,
    conviction: 3,
    setupType: "bounce",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "vrtx-2026-06-17",
    ticker: "VRTX",
    entryDate: "2026-06-17",
    exitDate: "2026-06-18",
    entryPrice: 458.99,
    exitPrice: 452.66,
    accountValueAtEntry: 2522.53,
    positionDollars: 917.0,
    conviction: 4,
    setupType: "bounce",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "sndk-2026-06-17",
    ticker: "SNDK",
    entryDate: "2026-06-17",
    exitDate: "2026-06-18",
    entryPrice: 1999.6,
    exitPrice: 2158.2,
    accountValueAtEntry: 2522.53,
    positionDollars: 700.0,
    conviction: 2,
    setupType: "bounce",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
  {
    id: "fix-2026-06-17",
    ticker: "FIX",
    entryDate: "2026-06-17",
    exitDate: "2026-06-18",
    entryPrice: 1955.58,
    exitPrice: 1965.52,
    accountValueAtEntry: 2522.53,
    positionDollars: 800.0,
    conviction: 2,
    setupType: "bounce",
    scaledInOut: false,
    followedRules: true,
    notes: "",
  },
];

/* ───────────────────────── MATH / FORMULAS ───────────────────────── */

const daysBetween = (d1, d2) =>
  Math.max(1, Math.round((new Date(d2) - new Date(d1)) / 86400000));

const tradeReturnPct = (t) => ((t.exitPrice - t.entryPrice) / t.entryPrice) * 100;
const positionSizePct = (t) => (t.positionDollars / t.accountValueAtEntry) * 100;
const accountImpactPct = (t) =>
  tradeReturnPct(t) * (t.positionDollars / t.accountValueAtEntry);
const holdDays = (t) => daysBetween(t.entryDate, t.exitDate);

const sortByEntry = (trades) =>
  [...trades].sort((a, b) => new Date(a.entryDate) - new Date(b.entryDate));

// SPY cache: { [dateStr]: price }
const SPY_CACHE_KEY = 'ledger:spy_cache';

// Sidecar base — the Python/SQLite backend the Tauri app spawns.
const SIDECAR = 'http://127.0.0.1:8765';

function getNeededSpyDates(trades) {
  if (!trades.length) return [];
  const sorted = sortByEntry(trades);
  const dates = new Set([sorted[0].entryDate]);
  sorted.forEach((t) => dates.add(t.exitDate));
  return Array.from(dates);
}

async function kvGet(key) {
  try {
    const res = await fetch(`${SIDECAR}/ledger/kv/get`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    const data = await res.json();
    return data.value ?? null;
  } catch (e) {
    return null;
  }
}

async function kvSet(key, value) {
  try {
    await fetch(`${SIDECAR}/ledger/kv/set`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value }),
    });
    return true;
  } catch (e) {
    return false;
  }
}

async function loadSpyCache() {
  const v = await kvGet(SPY_CACHE_KEY);
  if (v) {
    try { return JSON.parse(v); } catch (e) {}
  }
  return {};
}

async function saveSpyCache(cache) {
  await kvSet(SPY_CACHE_KEY, JSON.stringify(cache));
}

function computeStats(trades) {
  if (!trades.length) return null;
  const returns = trades.map(tradeReturnPct);
  const wins = returns.filter((r) => r > 0);
  const losses = returns.filter((r) => r < 0);
  const breakevens = returns.filter((r) => r === 0);
  const n = trades.length;
  const winRate = wins.length / n;
  const lossRate = losses.length / n;
  const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
  const avgLoss = losses.length
    ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length)
    : 0;
  const expectancy = winRate * avgWin - lossRate * avgLoss;
  const grossWin = wins.reduce((a, b) => a + b, 0);
  const grossLoss = Math.abs(losses.reduce((a, b) => a + b, 0));
  const profitFactor = grossLoss === 0 ? (grossWin > 0 ? Infinity : 0) : grossWin / grossLoss;
  // Kelly f* = p - q/b where b = avgWin/avgLoss
  const b = avgLoss === 0 ? Infinity : avgWin / avgLoss;
  const kelly = b === Infinity ? 1 : winRate - lossRate / b;
  const avgHold = trades.reduce((a, t) => a + holdDays(t), 0) / n;
  const expectancyPerDay = avgHold > 0 ? expectancy / avgHold : 0;

  // Rule followed vs broken — all trades
  const ruleFollowed = trades.filter((t) => t.followedRules).length;
  const ruleBroken = trades.length - ruleFollowed;

  return {
    n,
    winCount: wins.length,
    lossCount: losses.length,
    beCount: breakevens.length,
    winRate,
    lossRate,
    avgWin,
    avgLoss,
    expectancy,
    profitFactor,
    kelly,
    avgHold,
    expectancyPerDay,
    ruleFollowed,
    ruleBroken,
  };
}

// Equity curve — start at 100, compound by account-impact of each trade
// Also overlay SPY buy-and-hold from first entry date, normalized to 100
function computeEquityCurve(trades, spyCache = {}) {
  const sorted = sortByEntry(trades);
  if (!sorted.length) return [];
  const startDate = sorted[0].entryDate;
  const spyStart = spyCache[startDate] || null;

  const pts = [
    {
      idx: 0,
      label: 'Start',
      date: startDate,
      equity: 100,
      spy: spyStart ? 100 : null,
      ticker: null,
    },
  ];
  let eq = 100;
  sorted.forEach((t, i) => {
    eq = eq * (1 + accountImpactPct(t) / 100);
    const spyPrice = spyCache[t.exitDate] || null;
    const spy = spyStart && spyPrice ? 100 * (spyPrice / spyStart) : null;
    pts.push({
      idx: i + 1,
      label: `${i + 1}`,
      date: t.exitDate,
      equity: eq,
      spy,
      ticker: t.ticker,
      impact: accountImpactPct(t),
    });
  });
  return pts;
}

// Raw excess return vs SPY = final strategy equity - final SPY equity (points).
//
// This used to be called "Alpha". It is not alpha: no beta adjustment, and it
// compares a partially-deployed book against a fully-invested benchmark. It is
// kept, honestly named, as context beside the real figure — real Jensen alpha
// needs per-ticker betas and is computed by the sidecar (engine/alpha.py,
// POST /ledger/alpha).
function computeExcessVsSpy(curve) {
  if (!curve.length) return null;
  const last = curve[curve.length - 1];
  if (last.spy === null || last.spy === undefined) return null;
  return last.equity - last.spy;
}

// R² of equity curve vs linear fit
function computeR2(curve) {
  if (curve.length < 3) return null;
  const xs = curve.map((_, i) => i);
  const ys = curve.map((p) => p.equity);
  const meanX = xs.reduce((a, b) => a + b, 0) / xs.length;
  const meanY = ys.reduce((a, b) => a + b, 0) / ys.length;
  let num = 0, denX = 0, denY = 0;
  xs.forEach((x, i) => {
    num += (x - meanX) * (ys[i] - meanY);
    denX += (x - meanX) ** 2;
    denY += (ys[i] - meanY) ** 2;
  });
  const slope = num / denX;
  const intercept = meanY - slope * meanX;
  let ssRes = 0, ssTot = 0;
  ys.forEach((y, i) => {
    const pred = slope * xs[i] + intercept;
    ssRes += (y - pred) ** 2;
    ssTot += (y - meanY) ** 2;
  });
  if (ssTot === 0) return 1;
  return 1 - ssRes / ssTot;
}

// Max drawdown of an equity curve (as % from peak)
function maxDrawdown(equitySeries) {
  let peak = equitySeries[0];
  let maxDD = 0;
  for (const v of equitySeries) {
    if (v > peak) peak = v;
    const dd = (peak - v) / peak;
    if (dd > maxDD) maxDD = dd;
  }
  return maxDD * 100;
}

// Longest losing streak from array of returns
function longestLosingStreak(returns) {
  let max = 0, cur = 0;
  for (const r of returns) {
    if (r < 0) {
      cur++;
      if (cur > max) max = cur;
    } else cur = 0;
  }
  return max;
}

// Monte Carlo: bootstrap from historical trade account-impacts
function monteCarloSim(trades, simCount = 1000, futureTrades = 50) {
  if (trades.length < 2) return null;
  const impacts = trades.map(accountImpactPct); // use account-impact for equity
  const returnsOnly = trades.map(tradeReturnPct); // for losing streaks
  const results = [];
  for (let s = 0; s < simCount; s++) {
    let eq = 100;
    const eqSeries = [100];
    const rets = [];
    for (let i = 0; i < futureTrades; i++) {
      const idx = Math.floor(Math.random() * impacts.length);
      eq = eq * (1 + impacts[idx] / 100);
      eqSeries.push(eq);
      rets.push(returnsOnly[idx]);
    }
    results.push({
      final: eq,
      maxDD: maxDrawdown(eqSeries),
      losingStreak: longestLosingStreak(rets),
      series: eqSeries,
    });
  }
  // Percentile bands at each step
  const bands = [];
  for (let i = 0; i <= futureTrades; i++) {
    const slice = results.map((r) => r.series[i]).sort((a, b) => a - b);
    bands.push({
      idx: i,
      p5: slice[Math.floor(simCount * 0.05)],
      p25: slice[Math.floor(simCount * 0.25)],
      p50: slice[Math.floor(simCount * 0.5)],
      p75: slice[Math.floor(simCount * 0.75)],
      p95: slice[Math.floor(simCount * 0.95)],
    });
  }
  const finals = results.map((r) => r.final).sort((a, b) => a - b);
  const dds = results.map((r) => r.maxDD).sort((a, b) => a - b);
  const streaks = results.map((r) => r.losingStreak).sort((a, b) => a - b);
  const pct = (arr, p) => arr[Math.floor(arr.length * p)];
  return {
    bands,
    futureTrades,
    finalMedian: pct(finals, 0.5),
    finalP5: pct(finals, 0.05),
    finalP95: pct(finals, 0.95),
    ddMedian: pct(dds, 0.5),
    ddP95: pct(dds, 0.95),
    streakMedian: pct(streaks, 0.5),
    streakP95: pct(streaks, 0.95),
    ruinProb: finals.filter((f) => f < 50).length / simCount,
  };
}

// Conviction buckets: avg return per conviction level
function computeConvictionBuckets(trades) {
  const map = {};
  for (let i = 1; i <= 5; i++) map[i] = [];
  trades.forEach((t) => map[t.conviction].push(tradeReturnPct(t)));
  return Object.entries(map).map(([c, rs]) => ({
    conviction: Number(c),
    count: rs.length,
    avgReturn: rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : 0,
  }));
}

// SQN (System Quality Number) — Van Tharp
// SQN = (mean / stdDev) × √N, with N capped at 100.
//
// Two corrections against the earlier version, both of which changed the grade:
//
//  1. Account impact, not raw price return. Tharp defines SQN over R-multiples,
//     i.e. it is position-sizing aware. Using tradeReturnPct scored a position
//     worth 0.1% of the account identically to one worth 50% — the exact
//     distinction SQN exists to make. accountImpactPct is the sizing-aware
//     quantity this file already uses for the equity curve and Monte Carlo, so
//     this also makes the dashboard internally consistent.
//
//  2. N capped at 100, per Tharp. Without the cap √N grows without bound, so an
//     UNCHANGED edge scored 1.91 ("Below average") over 100 trades and 5.44
//     ("Superb") over 800 — the grade became a function of how much you traded
//     rather than how well. The bands in sqnGrade() are Tharp's and assume the
//     cap, so omitting it mis-grades every sample past 100.
const SQN_N_CAP = 100;

function computeSQN(trades) {
  if (trades.length < 2) return null;
  const impacts = trades.map(accountImpactPct);
  const n = impacts.length;
  const mean = impacts.reduce((a, b) => a + b, 0) / n;
  const variance = impacts.reduce((a, r) => a + (r - mean) ** 2, 0) / (n - 1);
  const stdDev = Math.sqrt(variance);
  if (stdDev === 0) return null;
  return (mean / stdDev) * Math.sqrt(Math.min(n, SQN_N_CAP));
}

function sqnGrade(sqn) {
  if (sqn === null || sqn === undefined || isNaN(sqn))
    return { label: 'Not enough data', tone: 'neutral', short: '—' };
  if (sqn < 1.6) return { label: 'Poor', tone: 'crimson', short: 'Poor' };
  if (sqn < 2.0) return { label: 'Below average', tone: 'crimson', short: 'Below avg' };
  if (sqn < 2.5) return { label: 'Average', tone: 'neutral', short: 'Average' };
  if (sqn < 3.0) return { label: 'Good', tone: 'emerald', short: 'Good' };
  if (sqn < 5.0) return { label: 'Excellent', tone: 'emerald', short: 'Excellent' };
  return { label: 'Superb (check sample)', tone: 'gold', short: 'Superb*' };
}

function sqnSampleConfidence(n) {
  if (n < 20) return 'Too few trades — SQN unreliable';
  if (n < 30) return 'Thin sample — directional only';
  if (n < 50) return 'Moderate confidence';
  if (n < 100) return 'Good confidence';
  return 'High confidence';
}

// Break-even win rate: what win rate you need given your avgWin/avgLoss to not lose money
// Solve: w × avgWin = (1 - w) × avgLoss → w = avgLoss / (avgWin + avgLoss)
function computeBreakEvenWinRate(stats) {
  if (!stats || stats.avgWin === 0 || stats.avgLoss === 0) return null;
  return stats.avgLoss / (stats.avgWin + stats.avgLoss);
}

// Rolling expectancy over a sliding window of N trades
function computeRollingExpectancy(trades, windowSize = 10) {
  if (trades.length < 2) return [];
  const sorted = sortByEntry(trades);
  const actualWindow = Math.min(windowSize, sorted.length);
  const points = [];
  for (let i = actualWindow - 1; i < sorted.length; i++) {
    const slice = sorted.slice(i - actualWindow + 1, i + 1);
    const returns = slice.map(tradeReturnPct);
    const wins = returns.filter((r) => r > 0);
    const losses = returns.filter((r) => r < 0);
    const winRate = wins.length / slice.length;
    const lossRate = losses.length / slice.length;
    const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
    const avgLoss = losses.length
      ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length)
      : 0;
    const expectancy = winRate * avgWin - lossRate * avgLoss;
    points.push({
      tradeNum: i + 1,
      expectancy,
      ticker: sorted[i].ticker,
    });
  }
  return { points, windowSize: actualWindow };
}

// Setup type breakdown: avg return and win rate per setup type
function computeSetupTypeBuckets(trades) {
  const types = ['bounce', 'breakout', 'dip_buy'];
  const labels = { bounce: 'Bounce', breakout: 'Breakout', dip_buy: 'Dip Buy' };
  return types.map((type) => {
    const filtered = trades.filter((t) => t.setupType === type);
    const returns = filtered.map(tradeReturnPct);
    const wins = returns.filter((r) => r > 0);
    const losses = returns.filter((r) => r < 0);
    const avgReturn = returns.length
      ? returns.reduce((a, b) => a + b, 0) / returns.length
      : 0;
    const winRate = returns.length
      ? wins.length / returns.length
      : 0;
    const expectancy = returns.length
      ? (wins.length / returns.length) * (wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0) -
        (losses.length / returns.length) * (losses.length ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length) : 0)
      : 0;
    return {
      type,
      label: labels[type],
      count: filtered.length,
      avgReturn,
      winRate,
      expectancy,
    };
  });
}

// Duration distribution: bucket trades by hold duration, compute avg return per bucket
function computeDurationBuckets(trades) {
  const buckets = [
    { label: '1d', min: 0, max: 1, trades: [] },
    { label: '2d', min: 2, max: 2, trades: [] },
    { label: '3-5d', min: 3, max: 5, trades: [] },
    { label: '6d+', min: 6, max: Infinity, trades: [] },
  ];
  trades.forEach((t) => {
    const d = holdDays(t);
    const bucket = buckets.find((b) => d >= b.min && d <= b.max);
    if (bucket) bucket.trades.push(t);
  });
  return buckets.map((b) => {
    const returns = b.trades.map(tradeReturnPct);
    const avgReturn = returns.length
      ? returns.reduce((a, c) => a + c, 0) / returns.length
      : 0;
    const winRate = returns.length
      ? returns.filter((r) => r > 0).length / returns.length
      : 0;
    return {
      label: b.label,
      count: b.trades.length,
      avgReturn,
      winRate,
    };
  });
}

// Monthly equity breakdown: net account-impact per calendar month
function computeMonthlyBreakdown(trades) {
  if (!trades.length) return [];
  const sorted = sortByEntry(trades);
  const monthMap = {};
  sorted.forEach((t) => {
    const month = t.exitDate.slice(0, 7); // YYYY-MM
    if (!monthMap[month]) monthMap[month] = { month, impact: 0, count: 0, wins: 0, losses: 0 };
    const imp = accountImpactPct(t);
    monthMap[month].impact += imp;
    monthMap[month].count += 1;
    if (tradeReturnPct(t) > 0) monthMap[month].wins += 1;
    else if (tradeReturnPct(t) < 0) monthMap[month].losses += 1;
  });
  return Object.values(monthMap).sort((a, b) => a.month.localeCompare(b.month));
}

// Rules-split expectancy: separate expectancy for rules-followed vs rules-broken trades
function computeRulesSplitExpectancy(trades) {
  const followed = trades.filter((t) => t.followedRules);
  const broken = trades.filter((t) => !t.followedRules);

  const computeExp = (arr) => {
    if (!arr.length) return null;
    const returns = arr.map(tradeReturnPct);
    const wins = returns.filter((r) => r > 0);
    const losses = returns.filter((r) => r < 0);
    const winRate = wins.length / arr.length;
    const lossRate = losses.length / arr.length;
    const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
    const avgLoss = losses.length
      ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length)
      : 0;
    return {
      count: arr.length,
      expectancy: winRate * avgWin - lossRate * avgLoss,
      winRate,
      avgWin,
      avgLoss,
    };
  };

  return {
    followed: computeExp(followed),
    broken: computeExp(broken),
  };
}

// Cumulative win rate over time — after each trade, what's the running WR?
// Also tracks running break-even WR as a reference line
function computeCumulativeWinRate(trades) {
  const sorted = sortByEntry(trades);
  if (!sorted.length) return [];
  let wins = 0;
  const points = [];
  sorted.forEach((t, i) => {
    if (tradeReturnPct(t) > 0) wins += 1;
    const wr = wins / (i + 1);

    // Running break-even WR at this point
    const slice = sorted.slice(0, i + 1);
    const sliceReturns = slice.map(tradeReturnPct);
    const sliceWins = sliceReturns.filter((r) => r > 0);
    const sliceLosses = sliceReturns.filter((r) => r < 0);
    const avgW = sliceWins.length ? sliceWins.reduce((a, b) => a + b, 0) / sliceWins.length : 0;
    const avgL = sliceLosses.length ? Math.abs(sliceLosses.reduce((a, b) => a + b, 0) / sliceLosses.length) : 0;
    const beWR = avgW + avgL > 0 ? avgL / (avgW + avgL) : null;

    points.push({
      tradeNum: i + 1,
      winRate: wr * 100,
      breakEven: beWR !== null ? beWR * 100 : null,
      ticker: t.ticker,
      margin: beWR !== null ? (wr - beWR) * 100 : null,
    });
  });
  return points;
}

// Weighted average price from tranches
function computeWeightedAvg(tranches) {
  if (!tranches || !tranches.length) return null;
  let totalDollars = 0;
  let totalShares = 0;
  tranches.forEach((t) => {
    const shares = t.dollars / t.price;
    totalDollars += t.dollars;
    totalShares += shares;
  });
  if (totalShares === 0) return null;
  return {
    avgPrice: totalDollars / totalShares,
    totalDollars,
    totalShares,
  };
}

/* ───────────────────────── STORAGE ───────────────────────── */

const STORAGE_KEY = 'ledger:trades';
const SEEDED_FLAG_KEY = 'ledger:seeded';

async function loadTrades() {
  try {
    const res = await fetch(`${SIDECAR}/ledger/trades`);
    const data = await res.json();
    // Backend returns null when the table was never initialized (so the app
    // knows to seed demo data), or an array (possibly empty) otherwise.
    return data.trades;
  } catch (e) {
    return null;
  }
}

async function saveTrades(trades) {
  try {
    await fetch(`${SIDECAR}/ledger/trades`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trades }),
    });
    return true;
  } catch (e) {
    return false;
  }
}

async function checkSeeded() {
  const v = await kvGet(SEEDED_FLAG_KEY);
  return !!v;
}

async function markSeeded() {
  await kvSet(SEEDED_FLAG_KEY, 'true');
}

/* ───────────────── ACCOUNT SNAPSHOTS ───────────────── */

const SNAPSHOTS_KEY = 'ledger:snapshots';

async function loadSnapshots() {
  const v = await kvGet(SNAPSHOTS_KEY);
  if (v) {
    try { return JSON.parse(v); } catch (e) {}
  }
  return [];
}

async function saveSnapshots(snapshots) {
  return await kvSet(SNAPSHOTS_KEY, JSON.stringify(snapshots));
}

// Compute the suggested account value for a new trade being entered on `onDate`.
// Rolls forward from the latest snapshot (or earliest trade if no snapshot) by applying
// each closed trade's dollar P&L. This is an approximation — positions open concurrently
// aren't reflected — but it's close enough for % return math if the user periodically
// snapshots the real value.
function suggestedAccountValue(trades, snapshots, onDate = null) {
  const cutoff = onDate ? new Date(onDate) : new Date();
  // Find the latest snapshot on or before cutoff
  const validSnapshots = snapshots
    .filter((s) => new Date(s.date) <= cutoff)
    .sort((a, b) => new Date(b.date) - new Date(a.date));
  let baseValue, baseDate;
  if (validSnapshots.length) {
    baseValue = validSnapshots[0].value;
    baseDate = validSnapshots[0].date;
  } else if (trades.length) {
    // Fall back to earliest trade's account value
    const earliest = [...trades].sort(
      (a, b) => new Date(a.entryDate) - new Date(b.entryDate)
    )[0];
    baseValue = earliest.accountValueAtEntry;
    baseDate = earliest.entryDate;
  } else {
    return null;
  }
  // Apply dollar P&L of all trades that exited AFTER baseDate and BEFORE/ON cutoff
  const applicable = trades.filter((t) => {
    const exit = new Date(t.exitDate);
    return exit > new Date(baseDate) && exit <= cutoff;
  });
  let value = baseValue;
  applicable.forEach((t) => {
    const dollarPnL = t.positionDollars * (tradeReturnPct(t) / 100);
    value += dollarPnL;
  });
  return value;
}

/* ───────────────────────── SPY AUTO-FETCH ───────────────────────── */

// Exact SPY closing price for a date, via the sidecar's yfinance lookup.
// Replaces the original web-search approach: official closes, instant, free,
// and it resolves weekends/holidays to the prior trading day server-side.
async function fetchSpyPrice(date) {
  try {
    const res = await fetch(`${SIDECAR}/ledger/spy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dates: [date] }),
    });
    const data = await res.json();
    const price = data.prices?.[date];
    if (typeof price === 'number' && price >= 100 && price <= 2000) return price;
  } catch (e) {}
  return null;
}

/* ───────────────────────── UI HELPERS ───────────────────────── */

const fmtPct = (n, decimals = 2) =>
  n === null || n === undefined || isNaN(n)
    ? '—'
    : `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`;

const fmtNum = (n, decimals = 2) =>
  n === null || n === undefined || isNaN(n)
    ? '—'
    : n === Infinity
    ? '∞'
    : n.toFixed(decimals);

const fmtMoney = (n) =>
  n === null || n === undefined || isNaN(n) ? '—' : `$${n.toFixed(2)}`;

const colorForReturn = (r) => (r > 0 ? 'text-emerald' : r < 0 ? 'text-crimson' : 'text-stone');

/* ───────────────────────── MAIN APP ───────────────────────── */

export default function Ledger() {
  const [view, setView] = useState('dashboard'); // dashboard | trades | form
  const [trades, setTrades] = useState([]);
  const [editingTrade, setEditingTrade] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [spyCache, setSpyCache] = useState({});
  const [spyLoading, setSpyLoading] = useState(false);
  const [spyError, setSpyError] = useState(null);
  const [snapshots, setSnapshots] = useState([]);
  const [showSnapshotModal, setShowSnapshotModal] = useState(false);

  // Fetch missing SPY dates, update cache + persist
  // Also invalidates any cached values that are outside SPY's plausible price range
  const syncSpyData = async (currentTrades, force = false) => {
    const needed = getNeededSpyDates(currentTrades);
    if (!needed.length) return;
    const currentCache = await loadSpyCache();

    // Invalidate clearly-wrong cached values (e.g., a year like 2026 got stored)
    const isPlausibleSpyPrice = (v) =>
      typeof v === 'number' && !isNaN(v) && v >= 100 && v <= 2000;
    const cleanedCache = {};
    Object.entries(currentCache).forEach(([date, val]) => {
      if (isPlausibleSpyPrice(val)) cleanedCache[date] = val;
    });

    const missing = force
      ? needed
      : needed.filter((d) => !(d in cleanedCache));
    if (!missing.length) {
      setSpyCache(cleanedCache);
      if (Object.keys(cleanedCache).length !== Object.keys(currentCache).length) {
        await saveSpyCache(cleanedCache);
      }
      return;
    }
    setSpyLoading(true);
    setSpyError(null);
    try {
      const results = await Promise.all(
        missing.map(async (date) => {
          const price = await fetchSpyPrice(date);
          return [date, price];
        })
      );
      const newCache = { ...cleanedCache };
      let anyFailed = false;
      results.forEach(([date, price]) => {
        if (isPlausibleSpyPrice(price)) newCache[date] = price;
        else anyFailed = true;
      });
      await saveSpyCache(newCache);
      setSpyCache(newCache);
      if (anyFailed) setSpyError('Some SPY dates could not be fetched');
    } catch (e) {
      setSpyError('SPY fetch failed');
    } finally {
      setSpyLoading(false);
    }
  };

  useEffect(() => {
    (async () => {
      const existing = await loadTrades();
      const seeded = await checkSeeded();
      let initialTrades;
      if (existing) {
        initialTrades = existing;
      } else if (!seeded) {
        initialTrades = SEED_TRADES;
        await saveTrades(SEED_TRADES);
        await markSeeded();
      } else {
        initialTrades = [];
      }

      // One-time IV backfill for historical trades logged before the IV field
      // existed. Canonical IVs taken from the user's most recent Luck Check
      // screenshot. Matches by ticker; only fills trades that have no iv yet,
      // so it never overwrites anything you've entered. CAT defaults to 43 for
      // all three CAT trades — correct any that differ by editing the trade.
      const IV_BACKFILL = {
        MU: 93, CAT: 43, VRTX: 27, SNDK: 111,
        FIX: 71, GLW: 96, SO: 20,
      };
      let backfilled = false;
      initialTrades = initialTrades.map((t) => {
        if ((t.iv == null || t.iv === '') && IV_BACKFILL[t.ticker] != null) {
          backfilled = true;
          return { ...t, iv: IV_BACKFILL[t.ticker] };
        }
        return t;
      });
      if (backfilled) {
        await saveTrades(initialTrades);
      }

      setTrades(initialTrades);
      const cache = await loadSpyCache();
      setSpyCache(cache);
      const snaps = await loadSnapshots();
      setSnapshots(snaps);
      setLoading(false);
      // Fire-and-forget sync
      syncSpyData(initialTrades);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persist = async (newTrades) => {
    setTrades(newTrades);
    await saveTrades(newTrades);
    syncSpyData(newTrades);
  };

  const upsertTrade = async (trade) => {
    const exists = trades.find((t) => t.id === trade.id);
    const next = exists
      ? trades.map((t) => (t.id === trade.id ? trade : t))
      : [...trades, trade];
    await persist(next);
    setEditingTrade(null);
    setView('trades');
  };

  const deleteTrade = async (id) => {
    await persist(trades.filter((t) => t.id !== id));
    setConfirmDelete(null);
  };

  const addSnapshot = async (date, value) => {
    const newSnap = {
      id: `snap-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      date,
      value: Number(value),
      createdAt: new Date().toISOString(),
    };
    const next = [...snapshots, newSnap].sort(
      (a, b) => new Date(a.date) - new Date(b.date)
    );
    setSnapshots(next);
    await saveSnapshots(next);
    setShowSnapshotModal(false);
  };

  const deleteSnapshot = async (id) => {
    const next = snapshots.filter((s) => s.id !== id);
    setSnapshots(next);
    await saveSnapshots(next);
  };

  const stats = useMemo(() => computeStats(trades), [trades]);
  const curve = useMemo(() => computeEquityCurve(trades, spyCache), [trades, spyCache]);
  const excessVsSpy = useMemo(() => computeExcessVsSpy(curve), [curve]);
  const r2 = useMemo(() => computeR2(curve), [curve]);
  const mc = useMemo(() => monteCarloSim(trades, 1000, 50), [trades]);
  const convictionBuckets = useMemo(() => computeConvictionBuckets(trades), [trades]);
  const sqn = useMemo(() => computeSQN(trades), [trades]);
  const breakEvenWR = useMemo(() => computeBreakEvenWinRate(stats), [stats]);
  const rollingExp = useMemo(() => computeRollingExpectancy(trades, 10), [trades]);
  const durationBuckets = useMemo(() => computeDurationBuckets(trades), [trades]);
  const monthlyBreakdown = useMemo(() => computeMonthlyBreakdown(trades), [trades]);
  const rulesSplit = useMemo(() => computeRulesSplitExpectancy(trades), [trades]);
  const cumulativeWR = useMemo(() => computeCumulativeWinRate(trades), [trades]);
  const setupBuckets = useMemo(() => computeSetupTypeBuckets(trades), [trades]);

  // Real Jensen alpha comes from the sidecar: it needs a per-ticker beta vs SPY,
  // which the frontend has no price history to estimate. Recomputed whenever the
  // trade set changes. A failure surfaces as text rather than a blank stat, so a
  // dead sidecar can't masquerade as "no alpha".
  const [alphaResult, setAlphaResult] = useState(null);
  const [alphaLoading, setAlphaLoading] = useState(false);
  const [alphaError, setAlphaError] = useState(null);

  useEffect(() => {
    const closed = trades.filter((t) => t.exitDate && t.exitPrice);
    if (!closed.length) {
      setAlphaResult(null);
      setAlphaError(null);
      return;
    }
    let cancelled = false;
    setAlphaLoading(true);
    setAlphaError(null);
    fetch(`${SIDECAR}/ledger/alpha`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trades: closed }),
    })
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok) throw new Error(body?.detail || `alpha failed: ${res.status}`);
        return body;
      })
      .then((a) => {
        if (!cancelled) setAlphaResult(a);
      })
      .catch((e) => {
        if (cancelled) return;
        setAlphaResult(null);
        setAlphaError(String(e?.message || e));
      })
      .finally(() => {
        if (!cancelled) setAlphaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [trades]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-ink text-bone font-body">
        <div className="animate-pulse text-stone">Loading ledger...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-ink text-bone font-body antialiased">
      <StyleSheet />

      <Header
        view={view}
        setView={setView}
        onNew={() => {
          setEditingTrade(null);
          setView('form');
        }}
        tradeCount={trades.length}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-8 py-8 pb-24">
        {view === 'dashboard' && (
          <Dashboard
            trades={trades}
            stats={stats}
            curve={curve}
            r2={r2}
            mc={mc}
            convictionBuckets={convictionBuckets}
            excessVsSpy={excessVsSpy}
            alphaResult={alphaResult}
            alphaLoading={alphaLoading}
            alphaError={alphaError}
            spyLoading={spyLoading}
            spyError={spyError}
            onRefreshSpy={() => syncSpyData(trades, true)}
            sqn={sqn}
            breakEvenWR={breakEvenWR}
            rollingExp={rollingExp}
            snapshots={snapshots}
            currentAccountValue={suggestedAccountValue(trades, snapshots)}
            onOpenSnapshot={() => setShowSnapshotModal(true)}
            onDeleteSnapshot={deleteSnapshot}
            durationBuckets={durationBuckets}
            monthlyBreakdown={monthlyBreakdown}
            rulesSplit={rulesSplit}
            cumulativeWR={cumulativeWR}
            setupBuckets={setupBuckets}
          />
        )}
        {view === 'trades' && (
          <TradesList
            trades={trades}
            onEdit={(t) => {
              setEditingTrade(t);
              setView('form');
            }}
            onDelete={(id) => setConfirmDelete(id)}
            onNew={() => {
              setEditingTrade(null);
              setView('form');
            }}
          />
        )}
        {view === 'form' && (
          <TradeForm
            trade={editingTrade}
            onSave={upsertTrade}
            onCancel={() => {
              setEditingTrade(null);
              setView(trades.length ? 'trades' : 'dashboard');
            }}
            suggestedValue={(onDate) => suggestedAccountValue(trades, snapshots, onDate)}
          />
        )}
      </main>

      {confirmDelete && (
        <ConfirmModal
          title="Delete trade?"
          message="This cannot be undone."
          onConfirm={() => deleteTrade(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}

      {showSnapshotModal && (
        <SnapshotModal
          snapshots={snapshots}
          onAdd={addSnapshot}
          onDelete={deleteSnapshot}
          onClose={() => setShowSnapshotModal(false)}
          suggestedValue={suggestedAccountValue(trades, snapshots)}
        />
      )}
    </div>
  );
}

/* ───────────────────────── STYLE SHEET ───────────────────────── */

function StyleSheet() {
  return (
    <style>{`
      @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

      :root {
        --ink: #0f1216;
        --ink-soft: #14181d;
        --ink-card: #1a1c1f;
        --ink-raised: #212326;
        --bone: #e7eaee;
        --bone-dim: #aab1ba;
        --stone: #6b7480;
        --emerald: #6fb89e;
        --emerald-dim: #3d6b5a;
        --crimson: #c78a73;
        --crimson-dim: #8a4a3c;
        --gold: #4db8c4;
        --gold-dim: #3a8c95;
        --rule: #2a313a;
      }

      body { margin: 0; }
      .font-body { font-family: 'Geist', ui-sans-serif, system-ui, sans-serif; font-feature-settings: 'ss01', 'cv11'; }
      .font-display { font-family: 'Fraunces', serif; font-feature-settings: 'ss01'; letter-spacing: -0.01em; }
      .font-mono { font-family: 'JetBrains Mono', ui-monospace, monospace; font-feature-settings: 'tnum'; }

      .bg-ink { background-color: var(--ink); }
      .bg-ink-soft { background-color: var(--ink-soft); }
      .bg-ink-card { background-color: var(--ink-card); }
      .bg-ink-raised { background-color: var(--ink-raised); }
      .text-bone { color: var(--bone); }
      .text-bone-dim { color: var(--bone-dim); }
      .text-stone { color: var(--stone); }
      .text-emerald { color: var(--emerald); }
      .text-crimson { color: var(--crimson); }
      .text-gold { color: var(--gold); }
      .bg-emerald-dim { background-color: var(--emerald-dim); }
      .bg-crimson-dim { background-color: var(--crimson-dim); }
      .bg-gold-dim { background-color: var(--gold-dim); }
      .bg-emerald { background-color: var(--emerald); }
      .bg-crimson { background-color: var(--crimson); }
      .bg-gold { background-color: var(--gold); }
      .border-rule { border-color: var(--rule); }

      .card {
        background: var(--ink-card);
        border: 1px solid var(--rule);
        border-radius: 6px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15), 0 1px 2px rgba(0, 0, 0, 0.1);
      }
      .card-raised {
        background: var(--ink-raised);
        border: 1px solid var(--rule);
        border-radius: 6px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15), 0 1px 2px rgba(0, 0, 0, 0.1);
      }

      .btn-primary {
        background: var(--bone);
        color: var(--ink);
        font-weight: 500;
        padding: 0.55rem 1.1rem;
        border-radius: 4px;
        transition: all 0.2s ease;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
      }
      .btn-primary:hover { opacity: 0.92; transform: translateY(-0.5px); box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25); }
      .btn-primary:active { transform: translateY(0); }
      .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }

      .btn-ghost {
        color: var(--bone-dim);
        padding: 0.5rem 1rem;
        border-radius: 4px;
        transition: all 0.2s ease;
      }
      .btn-ghost:hover { color: var(--bone); background: var(--ink-raised); }

      .btn-tab {
        color: var(--stone);
        padding: 0.5rem 0;
        border-bottom: 2px solid transparent;
        transition: all 0.25s ease;
        font-size: 0.8rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .btn-tab:hover { color: var(--bone-dim); }
      .btn-tab-active {
        color: var(--bone);
        border-bottom-color: var(--gold);
      }

      .input {
        background: var(--ink-soft);
        border: 1px solid var(--rule);
        color: var(--bone);
        padding: 0.65rem 0.85rem;
        border-radius: 4px;
        width: 100%;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.9rem;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
      }
      .input:focus { outline: none; border-color: var(--gold-dim); box-shadow: 0 0 0 2px rgba(77, 184, 196, 0.12); }
      .input::placeholder { color: var(--stone); }

      .label-field {
        font-size: 0.7rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--stone);
        margin-bottom: 0.45rem;
        display: block;
      }

      .chip {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        font-size: 0.7rem;
        letter-spacing: 0.06em;
        font-family: 'JetBrains Mono', monospace;
        border: 1px solid var(--rule);
      }

      .hairline { height: 1px; background: var(--rule); }

      .header-blur { background: linear-gradient(180deg, rgba(16, 17, 20, 0.97) 0%, rgba(16, 17, 20, 0.92) 100%); }
      .modal-overlay { background-color: rgba(10, 10, 12, 0.82); }
      .row-hover:hover { background-color: rgba(22, 24, 25, 0.6); }
      .divide-rule > * + * { border-top: 1px solid var(--rule); }

      .stat-value { font-family: 'Fraunces', serif; font-weight: 400; letter-spacing: -0.02em; }

      .recharts-tooltip-wrapper { outline: none; }
      .recharts-cartesian-axis-tick text { fill: var(--stone); font-family: 'JetBrains Mono', monospace; font-size: 11px; }

      /* Hide number input spinners */
      input[type=number]::-webkit-inner-spin-button,
      input[type=number]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
      input[type=number] { -moz-appearance: textfield; }

      /* Scrollbar styling */
      ::-webkit-scrollbar { width: 6px; height: 6px; }
      ::-webkit-scrollbar-track { background: var(--ink); }
      ::-webkit-scrollbar-thumb { background: var(--rule); border-radius: 3px; }
      ::-webkit-scrollbar-thumb:hover { background: var(--stone); }

      @media (max-width: 640px) {
        .stat-value-lg { font-size: 2rem !important; }
      }
    `}</style>
  );
}

/* ───────────────────────── HEADER ───────────────────────── */

function Header({ view, setView, onNew, tradeCount }) {
  return (
    <header className="border-b border-rule sticky top-0 header-blur backdrop-blur-sm z-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-8 py-5 flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-display text-3xl text-bone tracking-tight">Ledger</h1>
          <span className="font-mono text-[10px] text-stone tracking-widest uppercase">
            v1 · {tradeCount} {tradeCount === 1 ? 'trade' : 'trades'}
          </span>
        </div>

        <nav className="flex items-center gap-6 sm:gap-8">
          <button
            onClick={() => setView('dashboard')}
            className={`btn-tab ${view === 'dashboard' ? 'btn-tab-active' : ''}`}
          >
            Dashboard
          </button>
          <button
            onClick={() => setView('trades')}
            className={`btn-tab ${view === 'trades' ? 'btn-tab-active' : ''}`}
          >
            Trades
          </button>
          <button
            onClick={onNew}
            className="flex items-center gap-1.5 btn-primary text-xs tracking-wider uppercase"
          >
            <Plus size={14} strokeWidth={2.5} />
            <span className="hidden sm:inline">New</span>
          </button>
        </nav>
      </div>
    </header>
  );
}

/* ───────────────────────── DASHBOARD ───────────────────────── */

function Dashboard({ trades, stats, curve, r2, mc, convictionBuckets, excessVsSpy, alphaResult, alphaLoading, alphaError, spyLoading, spyError, onRefreshSpy, sqn, breakEvenWR, rollingExp, snapshots, currentAccountValue, onOpenSnapshot, onDeleteSnapshot, durationBuckets, monthlyBreakdown, rulesSplit, cumulativeWR, setupBuckets }) {
  const [dashTab, setDashTab] = useState('overview');

  if (!trades.length) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-8">
      <AccountStatusBar
        trades={trades}
        snapshots={snapshots}
        currentAccountValue={currentAccountValue}
        onOpenSnapshot={onOpenSnapshot}
        onDeleteSnapshot={onDeleteSnapshot}
      />

      {/* Tab switcher */}
      <div className="flex gap-6 border-b border-rule">
        <button
          onClick={() => setDashTab('overview')}
          className={`btn-tab pb-3 ${dashTab === 'overview' ? 'btn-tab-active' : ''}`}
        >
          Overview
        </button>
        <button
          onClick={() => setDashTab('deep')}
          className={`btn-tab pb-3 ${dashTab === 'deep' ? 'btn-tab-active' : ''}`}
        >
          Deep Dive
        </button>
      </div>

      {dashTab === 'overview' && (
        <div className="space-y-8">
          <HeadlineStats stats={stats} />
          <EquityCurve
            curve={curve}
            r2={r2}
            excessVsSpy={excessVsSpy}
            alphaResult={alphaResult}
            alphaLoading={alphaLoading}
            spyLoading={spyLoading}
            spyError={spyError}
            onRefreshSpy={onRefreshSpy}
          />
          <MonthlyBreakdownPanel months={monthlyBreakdown} />
          <WinRateChart data={cumulativeWR} />
          <CalendarHeatmap trades={trades} />
        </div>
      )}

      {dashTab === 'deep' && (
        <div className="space-y-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <StrategyGradePanel sqn={sqn} n={trades.length} />
            <RollingExpectancyPanel rolling={rollingExp} n={trades.length} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <MonteCarloPanel mc={mc} n={trades.length} />
            <SecondaryStatsPanel stats={stats} excessVsSpy={excessVsSpy} alphaResult={alphaResult} alphaError={alphaError} breakEvenWR={breakEvenWR} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <DurationPanel buckets={durationBuckets} />
            <ConvictionPanel buckets={convictionBuckets} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <RulesPanel stats={stats} rulesSplit={rulesSplit} />
            <SetupTypePanel buckets={setupBuckets} />
          </div>
        </div>
      )}
    </div>
  );
}

function AccountStatusBar({ trades, snapshots, currentAccountValue, onOpenSnapshot, onDeleteSnapshot }) {
  // Find latest snapshot date
  const latestSnapshot = snapshots.length
    ? [...snapshots].sort((a, b) => new Date(b.date) - new Date(a.date))[0]
    : null;

  // Count trades since latest snapshot (or since start if none)
  const cutoffDate = latestSnapshot
    ? new Date(latestSnapshot.date)
    : trades.length
    ? new Date(Math.min(...trades.map((t) => new Date(t.entryDate).getTime())))
    : null;

  const tradesSince = cutoffDate
    ? trades.filter((t) => new Date(t.exitDate) > cutoffDate).length
    : 0;

  const driftWarning = tradesSince >= 10;

  return (
    <div className="card p-4 flex items-center justify-between gap-4 flex-wrap">
      <div className="flex items-center gap-4">
        <div>
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
            Est. Account Value
          </div>
          <div className="font-display text-2xl text-bone">
            {currentAccountValue !== null ? fmtMoney(currentAccountValue) : '—'}
          </div>
        </div>
        <div className="h-8 w-px bg-[color:var(--rule)]" style={{ backgroundColor: 'var(--rule)' }} />
        <div>
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
            Last snapshot
          </div>
          <div className="font-mono text-sm text-bone-dim">
            {latestSnapshot ? (
              <>
                {latestSnapshot.date} · {fmtMoney(latestSnapshot.value)}
              </>
            ) : (
              'None — using first trade'
            )}
          </div>
        </div>
        {driftWarning && (
          <div className="flex items-center gap-1.5 text-[11px] text-gold">
            <AlertTriangle size={12} />
            {tradesSince} trades since snapshot · drift possible
          </div>
        )}
      </div>
      <button
        onClick={onOpenSnapshot}
        className="btn-ghost text-xs tracking-wider uppercase inline-flex items-center gap-1.5"
      >
        <Calendar size={14} /> Snapshot account
      </button>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="card p-16 text-center">
      <Sparkles size={32} className="mx-auto mb-4 text-gold" />
      <h2 className="font-display text-3xl text-bone mb-2">A clean page</h2>
      <p className="text-bone-dim max-w-md mx-auto mb-6">
        Log your first closed trade to start building the picture. Every metric here grows
        stronger with more data — aim for 30 trades before putting serious weight on the numbers.
      </p>
    </div>
  );
}

function HeadlineStats({ stats }) {
  if (!stats) return null;

  const cards = [
    {
      label: 'Win Rate',
      value: `${(stats.winRate * 100).toFixed(0)}%`,
      sub: `${stats.winCount}W · ${stats.lossCount}L${stats.beCount ? ` · ${stats.beCount}BE` : ''}`,
      tone: stats.winRate >= 0.5 ? 'emerald' : 'neutral',
      icon: Target,
    },
    {
      label: 'Expectancy',
      value: fmtPct(stats.expectancy, 2),
      sub: 'per trade, avg',
      tone: stats.expectancy > 0 ? 'emerald' : stats.expectancy < 0 ? 'crimson' : 'neutral',
      icon: Scale,
      note: 'The core number. What you make on average per trade.',
    },
    {
      label: 'Profit Factor',
      value: fmtNum(stats.profitFactor, 2),
      sub: stats.profitFactor === Infinity ? 'no losses yet' : 'gross win ÷ gross loss',
      tone: stats.profitFactor >= 2 ? 'emerald' : stats.profitFactor >= 1 ? 'neutral' : 'crimson',
      icon: Flame,
    },
    {
      label: 'Kelly',
      value: `${(stats.kelly * 100).toFixed(1)}%`,
      sub: 'optimal position size',
      tone: stats.kelly > 0 ? 'gold' : 'crimson',
      icon: Dices,
      note: 'Use half of this in practice — full Kelly is a rollercoaster.',
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((c) => (
        <StatCard key={c.label} {...c} />
      ))}
    </div>
  );
}

function StatCard({ label, value, sub, tone, icon: Icon, note }) {
  const toneClass =
    tone === 'emerald'
      ? 'text-emerald'
      : tone === 'crimson'
      ? 'text-crimson'
      : tone === 'gold'
      ? 'text-gold'
      : 'text-bone';
  return (
    <div className="card p-5 flex flex-col justify-between min-h-[140px] group relative">
      <div className="flex items-start justify-between">
        <span className="font-mono text-[10px] tracking-widest uppercase text-stone">{label}</span>
        <Icon size={14} className="text-stone" strokeWidth={1.5} />
      </div>
      <div>
        <div className={`stat-value stat-value-lg text-4xl ${toneClass}`}>{value}</div>
        <div className="font-mono text-[11px] text-bone-dim mt-1">{sub}</div>
      </div>
      {note && (
        <div className="absolute inset-x-0 bottom-full mb-2 mx-2 p-2 bg-ink-raised border border-rule rounded text-[11px] text-bone-dim opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
          {note}
        </div>
      )}
    </div>
  );
}

function StrategyGradePanel({ sqn, n }) {
  const grade = sqnGrade(sqn);
  const confidence = sqnSampleConfidence(n);
  const toneColor =
    grade.tone === 'emerald'
      ? 'var(--emerald)'
      : grade.tone === 'crimson'
      ? 'var(--crimson)'
      : grade.tone === 'gold'
      ? 'var(--gold)'
      : 'var(--bone)';

  // Position indicator on the SQN spectrum (0 to 5 range shown)
  const clampedSqn = sqn === null ? null : Math.max(0, Math.min(5, sqn));
  const position = clampedSqn === null ? 0 : (clampedSqn / 5) * 100;

  const thresholds = [
    { at: 1.6, label: '1.6', tone: 'crimson' },
    { at: 2.0, label: '2.0' },
    { at: 2.5, label: '2.5' },
    { at: 3.0, label: '3.0', tone: 'emerald' },
  ];

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-display text-2xl text-bone">Strategy Grade</h3>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            system quality number · van tharp
          </p>
        </div>
        <Activity size={14} className="text-stone" strokeWidth={1.5} />
      </div>

      {sqn === null ? (
        <div className="text-center py-8">
          <div className="font-display text-xl text-stone mb-2">Needs 2+ trades</div>
          <div className="text-[11px] text-stone">{confidence}</div>
        </div>
      ) : (
        <>
          <div className="flex items-end gap-4 mb-4">
            <div
              className="stat-value text-6xl"
              style={{ color: toneColor }}
            >
              {sqn.toFixed(2)}
            </div>
            <div className="pb-2">
              <div
                className="font-display text-xl"
                style={{ color: toneColor }}
              >
                {grade.label}
              </div>
              <div className="text-[11px] text-stone font-mono tracking-widest uppercase mt-0.5">
                {confidence}
              </div>
            </div>
          </div>

          {/* SQN spectrum visualization */}
          <div className="relative mt-6 mb-8">
            <div className="h-1.5 rounded-full overflow-hidden flex">
              <div style={{ width: '32%', backgroundColor: 'var(--crimson-dim)' }} />
              <div style={{ width: '8%', backgroundColor: 'var(--crimson-dim)', opacity: 0.6 }} />
              <div style={{ width: '10%', backgroundColor: 'var(--stone)', opacity: 0.4 }} />
              <div style={{ width: '10%', backgroundColor: 'var(--emerald-dim)', opacity: 0.6 }} />
              <div style={{ width: '40%', backgroundColor: 'var(--emerald-dim)' }} />
            </div>
            {/* Position marker */}
            <div
              className="absolute top-0 -translate-x-1/2"
              style={{ left: `${position}%` }}
            >
              <div
                className="w-3 h-3 rounded-full -mt-0.5"
                style={{
                  backgroundColor: toneColor,
                  boxShadow: '0 0 0 3px var(--ink-card)',
                }}
              />
            </div>
            {/* Threshold labels */}
            <div className="flex justify-between mt-3 font-mono text-[10px] text-stone">
              <span>Poor</span>
              <span>1.6</span>
              <span>2.0</span>
              <span>2.5</span>
              <span>3.0</span>
              <span>Excellent</span>
            </div>
          </div>

          <p className="text-[11px] text-stone mt-3">
            Scored on account impact, so position sizing counts. N is capped at 100 in the √N term —
            without that cap the same edge scores higher purely for trading more. Still thin below
            30 trades.
          </p>
        </>
      )}
    </div>
  );
}

function RollingExpectancyPanel({ rolling, n }) {
  const { points = [], windowSize = 10 } = rolling || {};

  if (n < 2 || points.length === 0) {
    return (
      <div className="card p-5">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="font-display text-2xl text-bone">Rolling Expectancy</h3>
            <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
              is the edge still alive?
            </p>
          </div>
          <Activity size={14} className="text-stone" strokeWidth={1.5} />
        </div>
        <div className="flex flex-col items-center justify-center py-12 text-center text-stone">
          <Activity size={32} className="mb-3 opacity-40" />
          <p className="text-sm max-w-xs">
            Needs at least 2 trades. Meaningful from about trade 15 onward.
          </p>
        </div>
      </div>
    );
  }

  const latest = points[points.length - 1].expectancy;
  const first = points[0].expectancy;
  const trend = latest - first;

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-display text-2xl text-bone">Rolling Expectancy</h3>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            window of {windowSize} trades · edge decay tracker
          </p>
        </div>
        <div className="text-right">
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
            Latest
          </div>
          <div
            className={`font-display text-2xl ${
              latest > 0 ? 'text-emerald' : latest < 0 ? 'text-crimson' : 'text-bone'
            }`}
          >
            {fmtPct(latest, 2)}
          </div>
        </div>
      </div>

      <div className="h-40">
        <ResponsiveContainer>
          <ComposedChart data={points} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="rollFillPos" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6a9e7b" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#6a9e7b" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="tradeNum" stroke="#2a2c30" tick={{ fontSize: 10 }} />
            <YAxis stroke="#2a2c30" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
            <ReferenceLine y={0} stroke="#2a2c30" strokeDasharray="2 3" />
            <Tooltip content={<RollingTooltip />} />
            <Area type="monotone" dataKey="expectancy" stroke="none" fill="url(#rollFillPos)" />
            <Line
              type="monotone"
              dataKey="expectancy"
              stroke="#6a9e7b"
              strokeWidth={2}
              dot={{ r: 2.5, fill: '#6a9e7b' }}
              activeDot={{ r: 4, fill: '#ece6d9' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[11px] text-stone mt-3">
        If this line trends down over 20+ trades while your overall expectancy looks fine,
        your edge is decaying — your earlier wins are carrying the average.
      </p>
    </div>
  );
}

function RollingTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-ink-raised border border-rule px-3 py-2 rounded text-xs font-mono">
      <div className="text-stone">Trade #{p.tradeNum}</div>
      {p.ticker && <div className="text-bone-dim">{p.ticker}</div>}
      <div className={p.expectancy >= 0 ? 'text-emerald' : 'text-crimson'}>
        Exp: {fmtPct(p.expectancy, 2)}
      </div>
    </div>
  );
}

function EquityCurve({ curve, r2, excessVsSpy, alphaResult, alphaLoading, spyLoading, spyError, onRefreshSpy }) {
  if (curve.length < 2) return null;
  const finalEq = curve[curve.length - 1].equity;
  const finalSpy = curve[curve.length - 1].spy;
  const totalReturn = finalEq - 100;
  const spyReturn = finalSpy !== null && finalSpy !== undefined ? finalSpy - 100 : null;
  const hasSpy = curve.some((p) => p.spy !== null && p.spy !== undefined);

  return (
    <div className="card p-5">
      <div className="flex items-end justify-between mb-4 flex-wrap gap-4">
        <div>
          <h3 className="font-display text-2xl text-bone">Equity Curve</h3>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            starting at 100 · vs buy-and-hold SPY
          </p>
        </div>
        <div className="flex items-end gap-6 flex-wrap">
          <div>
            <div className="text-[10px] text-stone font-mono tracking-widest uppercase flex items-center gap-2">
              <span
                className="inline-block w-3 h-[2px]"
                style={{ backgroundColor: 'var(--gold)' }}
              />
              Strategy
            </div>
            <div
              className={`font-display text-2xl ${
                totalReturn >= 0 ? 'text-emerald' : 'text-crimson'
              }`}
            >
              {fmtPct(totalReturn, 2)}
            </div>
          </div>
          {spyReturn !== null && (
            <div>
              <div className="text-[10px] text-stone font-mono tracking-widest uppercase flex items-center gap-2">
                <span
                  className="inline-block w-3 h-[2px]"
                  style={{ backgroundColor: 'var(--bone-dim)' }}
                />
                SPY
              </div>
              <div className="font-display text-2xl text-bone-dim">
                {fmtPct(spyReturn, 2)}
              </div>
            </div>
          )}
          {/* Real Jensen alpha: return the market exposure you carried does not
              explain. The raw curve gap is shown beneath it, clearly separated,
              because the two answer different questions. */}
          <div>
            <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
              Alpha (β-adj)
            </div>
            {alphaLoading ? (
              <div className="font-display text-2xl text-stone">…</div>
            ) : alphaResult ? (
              <div
                className={`font-display text-2xl ${
                  alphaResult.alpha >= 0 ? 'text-emerald' : 'text-crimson'
                }`}
                title={`Account return ${fmtPct(alphaResult.total_impact * 100, 2)} = market-explained ${fmtPct(
                  alphaResult.market_explained * 100,
                  2
                )} + alpha ${fmtPct(alphaResult.alpha * 100, 2)} · avg market exposure ${alphaResult.avg_beta_exposure.toFixed(2)}`}
              >
                {fmtPct(alphaResult.alpha * 100, 2)}
              </div>
            ) : (
              <div className="font-display text-2xl text-stone">—</div>
            )}
          </div>
          {excessVsSpy !== null && (
            <div>
              <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
                Excess vs SPY
              </div>
              <div className="font-display text-2xl text-bone-dim" title="Raw curve gap, not risk-adjusted — context only">
                {fmtPct(excessVsSpy, 2)}
              </div>
            </div>
          )}
          {r2 !== null && (
            <div>
              <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
                R²
              </div>
              <div className="font-display text-2xl text-bone">{r2.toFixed(3)}</div>
            </div>
          )}
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer>
          <ComposedChart data={curve} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#d4a574" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#d4a574" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="label" stroke="#2a2c30" tick={{ fontSize: 11 }} />
            <YAxis stroke="#2a2c30" tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
            <ReferenceLine y={100} stroke="#2a2c30" strokeDasharray="2 3" />
            <Tooltip content={<EquityTooltip />} />
            <Area type="monotone" dataKey="equity" stroke="none" fill="url(#eqFill)" />
            {hasSpy && (
              <Line
                type="monotone"
                dataKey="spy"
                stroke="#b0a898"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={{ r: 2, fill: '#b0a898', stroke: '#b0a898' }}
                activeDot={{ r: 4, fill: '#ece6d9' }}
                connectNulls
              />
            )}
            <Line
              type="monotone"
              dataKey="equity"
              stroke="#d4a574"
              strokeWidth={2}
              dot={{ r: 3, fill: '#d4a574', stroke: '#d4a574' }}
              activeDot={{ r: 5, fill: '#ece6d9' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center justify-between mt-3 gap-4 flex-wrap">
        <p className="text-[11px] text-stone flex-1 min-w-[200px]">
          Gold = your strategy. Dashed = SPY buy-and-hold from your first entry date. Alpha = your
          edge over just holding the market.
        </p>
        <button
          onClick={onRefreshSpy}
          disabled={spyLoading}
          className="btn-ghost text-[10px] tracking-wider uppercase inline-flex items-center gap-1.5"
        >
          <RefreshCw size={11} className={spyLoading ? 'animate-spin' : ''} />
          {spyLoading ? 'Fetching SPY' : 'Refresh SPY'}
        </button>
      </div>
      {spyError && (
        <p className="text-[11px] text-crimson mt-2 flex items-center gap-1">
          <AlertTriangle size={11} /> {spyError}
        </p>
      )}
    </div>
  );
}

function EquityTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-ink-raised border border-rule px-3 py-2 rounded text-xs">
      <div className="font-mono text-stone mb-1">
        {p.ticker ? `#${p.label} · ${p.ticker}` : 'Start'}
      </div>
      <div className="font-mono text-gold">Strategy: {p.equity.toFixed(2)}</div>
      {p.spy !== null && p.spy !== undefined && (
        <div className="font-mono text-bone-dim">SPY: {p.spy.toFixed(2)}</div>
      )}
      {p.impact !== undefined && (
        <div className={`font-mono ${p.impact >= 0 ? 'text-emerald' : 'text-crimson'}`}>
          {fmtPct(p.impact, 2)}
        </div>
      )}
    </div>
  );
}

function MonteCarloPanel({ mc, n }) {
  if (!mc || n < 3) {
    return (
      <div className="card p-5">
        <h3 className="font-display text-2xl text-bone mb-1">Monte Carlo</h3>
        <p className="text-[11px] text-stone font-mono tracking-widest uppercase mb-4">
          projection of next 50 trades · 1,000 simulations
        </p>
        <div className="flex flex-col items-center justify-center h-64 text-center text-stone">
          <Dices size={32} className="mb-3 opacity-40" />
          <p className="text-sm max-w-xs">
            Needs at least 3 trades. With only {n}, any projection would be random noise.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="card p-5">
      <div className="flex items-end justify-between mb-4 flex-wrap gap-2">
        <div>
          <h3 className="font-display text-2xl text-bone">Monte Carlo</h3>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            next {mc.futureTrades} trades · 1,000 simulations
          </p>
        </div>
      </div>
      <div className="h-48">
        <ResponsiveContainer>
          <ComposedChart data={mc.bands} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="mcBand" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#d4a574" stopOpacity={0.15} />
                <stop offset="100%" stopColor="#d4a574" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <XAxis dataKey="idx" stroke="#2a2c30" tick={{ fontSize: 10 }} />
            <YAxis stroke="#2a2c30" tick={{ fontSize: 10 }} />
            <ReferenceLine y={100} stroke="#2a2c30" strokeDasharray="2 3" />
            <Tooltip content={<MCTooltip />} />
            <Area dataKey="p95" stroke="none" fill="url(#mcBand)" />
            <Area dataKey="p5" stroke="none" fill="#101114" />
            <Line type="monotone" dataKey="p50" stroke="#d4a574" strokeWidth={2} dot={false} />
            <Line
              type="monotone"
              dataKey="p75"
              stroke="#8a6a47"
              strokeWidth={1}
              strokeDasharray="2 3"
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="p25"
              stroke="#8a6a47"
              strokeWidth={1}
              strokeDasharray="2 3"
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-3 gap-3 mt-4 text-center">
        <div className="bg-ink-soft p-3 rounded">
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
            Median equity
          </div>
          <div className="font-display text-lg text-bone">{mc.finalMedian.toFixed(0)}</div>
          <div className="font-mono text-[10px] text-bone-dim mt-1">
            {mc.finalP5.toFixed(0)}–{mc.finalP95.toFixed(0)} (5–95%)
          </div>
        </div>
        <div className="bg-ink-soft p-3 rounded">
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
            Expected DD
          </div>
          <div className="font-display text-lg text-crimson">-{mc.ddMedian.toFixed(1)}%</div>
          <div className="font-mono text-[10px] text-bone-dim mt-1">
            worst 5%: -{mc.ddP95.toFixed(0)}%
          </div>
        </div>
        <div className="bg-ink-soft p-3 rounded">
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
            Losing streak
          </div>
          <div className="font-display text-lg text-bone">{Math.round(mc.streakMedian)}</div>
          <div className="font-mono text-[10px] text-bone-dim mt-1">
            worst 5%: {Math.round(mc.streakP95)}
          </div>
        </div>
      </div>
      <p className="text-[11px] text-stone mt-3">
        Bootstrapping your trade history. The "worst 5%" numbers are what to mentally prepare for —
        they <em>will</em> happen at some point if your distribution holds.
      </p>
    </div>
  );
}

function MCTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-ink-raised border border-rule px-3 py-2 rounded text-xs font-mono">
      <div className="text-stone mb-1">Trade #{p.idx}</div>
      <div className="text-bone">Median: {p.p50?.toFixed(1)}</div>
      <div className="text-bone-dim">P25–P75: {p.p25?.toFixed(1)}–{p.p75?.toFixed(1)}</div>
      <div className="text-stone">P5–P95: {p.p5?.toFixed(1)}–{p.p95?.toFixed(1)}</div>
    </div>
  );
}

function SecondaryStatsPanel({ stats, excessVsSpy, alphaResult, alphaError, breakEvenWR }) {
  if (!stats) return null;

  // Margin of safety: actual win rate minus break-even win rate
  const safetyMargin =
    breakEvenWR !== null && breakEvenWR !== undefined
      ? (stats.winRate - breakEvenWR) * 100
      : null;

  const rows = [
    { label: 'Avg win', value: fmtPct(stats.avgWin, 2), tone: 'emerald' },
    { label: 'Avg loss', value: `-${stats.avgLoss.toFixed(2)}%`, tone: 'crimson' },
    {
      label: 'Payoff ratio',
      value:
        stats.avgLoss === 0
          ? '∞'
          : (stats.avgWin / stats.avgLoss).toFixed(2) + ':1',
      tone: 'neutral',
      hint: 'avg win size vs avg loss size',
    },
    {
      label: 'Break-even WR',
      value: breakEvenWR === null ? '—' : `${(breakEvenWR * 100).toFixed(1)}%`,
      tone: 'neutral',
      hint:
        safetyMargin === null
          ? 'minimum win rate to not lose money'
          : `you're at ${(stats.winRate * 100).toFixed(0)}% · ${safetyMargin >= 0 ? '+' : ''}${safetyMargin.toFixed(1)}pt margin`,
    },
    {
      label: 'Avg hold',
      value: `${stats.avgHold.toFixed(1)} days`,
      tone: 'neutral',
    },
    {
      label: 'Expectancy / day',
      value: fmtPct(stats.expectancyPerDay, 3),
      tone: stats.expectancyPerDay > 0 ? 'emerald' : 'crimson',
      hint: 'capital efficiency — short fast wins > long slow wins',
    },
    {
      label: 'Alpha (β-adjusted)',
      value: alphaError
        ? 'error'
        : alphaResult === null
        ? '—'
        : fmtPct(alphaResult.alpha * 100, 2),
      tone:
        alphaError || alphaResult === null
          ? 'neutral'
          : alphaResult.alpha > 0
          ? 'emerald'
          : 'crimson',
      hint: alphaError
        ? alphaError
        : alphaResult === null
        ? 'return your market exposure does not explain'
        : `account ${fmtPct(alphaResult.total_impact * 100, 2)} = market ${fmtPct(
            alphaResult.market_explained * 100,
            2
          )} + alpha ${fmtPct(alphaResult.alpha * 100, 2)}`,
    },
    {
      label: 'Avg market exposure',
      value:
        alphaResult === null ? '—' : alphaResult.avg_beta_exposure.toFixed(2),
      tone: 'neutral',
      hint: 'average β × position weight — how much market risk you carried',
    },
    {
      label: 'Excess vs SPY',
      value: excessVsSpy === null ? '—' : fmtPct(excessVsSpy, 2),
      tone: 'neutral',
      hint: 'raw curve gap, NOT risk-adjusted — context only',
    },
  ];
  return (
    <div className="card p-5">
      <h3 className="font-display text-2xl text-bone mb-1">Detail</h3>
      <p className="text-[11px] text-stone font-mono tracking-widest uppercase mb-4">
        deeper breakdown
      </p>
      <div className="divide-rule">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between py-3">
            <div>
              <div className="text-bone-dim text-sm">{r.label}</div>
              {r.hint && <div className="text-[11px] text-stone">{r.hint}</div>}
            </div>
            <div
              className={`font-mono font-medium ${
                r.tone === 'emerald'
                  ? 'text-emerald'
                  : r.tone === 'crimson'
                  ? 'text-crimson'
                  : 'text-bone'
              }`}
            >
              {r.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ConvictionPanel({ buckets }) {
  const withData = buckets.filter((b) => b.count > 0);
  return (
    <div className="card p-5">
      <h3 className="font-display text-2xl text-bone mb-1">Conviction vs Outcome</h3>
      <p className="text-[11px] text-stone font-mono tracking-widest uppercase mb-4">
        do your 5s actually beat your 2s?
      </p>
      {withData.length === 0 ? (
        <div className="text-stone text-sm text-center py-8">No data yet</div>
      ) : (
        <div className="h-48">
          <ResponsiveContainer>
            <BarChart data={buckets} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <XAxis dataKey="conviction" stroke="#2a2c30" tick={{ fontSize: 11 }} />
              <YAxis stroke="#2a2c30" tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
              <ReferenceLine y={0} stroke="#2a2c30" />
              <Tooltip content={<ConvictionTooltip />} />
              <Bar dataKey="avgReturn" radius={[2, 2, 0, 0]}>
                {buckets.map((b, i) => (
                  <Cell
                    key={i}
                    fill={b.count === 0 ? '#2a2c30' : b.avgReturn >= 0 ? '#6a9e7b' : '#c97664'}
                    opacity={b.count === 0 ? 0.3 : 1}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-[11px] text-stone mt-3">
        Most traders find conviction doesn't correlate well with outcomes. If your 5s don't
        outperform your 2s over 30+ trades, your confidence calibration needs work.
      </p>
    </div>
  );
}

function ConvictionTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  if (p.count === 0) return null;
  return (
    <div className="bg-ink-raised border border-rule px-3 py-2 rounded text-xs font-mono">
      <div className="text-stone">Conviction {p.conviction}</div>
      <div className="text-bone">{p.count} trade{p.count === 1 ? '' : 's'}</div>
      <div className={p.avgReturn >= 0 ? 'text-emerald' : 'text-crimson'}>
        Avg: {fmtPct(p.avgReturn, 2)}
      </div>
    </div>
  );
}

function SetupTypePanel({ buckets }) {
  const withData = buckets.filter((b) => b.count > 0);

  return (
    <div className="card p-5">
      <h3 className="font-display text-2xl text-bone mb-1">Setup Type</h3>
      <p className="text-[11px] text-stone font-mono tracking-widest uppercase mb-4">
        performance by setup · which type is your edge?
      </p>
      {withData.length === 0 ? (
        <div className="text-stone text-sm text-center py-8">No data yet</div>
      ) : (
        <div className="space-y-3">
          {buckets.map((b) => {
            const isActive = b.count > 0;
            return (
              <div
                key={b.type}
                className="bg-ink-soft rounded p-4"
                style={{ opacity: isActive ? 1 : 0.4 }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="font-mono text-sm text-bone font-medium">{b.label}</div>
                  <div className="font-mono text-[11px] text-bone-dim">
                    {b.count} trade{b.count === 1 ? '' : 's'}
                  </div>
                </div>
                {isActive && (
                  <div className="flex items-center gap-6">
                    <div>
                      <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-0.5">
                        Win rate
                      </div>
                      <div className="font-mono text-sm text-bone">
                        {(b.winRate * 100).toFixed(0)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-0.5">
                        Avg return
                      </div>
                      <div
                        className={`font-mono text-sm ${
                          b.avgReturn >= 0 ? 'text-emerald' : 'text-crimson'
                        }`}
                      >
                        {fmtPct(b.avgReturn, 2)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-0.5">
                        Expectancy
                      </div>
                      <div
                        className={`font-mono text-sm ${
                          b.expectancy >= 0 ? 'text-emerald' : 'text-crimson'
                        }`}
                      >
                        {fmtPct(b.expectancy, 2)}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="text-[11px] text-stone mt-3">
        Separate expectancy per setup type. After 30+ trades, this tells you which
        setups carry your edge and which are dead weight.
      </p>
    </div>
  );
}

function DurationPanel({ buckets }) {
  const withData = buckets.filter((b) => b.count > 0);

  return (
    <div className="card p-5">
      <h3 className="font-display text-2xl text-bone mb-1">Hold Duration</h3>
      <p className="text-[11px] text-stone font-mono tracking-widest uppercase mb-4">
        is there a sweet spot?
      </p>
      {withData.length === 0 ? (
        <div className="text-stone text-sm text-center py-8">No data yet</div>
      ) : (
        <div className="h-48">
          <ResponsiveContainer>
            <BarChart data={buckets} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <XAxis dataKey="label" stroke="#2a2c30" tick={{ fontSize: 11 }} />
              <YAxis stroke="#2a2c30" tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
              <ReferenceLine y={0} stroke="#2a2c30" />
              <Tooltip content={<DurationTooltip />} />
              <Bar dataKey="avgReturn" radius={[2, 2, 0, 0]}>
                {buckets.map((b, i) => (
                  <Cell
                    key={i}
                    fill={b.count === 0 ? '#2a2c30' : b.avgReturn >= 0 ? '#6a9e7b' : '#c97664'}
                    opacity={b.count === 0 ? 0.3 : 1}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-[11px] text-stone mt-3">
        Average return by hold duration. If short holds consistently outperform longer ones,
        you might be overstaying your welcome — or vice versa. Needs 30+ trades to trust.
      </p>
    </div>
  );
}

function DurationTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  if (p.count === 0) return null;
  return (
    <div className="bg-ink-raised border border-rule px-3 py-2 rounded text-xs font-mono">
      <div className="text-stone">{p.label} hold</div>
      <div className="text-bone">{p.count} trade{p.count === 1 ? '' : 's'}</div>
      <div className={p.avgReturn >= 0 ? 'text-emerald' : 'text-crimson'}>
        Avg: {fmtPct(p.avgReturn, 2)}
      </div>
      <div className="text-bone-dim">WR: {(p.winRate * 100).toFixed(0)}%</div>
    </div>
  );
}

function WinRateChart({ data }) {
  if (!data.length) return null;

  const latest = data[data.length - 1];

  return (
    <div className="card p-5">
      <div className="flex items-end justify-between mb-4 flex-wrap gap-3">
        <div>
          <h3 className="font-display text-2xl text-bone">Win Rate</h3>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            cumulative · dashed = break-even threshold
          </p>
        </div>
        <div className="flex items-end gap-6">
          <div>
            <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
              Current
            </div>
            <div className="font-display text-2xl text-emerald">
              {latest.winRate.toFixed(1)}%
            </div>
          </div>
          {latest.breakEven !== null && (
            <div>
              <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
                Break-even
              </div>
              <div className="font-display text-2xl text-bone-dim">
                {latest.breakEven.toFixed(1)}%
              </div>
            </div>
          )}
          {latest.margin !== null && (
            <div>
              <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
                Margin
              </div>
              <div
                className={`font-display text-2xl ${
                  latest.margin >= 0 ? 'text-emerald' : 'text-crimson'
                }`}
              >
                {latest.margin >= 0 ? '+' : ''}{latest.margin.toFixed(1)}pt
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="h-52">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="wrFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6a9e7b" stopOpacity={0.2} />
                <stop offset="100%" stopColor="#6a9e7b" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="tradeNum" stroke="#2a2c30" tick={{ fontSize: 11 }} />
            <YAxis
              stroke="#2a2c30"
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => `${v}%`}
              domain={[0, 100]}
            />
            <Tooltip content={<WinRateTooltip />} />
            <Area type="monotone" dataKey="winRate" stroke="none" fill="url(#wrFill)" />
            <Line
              type="monotone"
              dataKey="breakEven"
              stroke="#b0a898"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="winRate"
              stroke="#6a9e7b"
              strokeWidth={2}
              dot={{ r: 3, fill: '#6a9e7b', stroke: '#6a9e7b' }}
              activeDot={{ r: 5, fill: '#ece6d9' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[11px] text-stone mt-3">
        Green = your cumulative win rate after each trade. Dashed = break-even win rate
        (minimum WR needed given your payoff ratio). The gap between them is your margin of safety.
      </p>
    </div>
  );
}

function WinRateTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-ink-raised border border-rule px-3 py-2 rounded text-xs font-mono">
      <div className="text-stone">Trade #{p.tradeNum} · {p.ticker}</div>
      <div className="text-emerald">WR: {p.winRate.toFixed(1)}%</div>
      {p.breakEven !== null && (
        <div className="text-bone-dim">Break-even: {p.breakEven.toFixed(1)}%</div>
      )}
      {p.margin !== null && (
        <div className={p.margin >= 0 ? 'text-emerald' : 'text-crimson'}>
          Margin: {p.margin >= 0 ? '+' : ''}{p.margin.toFixed(1)}pt
        </div>
      )}
    </div>
  );
}

function CalendarHeatmap({ trades }) {
  // Build a map of exitDate → net account impact for that day
  const dayMap = {};
  trades.forEach((t) => {
    const d = t.exitDate;
    if (!dayMap[d]) dayMap[d] = { impact: 0, count: 0, wins: 0, losses: 0, tickers: [] };
    const imp = accountImpactPct(t);
    dayMap[d].impact += imp;
    dayMap[d].count += 1;
    if (tradeReturnPct(t) > 0) dayMap[d].wins += 1;
    else if (tradeReturnPct(t) < 0) dayMap[d].losses += 1;
    dayMap[d].tickers.push(t.ticker);
  });

  // Determine date range: show months that have trades, plus current month
  const allDates = Object.keys(dayMap).sort();
  const now = new Date();
  const currentMonthStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  // Get unique months from trades + current month
  const monthSet = new Set();
  allDates.forEach((d) => monthSet.add(d.slice(0, 7)));
  monthSet.add(currentMonthStr);
  const months = Array.from(monthSet).sort();

  // Navigation state
  const [selectedMonth, setSelectedMonth] = useState(months[months.length - 1]);
  const [hoveredDay, setHoveredDay] = useState(null);

  // Build calendar grid for selected month
  const buildMonthGrid = (monthStr) => {
    const [year, month] = monthStr.split('-').map(Number);
    const firstDay = new Date(year, month - 1, 1);
    const lastDay = new Date(year, month, 0);
    const startDow = firstDay.getDay(); // 0=Sun
    const daysInMonth = lastDay.getDate();

    const grid = [];
    // Fill leading empty cells
    for (let i = 0; i < startDow; i++) grid.push(null);
    // Fill days
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      grid.push({
        day: d,
        date: dateStr,
        data: dayMap[dateStr] || null,
        isToday:
          d === now.getDate() &&
          month === now.getMonth() + 1 &&
          year === now.getFullYear(),
        isWeekend: new Date(year, month - 1, d).getDay() === 0 || new Date(year, month - 1, d).getDay() === 6,
      });
    }
    return grid;
  };

  const grid = buildMonthGrid(selectedMonth);
  const monthNames = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const [selYear, selMon] = selectedMonth.split('-').map(Number);
  const monthLabel = `${monthNames[selMon]} ${selYear}`;

  // Month navigation
  const monthIdx = months.indexOf(selectedMonth);
  const canPrev = monthIdx > 0;
  const canNext = monthIdx < months.length - 1;

  // Color scale for cells
  const getCellStyle = (data) => {
    if (!data) return {};
    const imp = data.impact;
    if (imp > 0) {
      const intensity = Math.min(1, Math.abs(imp) / 2); // 2% = full saturation
      return {
        backgroundColor: `rgba(106, 158, 123, ${0.15 + intensity * 0.65})`,
        borderColor: `rgba(106, 158, 123, ${0.3 + intensity * 0.5})`,
      };
    } else {
      const intensity = Math.min(1, Math.abs(imp) / 2);
      return {
        backgroundColor: `rgba(201, 118, 100, ${0.15 + intensity * 0.65})`,
        borderColor: `rgba(201, 118, 100, ${0.3 + intensity * 0.5})`,
      };
    }
  };

  // Monthly summary
  const monthTrades = trades.filter((t) => t.exitDate.startsWith(selectedMonth));
  const monthImpact = monthTrades.reduce((a, t) => a + accountImpactPct(t), 0);
  const monthWins = monthTrades.filter((t) => tradeReturnPct(t) > 0).length;
  const monthLosses = monthTrades.filter((t) => tradeReturnPct(t) < 0).length;
  const tradingDays = new Set(monthTrades.map((t) => t.exitDate)).size;

  return (
    <div className="card p-5">
      <div className="flex items-end justify-between mb-5 flex-wrap gap-3">
        <div>
          <h3 className="font-display text-2xl text-bone">Calendar</h3>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            daily P&L heatmap
          </p>
        </div>

        {/* Month nav */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => canPrev && setSelectedMonth(months[monthIdx - 1])}
            disabled={!canPrev}
            className="btn-ghost px-2 py-1 disabled:opacity-20"
          >
            ‹
          </button>
          <div className="font-display text-lg text-bone min-w-[160px] text-center">
            {monthLabel}
          </div>
          <button
            onClick={() => canNext && setSelectedMonth(months[monthIdx + 1])}
            disabled={!canNext}
            className="btn-ghost px-2 py-1 disabled:opacity-20"
          >
            ›
          </button>
        </div>
      </div>

      {/* Day-of-week headers */}
      <div className="grid grid-cols-7 gap-1 mb-1">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
          <div
            key={d}
            className="text-center font-mono text-[10px] text-stone tracking-widest uppercase py-1"
          >
            {d}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-1">
        {grid.map((cell, i) => {
          if (cell === null) {
            return <div key={`empty-${i}`} className="aspect-square" />;
          }
          const hasData = !!cell.data;
          const isHovered = hoveredDay === cell.date;

          return (
            <div
              key={cell.date}
              className="aspect-square relative rounded cursor-default transition-all"
              style={{
                border: '1px solid',
                borderColor: cell.isToday
                  ? 'var(--gold)'
                  : hasData
                  ? getCellStyle(cell.data).borderColor
                  : '#3a3d42',
                backgroundColor: hasData
                  ? getCellStyle(cell.data).backgroundColor
                  : 'transparent',
                opacity: cell.isWeekend && !hasData ? 0.5 : 1,
              }}
              onMouseEnter={() => setHoveredDay(cell.date)}
              onMouseLeave={() => setHoveredDay(null)}
            >
              {/* Day number */}
              <div
                className="absolute top-1 left-1.5 font-mono text-[10px]"
                style={{
                  color: cell.isToday
                    ? 'var(--gold)'
                    : hasData
                    ? 'var(--bone)'
                    : 'var(--stone)',
                }}
              >
                {cell.day}
              </div>

              {/* Impact value in center */}
              {hasData && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <div
                    className="font-mono text-xs font-semibold"
                    style={{
                      color: 'var(--bone)',
                      textShadow: '0 1px 3px rgba(0,0,0,0.4)',
                    }}
                  >
                    {cell.data.impact >= 0 ? '+' : ''}{cell.data.impact.toFixed(2)}%
                  </div>
                </div>
              )}

              {/* Trade count */}
              {hasData && cell.data.count > 1 && (
                <div
                  className="absolute bottom-1 right-1.5 font-mono text-[10px] font-medium"
                  style={{ color: 'var(--bone)', textShadow: '0 1px 2px rgba(0,0,0,0.4)' }}
                >
                  ×{cell.data.count}
                </div>
              )}

              {/* Tooltip */}
              {isHovered && hasData && (
                <div
                  className="absolute z-10 bg-ink-raised border border-rule rounded px-3 py-2 text-xs font-mono shadow-lg pointer-events-none"
                  style={{
                    bottom: '110%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  <div className="text-stone mb-1">{cell.date}</div>
                  <div
                    style={{
                      color: cell.data.impact >= 0 ? 'var(--emerald)' : 'var(--crimson)',
                    }}
                  >
                    Net: {fmtPct(cell.data.impact, 2)}
                  </div>
                  <div className="text-bone">
                    {cell.data.count} trade{cell.data.count === 1 ? '' : 's'} · {cell.data.wins}W {cell.data.losses}L
                  </div>
                  <div className="text-bone-dim">{cell.data.tickers.join(', ')}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Monthly summary strip */}
      <div
        className="mt-4 pt-4 flex items-center gap-6 flex-wrap"
        style={{ borderTop: '1px solid var(--rule)' }}
      >
        <div>
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-0.5">
            Net
          </div>
          <div
            className={`font-display text-xl ${
              monthImpact >= 0 ? 'text-emerald' : 'text-crimson'
            }`}
          >
            {monthTrades.length ? fmtPct(monthImpact, 2) : '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-0.5">
            Trades
          </div>
          <div className="font-mono text-bone">{monthTrades.length}</div>
        </div>
        <div>
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-0.5">
            W / L
          </div>
          <div className="font-mono text-bone">
            <span className="text-emerald">{monthWins}</span>
            {' / '}
            <span className="text-crimson">{monthLosses}</span>
          </div>
        </div>
        <div>
          <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-0.5">
            Active days
          </div>
          <div className="font-mono text-bone">{tradingDays}</div>
        </div>

        {/* Legend */}
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div
              className="w-3 h-3 rounded"
              style={{ backgroundColor: 'rgba(201, 118, 100, 0.5)' }}
            />
            <span className="font-mono text-[10px] text-stone">Loss</span>
          </div>
          <div
            className="w-3 h-3 rounded"
            style={{ backgroundColor: 'var(--rule)' }}
          />
          <div className="flex items-center gap-1.5">
            <div
              className="w-3 h-3 rounded"
              style={{ backgroundColor: 'rgba(106, 158, 123, 0.5)' }}
            />
            <span className="font-mono text-[10px] text-stone">Win</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function MonthlyBreakdownPanel({ months }) {
  if (!months.length) return null;

  return (
    <div className="card p-5">
      <div className="flex items-end justify-between mb-4 flex-wrap gap-2">
        <div>
          <h3 className="font-display text-2xl text-bone">Monthly Returns</h3>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            net account impact per month
          </p>
        </div>
      </div>
      <div className="h-48">
        <ResponsiveContainer>
          <BarChart data={months} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <XAxis
              dataKey="month"
              stroke="#2a2c30"
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => {
                const parts = v.split('-');
                const monthNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                return `${monthNames[parseInt(parts[1])]} '${parts[0].slice(2)}`;
              }}
            />
            <YAxis stroke="#2a2c30" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
            <ReferenceLine y={0} stroke="#2a2c30" />
            <Tooltip content={<MonthlyTooltip />} />
            <Bar dataKey="impact" radius={[2, 2, 0, 0]}>
              {months.map((m, i) => (
                <Cell
                  key={i}
                  fill={m.impact >= 0 ? '#6a9e7b' : '#c97664'}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function MonthlyTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const parts = p.month.split('-');
  const monthNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const label = `${monthNames[parseInt(parts[1])]} ${parts[0]}`;
  return (
    <div className="bg-ink-raised border border-rule px-3 py-2 rounded text-xs font-mono">
      <div className="text-stone">{label}</div>
      <div className={p.impact >= 0 ? 'text-emerald' : 'text-crimson'}>
        Net: {fmtPct(p.impact, 2)}
      </div>
      <div className="text-bone">{p.count} trade{p.count === 1 ? '' : 's'}</div>
      <div className="text-bone-dim">{p.wins}W · {p.losses}L</div>
    </div>
  );
}

function RulesPanel({ stats, rulesSplit }) {
  if (!stats) return null;
  const total = stats.ruleFollowed + stats.ruleBroken;
  const followedPct = total > 0 ? (stats.ruleFollowed / total) * 100 : null;

  return (
    <div className="card p-5">
      <h3 className="font-display text-2xl text-bone mb-1">Discipline</h3>
      <p className="text-[11px] text-stone font-mono tracking-widest uppercase mb-4">
        rules followed vs broken · all trades · with expectancy split
      </p>
      {total === 0 ? (
        <div className="text-stone text-sm text-center py-12">No trades yet</div>
      ) : (
        <>
          {total > 0 && (
            <>
              <div className="flex items-end gap-6 mb-4">
                <div>
                  <div className="font-display text-4xl text-emerald">
                    {followedPct.toFixed(0)}%
                  </div>
                  <div className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
                    plan executed
                  </div>
                </div>
                <div>
                  <div className="font-display text-4xl text-crimson">
                    {(100 - followedPct).toFixed(0)}%
                  </div>
                  <div className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
                    rules broken
                  </div>
                </div>
              </div>
              <div className="h-2 bg-ink-soft rounded-full overflow-hidden flex">
                <div
                  className="bg-emerald-dim"
                  style={{ width: `${followedPct}%` }}
                />
                <div
                  className="bg-crimson-dim"
                  style={{ width: `${100 - followedPct}%` }}
                />
              </div>
              <div className="flex justify-between mt-2 font-mono text-[11px] text-bone-dim">
                <span>{stats.ruleFollowed} followed</span>
                <span>{stats.ruleBroken} broken</span>
              </div>
            </>
          )}

          {/* Split expectancy comparison */}
          {rulesSplit && (rulesSplit.followed || rulesSplit.broken) && (
            <div className="mt-5">
              <div className="hairline mb-4" />
              <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-3">
                Expectancy split
              </div>
              <div className="grid grid-cols-2 gap-3">
                {rulesSplit.followed && (
                  <div className="bg-ink-soft rounded p-3">
                    <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
                      Rules followed
                    </div>
                    <div
                      className={`font-display text-xl ${
                        rulesSplit.followed.expectancy >= 0 ? 'text-emerald' : 'text-crimson'
                      }`}
                    >
                      {fmtPct(rulesSplit.followed.expectancy, 2)}
                    </div>
                    <div className="font-mono text-[10px] text-bone-dim mt-1">
                      {rulesSplit.followed.count} trades · {(rulesSplit.followed.winRate * 100).toFixed(0)}% WR
                    </div>
                  </div>
                )}
                {rulesSplit.broken && (
                  <div className="bg-ink-soft rounded p-3">
                    <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
                      Rules broken
                    </div>
                    <div
                      className={`font-display text-xl ${
                        rulesSplit.broken.expectancy >= 0 ? 'text-emerald' : 'text-crimson'
                      }`}
                    >
                      {fmtPct(rulesSplit.broken.expectancy, 2)}
                    </div>
                    <div className="font-mono text-[10px] text-bone-dim mt-1">
                      {rulesSplit.broken.count} trades · {(rulesSplit.broken.winRate * 100).toFixed(0)}% WR
                    </div>
                  </div>
                )}
              </div>
              <p className="text-[11px] text-stone mt-3">
                If rules-broken trades have negative expectancy while rules-followed stay
                positive, your process is good — the mistakes are identifiable and fixable.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ───────────────────────── TRADES LIST ───────────────────────── */

function TradesList({ trades, onEdit, onDelete, onNew }) {
  const sorted = useMemo(
    () => [...trades].sort((a, b) => new Date(b.entryDate) - new Date(a.entryDate)),
    [trades]
  );

  const [csvText, setCsvText] = useState(null);
  const [copied, setCopied] = useState(false);

  const exportCsv = () => {
    const headers = [
      'Ticker','EntryDate','ExitDate','EntryPrice','ExitPrice',
      'AccountValueAtEntry','PositionDollars','PositionSize%',
      'TradeReturn%','AccountImpact%','HoldDays','Conviction','SetupType',
      'ScaledInOut','FollowedRules','Notes'
    ];
    const rows = sorted.map((t) => [
      t.ticker, t.entryDate, t.exitDate, t.entryPrice, t.exitPrice,
      t.accountValueAtEntry, t.positionDollars,
      positionSizePct(t).toFixed(2),
      tradeReturnPct(t).toFixed(2),
      accountImpactPct(t).toFixed(3),
      holdDays(t), t.conviction,
      t.setupType || '',
      t.scaledInOut ? 'Y' : 'N',
      t.followedRules ? 'Y' : 'N',
      (t.notes || '').replace(/\n/g, ' ').replace(/"/g, '""'),
    ]);
    const csv = [headers.join(','), ...rows.map((r) => r.map((c) => `"${c}"`).join(','))].join('\n');

    // Try download first, fall back to copy modal
    try {
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `ledger-${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setCsvText(csv);
    }
    // Also show the modal as fallback if download was blocked
    setCsvText(csv);
  };

  const copyCsv = async () => {
    if (!csvText) return;
    try {
      await navigator.clipboard.writeText(csvText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      // Fallback: select the textarea content
      const ta = document.querySelector('#csv-export-text');
      if (ta) {
        ta.select();
        document.execCommand('copy');
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    }
  };

  if (!trades.length) {
    return (
      <div className="card p-12 text-center">
        <BookOpen size={32} className="mx-auto mb-4 text-stone" />
        <h3 className="font-display text-2xl text-bone mb-3">No trades logged yet</h3>
        <button onClick={onNew} className="btn-primary inline-flex items-center gap-2">
          <Plus size={14} /> Log first trade
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="font-display text-3xl text-bone">Trades</h2>
        <div className="flex gap-2">
          <button
            onClick={exportCsv}
            className="btn-ghost text-xs tracking-wider uppercase inline-flex items-center gap-1.5"
          >
            <Download size={14} /> Export CSV
          </button>
          <button onClick={onNew} className="btn-primary text-xs tracking-wider uppercase inline-flex items-center gap-1.5">
            <Plus size={14} /> New
          </button>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-rule bg-ink-soft">
                <Th>Ticker</Th>
                <Th>Entry → Exit</Th>
                <Th right>Entry</Th>
                <Th right>Exit</Th>
                <Th right>Size</Th>
                <Th right>Return</Th>
                <Th right>Impact</Th>
                <Th right>Hold</Th>
                <Th center>Conv.</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((t) => {
                const ret = tradeReturnPct(t);
                const imp = accountImpactPct(t);
                return (
                  <tr
                    key={t.id}
                    className="border-b border-rule row-hover transition-colors group"
                  >
                    <Td>
                      <span className="font-mono font-semibold text-bone">{t.ticker}</span>
                      {t.setupType && (
                        <span className="chip ml-2 text-stone">
                          {t.setupType === 'dip_buy' ? 'dip' : t.setupType}
                        </span>
                      )}
                      {t.scaledInOut && (
                        <span className="chip ml-1 text-stone">scaled</span>
                      )}
                    </Td>
                    <Td>
                      <div className="font-mono text-[11px] text-bone-dim">
                        {t.entryDate} → {t.exitDate}
                      </div>
                    </Td>
                    <Td right mono>{fmtMoney(t.entryPrice)}</Td>
                    <Td right mono>{fmtMoney(t.exitPrice)}</Td>
                    <Td right mono>{positionSizePct(t).toFixed(1)}%</Td>
                    <Td right>
                      <span className={`font-mono font-medium ${ret >= 0 ? 'text-emerald' : 'text-crimson'}`}>
                        {fmtPct(ret, 2)}
                      </span>
                    </Td>
                    <Td right>
                      <span className={`font-mono ${imp >= 0 ? 'text-emerald' : 'text-crimson'}`}>
                        {fmtPct(imp, 2)}
                      </span>
                    </Td>
                    <Td right mono>{holdDays(t)}d</Td>
                    <Td center>
                      <ConvictionPip level={t.conviction} />
                    </Td>
                    <Td>
                      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => onEdit(t)}
                          className="p-1.5 text-stone hover:text-bone transition-colors"
                        >
                          <Edit3 size={14} />
                        </button>
                        <button
                          onClick={() => onDelete(t.id)}
                          className="p-1.5 text-stone hover:text-crimson transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mobile hint */}
      <p className="sm:hidden text-[11px] text-stone mt-3 text-center">
        Swipe table sideways for more columns →
      </p>

      {/* CSV Export Modal */}
      {csvText && (
        <div className="fixed inset-0 modal-overlay backdrop-blur-sm z-30 flex items-center justify-center p-4">
          <div className="card p-6 max-w-2xl w-full">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="font-display text-xl text-bone">Export CSV</h3>
                <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
                  copy and paste into a .csv file
                </p>
              </div>
              <button
                onClick={() => { setCsvText(null); setCopied(false); }}
                className="text-stone hover:text-bone transition-colors p-1"
              >
                <X size={18} />
              </button>
            </div>
            <textarea
              id="csv-export-text"
              readOnly
              value={csvText}
              className="input w-full font-mono text-xs"
              style={{
                height: '240px',
                resize: 'none',
                whiteSpace: 'pre',
                overflowX: 'auto',
              }}
              onClick={(e) => e.target.select()}
            />
            <div className="flex items-center justify-between mt-4">
              <p className="text-[11px] text-stone">
                Click the text to select all, then paste into a text file and save as .csv
              </p>
              <button
                onClick={copyCsv}
                className="btn-primary text-xs tracking-wider uppercase inline-flex items-center gap-1.5"
              >
                {copied ? (
                  <><CheckCircle2 size={14} /> Copied</>
                ) : (
                  <><Download size={14} /> Copy to clipboard</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Th({ children, right, center }) {
  return (
    <th
      className={`px-3 py-2.5 text-[10px] font-mono tracking-widest uppercase text-stone font-normal ${
        right ? 'text-right' : center ? 'text-center' : 'text-left'
      }`}
    >
      {children}
    </th>
  );
}

function Td({ children, right, center, mono }) {
  return (
    <td
      className={`px-3 py-3 ${right ? 'text-right' : center ? 'text-center' : 'text-left'} ${
        mono ? 'font-mono text-bone-dim' : ''
      }`}
    >
      {children}
    </td>
  );
}

function ConvictionPip({ level }) {
  return (
    <div className="inline-flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${
            i <= level ? 'bg-gold' : 'bg-ink-raised'
          }`}
          style={{ backgroundColor: i <= level ? 'var(--gold)' : 'var(--ink-raised)' }}
        />
      ))}
    </div>
  );
}

/* ───────────────────────── TRADE FORM ───────────────────────── */

function TradeForm({ trade, onSave, onCancel, suggestedValue }) {
  const isEdit = !!trade;
  const [form, setForm] = useState(
    trade
      ? { ...trade }
      : {
          id: `trade-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          ticker: '',
          entryDate: '',
          exitDate: '',
          entryPrice: '',
          exitPrice: '',
          iv: '',
          accountValueAtEntry: '',
          positionDollars: '',
          conviction: 3,
          setupType: 'bounce',
          scaledInOut: false,
          followedRules: true,
          notes: '',
          tranches: [],
          exitTranches: [],
        }
  );

  // Auto-fill account value when creating a new trade and entry date is set
  const [accountAutoFilled, setAccountAutoFilled] = useState(false);
  useEffect(() => {
    if (isEdit) return;
    if (!form.entryDate) return;
    if (form.accountValueAtEntry !== '' && !accountAutoFilled) return;
    const suggested = suggestedValue ? suggestedValue(form.entryDate) : null;
    if (suggested !== null && suggested !== undefined) {
      setForm((f) => ({ ...f, accountValueAtEntry: Number(suggested.toFixed(2)) }));
      setAccountAutoFilled(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.entryDate]);

  const [errors, setErrors] = useState({});

  const numericField = (k) => (e) => {
    const v = e.target.value;
    setForm({ ...form, [k]: v === '' ? '' : Number(v) });
  };

  const ret =
    form.entryPrice && form.exitPrice
      ? ((Number(form.exitPrice) - Number(form.entryPrice)) / Number(form.entryPrice)) * 100
      : null;
  const isLoss = ret !== null && ret < 0;

  const positionPct =
    form.accountValueAtEntry && form.positionDollars
      ? (Number(form.positionDollars) / Number(form.accountValueAtEntry)) * 100
      : null;

  const impact =
    ret !== null && positionPct !== null ? (ret * positionPct) / 100 : null;

  const validate = () => {
    const e = {};
    if (!form.ticker) e.ticker = 'Required';
    if (!form.entryDate) e.entryDate = 'Required';
    if (!form.exitDate) e.exitDate = 'Required';
    if (form.entryDate && form.exitDate && new Date(form.exitDate) < new Date(form.entryDate))
      e.exitDate = 'Exit before entry';
    if (!form.entryPrice || form.entryPrice <= 0) e.entryPrice = 'Required';
    if (!form.exitPrice || form.exitPrice <= 0) e.exitPrice = 'Required';
    if (form.iv === '' || form.iv === null || form.iv === undefined || Number(form.iv) <= 0)
      e.iv = 'Required';
    if (!form.accountValueAtEntry || form.accountValueAtEntry <= 0)
      e.accountValueAtEntry = 'Required';
    if (!form.positionDollars || form.positionDollars <= 0) e.positionDollars = 'Required';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSave = () => {
    if (!validate()) return;
    const cleaned = {
      ...form,
      ticker: form.ticker.toUpperCase().trim(),
      entryPrice: Number(form.entryPrice),
      exitPrice: Number(form.exitPrice),
      iv: Number(form.iv),
      accountValueAtEntry: Number(form.accountValueAtEntry),
      positionDollars: Number(form.positionDollars),
      conviction: Number(form.conviction),
    };
    onSave(cleaned);
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="font-display text-3xl text-bone">
            {isEdit ? 'Edit trade' : 'New trade'}
          </h2>
          <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
            {isEdit ? 'update existing entry' : 'log a closed position'}
          </p>
        </div>
        <button onClick={onCancel} className="btn-ghost text-xs tracking-wider uppercase">
          Cancel
        </button>
      </div>

      <div className="card p-6 space-y-6">
        {/* Row 1: Ticker + dates */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Field label="Ticker" error={errors.ticker}>
            <input
              className="input uppercase"
              value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })}
              placeholder="AVGO"
            />
          </Field>
          <Field label="Entry date" error={errors.entryDate}>
            <input
              type="date"
              className="input"
              value={form.entryDate}
              onChange={(e) => setForm({ ...form, entryDate: e.target.value })}
            />
          </Field>
          <Field label="Exit date" error={errors.exitDate}>
            <input
              type="date"
              className="input"
              value={form.exitDate}
              onChange={(e) => setForm({ ...form, exitDate: e.target.value })}
            />
          </Field>
        </div>

        {/* Row 2: Prices */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field
            label="Entry price ($)"
            error={errors.entryPrice}
            hint={form.scaledInOut ? 'weighted avg from tranches' : undefined}
          >
            <div className="relative">
              <input
                type="number"
                step="any"
                className="input"
                value={form.entryPrice}
                onChange={numericField('entryPrice')}
                placeholder="377.92"
                style={
                  form.scaledInOut
                    ? { borderColor: 'var(--gold-dim)', color: 'var(--gold)' }
                    : undefined
                }
              />
              {form.scaledInOut && (
                <div className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-[9px] tracking-widest uppercase text-gold pointer-events-none">
                  auto
                </div>
              )}
            </div>
          </Field>
          <Field
            label="Exit price ($)"
            error={errors.exitPrice}
            hint={form.scaledInOut ? 'weighted avg from exit tranches' : undefined}
          >
            <div className="relative">
              <input
                type="number"
                step="any"
                className="input"
                value={form.exitPrice}
                onChange={numericField('exitPrice')}
                placeholder="390.46"
                style={
                  form.scaledInOut
                    ? { borderColor: 'var(--gold-dim)', color: 'var(--gold)' }
                    : undefined
                }
              />
              {form.scaledInOut && (
                <div className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-[9px] tracking-widest uppercase text-gold pointer-events-none">
                  auto
                </div>
              )}
            </div>
          </Field>
        </div>

        {/* Row 2b: Entry IV — captured at entry for later Luck Check use */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field
            label="Entry IV (%)"
            error={errors.iv}
            hint="implied vol at entry — used by Luck Check"
          >
            <input
              type="number"
              step="any"
              className="input"
              value={form.iv}
              onChange={numericField('iv')}
              placeholder="92"
            />
          </Field>
        </div>

        {/* Row 3: Account + position */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field
            label="Account value at entry ($)"
            error={errors.accountValueAtEntry}
            hint={
              accountAutoFilled && !isEdit
                ? 'auto-filled · editable'
                : 'total portfolio $ when you opened'
            }
          >
            <div className="relative">
              <input
                type="number"
                step="any"
                className="input"
                value={form.accountValueAtEntry}
                onChange={(e) => {
                  setAccountAutoFilled(false);
                  numericField('accountValueAtEntry')(e);
                }}
                placeholder="2597.62"
                style={
                  accountAutoFilled && !isEdit
                    ? { borderColor: 'var(--gold-dim)', color: 'var(--gold)' }
                    : undefined
                }
              />
              {accountAutoFilled && !isEdit && (
                <div
                  className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-[9px] tracking-widest uppercase text-gold pointer-events-none"
                >
                  auto
                </div>
              )}
            </div>
          </Field>
          <Field
            label="Position $ at entry"
            error={errors.positionDollars}
            hint={form.scaledInOut ? 'total from tranches' : 'shares × entry price'}
          >
            <div className="relative">
              <input
                type="number"
                step="any"
                className="input"
                value={form.positionDollars}
                onChange={numericField('positionDollars')}
                placeholder="577.92"
                style={
                  form.scaledInOut
                    ? { borderColor: 'var(--gold-dim)', color: 'var(--gold)' }
                    : undefined
                }
              />
              {form.scaledInOut && (
                <div className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-[9px] tracking-widest uppercase text-gold pointer-events-none">
                  auto
                </div>
              )}
            </div>
          </Field>
        </div>

        {/* Live preview */}
        {(ret !== null || positionPct !== null) && (
          <div className="bg-ink-soft rounded p-4 grid grid-cols-2 sm:grid-cols-4 gap-4">
            <LiveStat
              label="Trade return"
              value={ret !== null ? fmtPct(ret, 2) : '—'}
              tone={ret === null ? 'neutral' : ret >= 0 ? 'emerald' : 'crimson'}
            />
            <LiveStat
              label="Position size"
              value={positionPct !== null ? `${positionPct.toFixed(1)}%` : '—'}
              tone="neutral"
            />
            <LiveStat
              label="Account impact"
              value={impact !== null ? fmtPct(impact, 2) : '—'}
              tone={impact === null ? 'neutral' : impact >= 0 ? 'emerald' : 'crimson'}
            />
            <LiveStat
              label="Hold"
              value={
                form.entryDate && form.exitDate
                  ? `${daysBetween(form.entryDate, form.exitDate)}d`
                  : '—'
              }
              tone="neutral"
            />
          </div>
        )}

        <div className="hairline" />

        {/* Conviction */}
        <Field label="Conviction at entry" hint="1 = low · 5 = high">
          <div className="flex gap-2">
            {[1, 2, 3, 4, 5].map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => setForm({ ...form, conviction: level })}
                className={`flex-1 py-3 rounded border transition-colors font-mono ${
                  form.conviction === level ? 'text-gold' : 'border-rule text-bone-dim hover:text-bone'
                }`}
                style={
                  form.conviction === level
                    ? {
                        borderColor: 'var(--gold)',
                        backgroundColor: 'rgba(77, 184, 196, 0.15)',
                      }
                    : undefined
                }
              >
                {level}
              </button>
            ))}
          </div>
        </Field>

        {/* Setup type */}
        <Field label="Setup type">
          <div className="flex gap-2">
            {[
              { value: 'bounce', label: 'Bounce' },
              { value: 'breakout', label: 'Breakout' },
              { value: 'dip_buy', label: 'Dip Buy' },
            ].map((setup) => (
              <button
                key={setup.value}
                type="button"
                onClick={() => setForm({ ...form, setupType: setup.value })}
                className={`flex-1 py-3 rounded border transition-colors font-mono text-sm ${
                  form.setupType === setup.value ? 'text-gold' : 'border-rule text-bone-dim hover:text-bone'
                }`}
                style={
                  form.setupType === setup.value
                    ? {
                        borderColor: 'var(--gold)',
                        backgroundColor: 'rgba(77, 184, 196, 0.15)',
                      }
                    : undefined
                }
              >
                {setup.label}
              </button>
            ))}
          </div>
        </Field>

        {/* Checkboxes */}
        <div className="flex flex-wrap gap-6">
          <CheckField
            checked={form.scaledInOut}
            onChange={(v) => {
              const update = { ...form, scaledInOut: v };
              // Initialize tranches when toggling on
              if (v && (!form.tranches || form.tranches.length === 0)) {
                update.tranches = [
                  { price: form.entryPrice || '', dollars: form.positionDollars || '' },
                  { price: '', dollars: '' },
                ];
              }
              if (v && (!form.exitTranches || form.exitTranches.length === 0)) {
                update.exitTranches = [
                  { price: form.exitPrice || '', dollars: '' },
                  { price: '', dollars: '' },
                ];
              }
              setForm(update);
            }}
            label="Scaled in or out"
          />
          <CheckField
            checked={form.followedRules}
            onChange={(v) => setForm({ ...form, followedRules: v })}
            label="Followed my rules"
            tone={form.followedRules ? 'emerald' : 'crimson'}
            hint={
              form.followedRules
                ? 'Plan executed (regardless of outcome)'
                : 'Broke my own rules'
            }
          />
        </div>

        {/* Scale-in tranches */}
        {form.scaledInOut && (
          <TranchesSection
            label="Entry tranches"
            hint="entry price + position $ per add · weighted avg auto-fills above"
            tranches={form.tranches || []}
            onChange={(tranches) => {
              // Auto-compute weighted avg entry and total position $
              const valid = tranches.filter(
                (t) => t.price && t.dollars && Number(t.price) > 0 && Number(t.dollars) > 0
              );
              const weighted = computeWeightedAvg(
                valid.map((t) => ({ price: Number(t.price), dollars: Number(t.dollars) }))
              );
              const update = { ...form, tranches };
              if (weighted) {
                update.entryPrice = Number(weighted.avgPrice.toFixed(4));
                update.positionDollars = Number(weighted.totalDollars.toFixed(2));
              }
              setForm(update);
            }}
          />
        )}

        {/* Scale-out tranches */}
        {form.scaledInOut && (
          <TranchesSection
            label="Exit tranches"
            hint="exit price + $ sold per tranche · weighted avg auto-fills above"
            tranches={form.exitTranches || []}
            onChange={(exitTranches) => {
              // Auto-compute weighted avg exit
              const valid = exitTranches.filter(
                (t) => t.price && t.dollars && Number(t.price) > 0 && Number(t.dollars) > 0
              );
              const weighted = computeWeightedAvg(
                valid.map((t) => ({ price: Number(t.price), dollars: Number(t.dollars) }))
              );
              const update = { ...form, exitTranches };
              if (weighted) {
                update.exitPrice = Number(weighted.avgPrice.toFixed(4));
              }
              setForm(update);
            }}
          />
        )}

        {/* Notes */}
        <Field label="Notes" hint="optional">
          <textarea
            rows={2}
            className="input resize-none"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            placeholder="why did you take it? what did you learn?"
          />
        </Field>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 pt-2">
          <button onClick={onCancel} className="btn-ghost text-xs tracking-wider uppercase">
            Cancel
          </button>
          <button onClick={handleSave} className="btn-primary text-xs tracking-wider uppercase">
            {isEdit ? 'Update trade' : 'Save trade'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, error, children }) {
  return (
    <div>
      <label className="label-field">
        {label}
        {hint && <span className="ml-2 text-[10px] text-stone normal-case tracking-normal">· {hint}</span>}
      </label>
      {children}
      {error && (
        <p className="text-[11px] text-crimson mt-1 flex items-center gap-1">
          <AlertTriangle size={11} /> {error}
        </p>
      )}
    </div>
  );
}

function CheckField({ checked, onChange, label, hint, tone = 'gold' }) {
  const toneColor =
    tone === 'emerald'
      ? 'var(--emerald)'
      : tone === 'crimson'
      ? 'var(--crimson)'
      : 'var(--gold)';
  return (
    <label className="flex items-start gap-3 cursor-pointer group">
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`w-5 h-5 rounded border flex-shrink-0 flex items-center justify-center mt-0.5 transition-colors ${
          checked ? '' : 'border-rule'
        }`}
        style={{
          borderColor: checked ? toneColor : undefined,
          backgroundColor: checked ? toneColor : 'transparent',
        }}
      >
        {checked && <CheckCircle2 size={14} style={{ color: 'var(--ink)' }} />}
      </button>
      <div>
        <div className="text-bone text-sm">{label}</div>
        {hint && <div className="text-[11px] text-stone mt-0.5">{hint}</div>}
      </div>
    </label>
  );
}

function LiveStat({ label, value, tone }) {
  const colorClass =
    tone === 'emerald' ? 'text-emerald' : tone === 'crimson' ? 'text-crimson' : 'text-bone';
  return (
    <div>
      <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
        {label}
      </div>
      <div className={`font-mono font-medium ${colorClass}`}>{value}</div>
    </div>
  );
}

/* ───────────────────────── TRANCHES ───────────────────────── */

function TranchesSection({ tranches, onChange, label = 'Entry tranches', hint = '' }) {
  const updateTranche = (idx, key, val) => {
    const next = [...tranches];
    next[idx] = { ...next[idx], [key]: val === '' ? '' : Number(val) };
    onChange(next);
  };

  const addTranche = () => {
    onChange([...tranches, { price: '', dollars: '' }]);
  };

  const removeTranche = (idx) => {
    if (tranches.length <= 2) return;
    onChange(tranches.filter((_, i) => i !== idx));
  };

  // Compute weighted avg for display
  const valid = tranches.filter(
    (t) => t.price && t.dollars && Number(t.price) > 0 && Number(t.dollars) > 0
  );
  const weighted = computeWeightedAvg(
    valid.map((t) => ({ price: Number(t.price), dollars: Number(t.dollars) }))
  );

  return (
    <div className="card-raised p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="label-field" style={{ margin: 0 }}>{label}</div>
          {hint && (
            <div className="text-[11px] text-stone mt-0.5">
              {hint}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={addTranche}
          className="btn-ghost text-[10px] tracking-wider uppercase inline-flex items-center gap-1"
        >
          <Plus size={12} /> Add
        </button>
      </div>

      <div className="space-y-2">
        {tranches.map((t, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="font-mono text-[10px] text-stone w-4 text-right flex-shrink-0">
              {i + 1}
            </div>
            <input
              type="number"
              step="any"
              className="input flex-1"
              placeholder="Price"
              value={t.price}
              onChange={(e) => updateTranche(i, 'price', e.target.value)}
            />
            <input
              type="number"
              step="any"
              className="input flex-1"
              placeholder="Position $"
              value={t.dollars}
              onChange={(e) => updateTranche(i, 'dollars', e.target.value)}
            />
            {tranches.length > 2 && (
              <button
                type="button"
                onClick={() => removeTranche(i)}
                className="p-1 text-stone hover:text-crimson transition-colors flex-shrink-0"
              >
                <X size={14} />
              </button>
            )}
            {tranches.length <= 2 && <div className="w-6 flex-shrink-0" />}
          </div>
        ))}
      </div>

      {weighted && (
        <div className="mt-3 pt-3 flex items-center gap-4" style={{ borderTop: '1px solid var(--rule)' }}>
          <div>
            <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
              Weighted avg
            </div>
            <div className="font-mono text-gold">{fmtMoney(weighted.avgPrice)}</div>
          </div>
          <div>
            <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
              Total position
            </div>
            <div className="font-mono text-bone">{fmtMoney(weighted.totalDollars)}</div>
          </div>
          <div>
            <div className="text-[10px] text-stone font-mono tracking-widest uppercase">
              Shares
            </div>
            <div className="font-mono text-bone-dim">{weighted.totalShares.toFixed(4)}</div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ───────────────────────── SNAPSHOT MODAL ───────────────────────── */

function SnapshotModal({ snapshots, onAdd, onDelete, onClose, suggestedValue }) {
  const today = new Date().toISOString().split('T')[0];
  const [date, setDate] = useState(today);
  const [value, setValue] = useState('');
  const [error, setError] = useState(null);

  const sortedSnapshots = [...snapshots].sort(
    (a, b) => new Date(b.date) - new Date(a.date)
  );

  const handleAdd = () => {
    if (!date) {
      setError('Date required');
      return;
    }
    if (!value || Number(value) <= 0) {
      setError('Valid account value required');
      return;
    }
    onAdd(date, value);
  };

  return (
    <div className="fixed inset-0 modal-overlay backdrop-blur-sm z-30 flex items-center justify-center p-4 overflow-y-auto">
      <div className="card p-6 max-w-lg w-full my-8">
        <div className="flex items-start justify-between mb-2">
          <div>
            <h3 className="font-display text-2xl text-bone">Account snapshot</h3>
            <p className="text-[11px] text-stone font-mono tracking-widest uppercase mt-1">
              set the real value to correct drift
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-stone hover:text-bone transition-colors p-1"
          >
            <X size={18} />
          </button>
        </div>

        <p className="text-sm text-bone-dim mt-3 mb-5">
          Check IBKR for your current total portfolio value and enter it below. Future trades
          will auto-fill their account value from this baseline.
        </p>

        {suggestedValue !== null && (
          <div className="bg-ink-soft rounded p-3 mb-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-1">
                App's current estimate
              </div>
              <div className="font-mono text-bone">{fmtMoney(suggestedValue)}</div>
            </div>
            <div className="text-[11px] text-stone text-right max-w-[180px]">
              If IBKR differs from this, a snapshot will fix it going forward.
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <Field label="Date">
            <input
              type="date"
              className="input"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                setError(null);
              }}
              max={today}
            />
          </Field>
          <Field label="Account value ($)">
            <input
              type="number"
              step="any"
              className="input"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setError(null);
              }}
              placeholder="2700.00"
              autoFocus
            />
          </Field>
        </div>

        {error && (
          <p className="text-[11px] text-crimson mb-3 flex items-center gap-1">
            <AlertTriangle size={11} /> {error}
          </p>
        )}

        <div className="flex justify-end gap-2 mb-6">
          <button onClick={onClose} className="btn-ghost text-xs tracking-wider uppercase">
            Cancel
          </button>
          <button onClick={handleAdd} className="btn-primary text-xs tracking-wider uppercase">
            Save snapshot
          </button>
        </div>

        {sortedSnapshots.length > 0 && (
          <>
            <div className="hairline mb-4" />
            <div className="text-[10px] text-stone font-mono tracking-widest uppercase mb-3">
              Past snapshots ({sortedSnapshots.length})
            </div>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {sortedSnapshots.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center justify-between py-2 px-3 bg-ink-soft rounded group"
                >
                  <div>
                    <div className="font-mono text-sm text-bone">{fmtMoney(s.value)}</div>
                    <div className="font-mono text-[11px] text-stone">{s.date}</div>
                  </div>
                  <button
                    onClick={() => onDelete(s.id)}
                    className="p-1.5 text-stone hover:text-crimson transition-colors opacity-0 group-hover:opacity-100"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ───────────────────────── CONFIRM MODAL ───────────────────────── */

function ConfirmModal({ title, message, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 modal-overlay backdrop-blur-sm z-30 flex items-center justify-center p-4">
      <div className="card p-6 max-w-sm w-full">
        <h3 className="font-display text-xl text-bone mb-2">{title}</h3>
        <p className="text-bone-dim text-sm mb-6">{message}</p>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="btn-ghost text-xs tracking-wider uppercase">
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="btn-primary text-xs tracking-wider uppercase"
            style={{ background: 'var(--crimson)', color: 'var(--ink)' }}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
