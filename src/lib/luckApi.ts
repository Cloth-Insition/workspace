// Luck Check API — reads trades from Ledger, runs the skill-vs-variance calc.

const BASE = "http://127.0.0.1:8765";

export interface LedgerTrade {
  id: string;
  ticker: string;
  entryDate: string;
  exitDate: string;
  entryPrice: number;
  exitPrice: number;
  iv?: number; // entry IV as a percent number (e.g. 92), if logged
  [k: string]: unknown;
}

export interface LuckTradeResult {
  ticker: string;
  entryDate: string;
  exitDate: string;
  iv: number;
  r_actual: number;
  trading_days: number | null;
  sigma_hold: number | null;
  z_raw: number | null;
  benchmark: string | null;
  beta: number | null;
  rho: number | null;
  /** rho after the RHO_CAP clamp — what the variance strip actually used. */
  rho_used: number | null;
  /** True when |rho| exceeded the cap, i.e. the residual is mostly noise. */
  rho_capped: boolean;
  bench_return?: number;
  r_market: number | null;
  r_resid: number | null;
  sigma_resid: number | null;
  beta_obs?: number;
  z_adj: number | null;
  z_mean_only?: number;
  p: number | null;
  p_raw?: number;
  adjusted: boolean;
  note?: string | null;
  error: string | null;
}

export type LuckBand =
  | "extraordinary"
  | "very_strong"
  | "strong"
  | "moderate"
  | "weak"
  | "none";

export interface LuckResult {
  trades: LuckTradeResult[];
  n: number;
  n_winners: number;
  n_losers: number;
  all_winners: boolean;
  /** Stouffer combined z: sum(z_adj)/sqrt(n). Standard normal under the null. */
  z_combined: number | null;
  mean_z: number | null;
  /** Two-tailed p on z_combined — drives the strength band. */
  p_two_tailed: number | null;
  /** One-tailed p in the observed direction — quoted in the detail sentence. */
  p_directional: number | null;
  direction: "above" | "below" | null;
  band: LuckBand;
  verdict: string;
  detail: string;
  /** Secondary diagnostic only: answers "is any ONE trade unusual", and is
   *  driven by outliers. Not the headline. */
  fisher_p: number | null;
  /** Smallest |mean z| this sample size could resolve at p<0.05 (1.96/sqrt(n)). */
  detection_floor: number | null;
  /** Trades needed for 80% power at the effect size actually observed. */
  n_for_power: number | null;
  effect_label: string | null;
  /** True when the observed effect clears the detection floor. */
  resolvable: boolean;
  /** Plain-language read of what this sample can and cannot show. */
  sample_note: string;
  caveats: string[];
}

export async function getLedgerTrades(): Promise<LedgerTrade[]> {
  const res = await fetch(`${BASE}/ledger/trades`);
  const data = await res.json();
  return (data.trades || []) as LedgerTrade[];
}

export async function calculateLuck(
  trades: { ticker: string; entryDate: string; exitDate: string; entryPrice: number; exitPrice: number; iv: number }[]
): Promise<LuckResult> {
  const res = await fetch(`${BASE}/luck/calculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trades }),
  });
  if (!res.ok) throw new Error(`luck calc failed: ${res.status}`);
  return res.json();
}
