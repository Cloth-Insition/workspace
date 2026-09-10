import { useEffect, useState } from "react";
import {
  getLedgerTrades,
  calculateLuck,
  type LedgerTrade,
  type LuckResult,
} from "../lib/luckApi";
import "../styles/rotation.css";
import "../styles/luck.css";

function pct(n: number, dp = 2) {
  return (n >= 0 ? "+" : "") + (n * 100).toFixed(dp) + "%";
}

/**
 * Format a p-value for the diagnostics row.
 *
 * Deliberately NOT converted to "X% chance this was luck" — a p-value is
 * P(results at least this extreme | no edge), not P(no edge | results). The
 * previous version showed the former under the latter's label, which made an
 * entirely ordinary run of trades read as a 50/50 coin flip between skill and
 * luck. The headline is now a verdict in words; the raw p lives here.
 */
function fmtP(p: number | null | undefined): string {
  if (p == null || isNaN(p)) return "—";
  if (p <= 0) return "<1e-12";
  if (p < 0.001) return p.toExponential(2);
  return p.toFixed(4);
}

/** Typed entry IV -> decimal. The column header says "%", so a value of 1 or
 *  more is read as a percent (92 -> 0.92). Below 1 it can only sensibly be a
 *  decimal already (0.92 -> 0.92), since no equity has sub-1% IV. The old
 *  boundary of 3 silently read a typed "3" as 300%. */
function normalizeIv(raw: number): number {
  return raw >= 1 ? raw / 100 : raw;
}

export function LuckView() {
  const [trades, setTrades] = useState<LedgerTrade[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [ivs, setIvs] = useState<Record<string, string>>({});
  const [result, setResult] = useState<LuckResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [calcing, setCalcing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getLedgerTrades()
      .then((t) => setTrades(t.filter((x) => x.exitDate && x.exitPrice)))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function toggle(id: string) {
    const trade = trades.find((t) => t.id === id);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    // Seed the IV input from the trade's stored IV (logged at entry) if present
    // and not already typed. Stored as a percent number (e.g. 92).
    if (trade && trade.iv != null && (ivs[id] === undefined || ivs[id] === "")) {
      setIvs((prev) => ({ ...prev, [id]: String(trade.iv) }));
    }
    setResult(null);
    setError(null);
  }

  const selectedTrades = trades.filter((t) => selected.has(t.id));
  const allIvsEntered = selectedTrades.every((t) => {
    const v = parseFloat(ivs[t.id]);
    return !isNaN(v) && v > 0;
  });

  async function calculate() {
    setCalcing(true);
    setResult(null);
    setError(null);
    try {
      const payload = selectedTrades.map((t) => ({
        ticker: t.ticker,
        entryDate: t.entryDate,
        exitDate: t.exitDate,
        entryPrice: t.entryPrice,
        exitPrice: t.exitPrice,
        iv: normalizeIv(parseFloat(ivs[t.id])),
      }));
      setResult(await calculateLuck(payload));
    } catch (e) {
      // Fail loudly — a silent null here used to look like "nothing happened".
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCalcing(false);
    }
  }

  if (loading) return <div className="rot-msg">Loading trades…</div>;

  return (
    <div className="rot">
      <div className="rot-head">
        <h1>Luck Check</h1>
        <span className="rot-stamp mono">{selected.size} selected</span>
      </div>

      <p className="luck-intro">
        Was a run of trades skill or variance? Pick trades, type the entry IV for
        each, and this scores how surprising your returns were given each name’s
        expected move — stripping out the market’s contribution — then combines
        them into a single test. <strong>Include losers</strong> for an honest
        number; winners-only is biased by construction.
      </p>

      {trades.length === 0 ? (
        <p className="rot-foot">No closed trades in Ledger yet.</p>
      ) : (
        <>
          <table className="rot-table luck-table">
            <thead>
              <tr>
                <th className="c-bd"></th>
                <th className="c-etf">ticker</th>
                <th className="c-date">entry</th>
                <th className="c-date">exit</th>
                <th className="c-num">return</th>
                <th className="c-num luck-iv-head">entry IV %</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const r = t.exitPrice / t.entryPrice - 1;
                const isSel = selected.has(t.id);
                return (
                  <tr key={t.id} className={isSel ? "luck-sel" : ""}>
                    <td className="c-bd">
                      <button
                        className={`luck-check ${isSel ? "on" : ""}`}
                        onClick={() => toggle(t.id)}
                        aria-label="select trade"
                      >
                        <i className={isSel ? "ti ti-square-check-filled" : "ti ti-square"} />
                      </button>
                    </td>
                    <td className="c-etf tick">{t.ticker}</td>
                    <td className="c-date date">{t.entryDate}</td>
                    <td className="c-date date">{t.exitDate}</td>
                    <td className={`c-num ${r >= 0 ? "up" : "down"}`}>{pct(r)}</td>
                    <td className="c-num">
                      {isSel ? (
                        <input
                          className="luck-iv-input mono"
                          placeholder="92"
                          value={ivs[t.id] ?? ""}
                          onChange={(e) =>
                            setIvs((prev) => ({ ...prev, [t.id]: e.target.value }))
                          }
                        />
                      ) : t.iv != null ? (
                        <span className="luck-iv-stored mono" title="logged at entry">
                          {t.iv}%
                        </span>
                      ) : (
                        <span className="luck-iv-dash">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="luck-actions">
            <button
              className={`rot-refresh ${calcing ? "spinning" : ""}`}
              onClick={calculate}
              disabled={selected.size === 0 || !allIvsEntered || calcing}
              title={
                selected.size === 0
                  ? "Select at least one trade"
                  : !allIvsEntered
                  ? "Enter IV for every selected trade"
                  : "Calculate"
              }
            >
              <i className="ti ti-dice" />
              {calcing ? "Scoring…" : "Calculate"}
            </button>
            {selected.size > 0 && !allIvsEntered && (
              <span className="luck-hint">Type the entry IV for each selected trade.</span>
            )}
          </div>
        </>
      )}

      {error && <div className="rot-msg rot-err">{error}</div>}
      {result && <LuckResultView result={result} />}
    </div>
  );
}

function LuckResultView({ result }: { result: LuckResult }) {
  // Muted direction language, consistent with the rest of the app: sea green
  // when the evidence points to edge, faded clay when it points the other way,
  // neutral when there's nothing to see.
  const tone =
    result.band === "none"
      ? "flat"
      : result.direction === "above"
      ? "edge"
      : "poor";

  const capped = result.trades.filter((t) => t.rho_capped);
  const unadjusted = result.trades.filter(
    (t) => !t.adjusted && !t.error && t.note
  );

  return (
    <div className="luck-result">
      <div className={`luck-verdict ${tone}`}>
        <span className="luck-verdict-word">{result.verdict}</span>
        <p className="luck-verdict-detail">{result.detail}</p>
      </div>

      {/* What THIS sample size can actually resolve. "No evidence of edge"
          means something completely different at n=6 than at n=200, so the
          verdict never travels without this. */}
      {result.sample_note && (
        <div className={`luck-sample ${result.resolvable ? "resolved" : ""}`}>
          <i className={`ti ${result.resolvable ? "ti-target-arrow" : "ti-ruler-measure"}`} />
          <p>{result.sample_note}</p>
        </div>
      )}

      {result.all_winners && (
        <div className="luck-warn">
          <i className="ti ti-alert-triangle" />
          <div>
            <strong>Winners only — selection bias.</strong> Every selected trade
            is a winner, so this result is biased favourably by construction. It
            is only a fair test of edge if you include losers and break-evens
            too. Treat it as a ceiling, not a verdict.
          </div>
        </div>
      )}

      {capped.length > 0 && (
        <div className="luck-warn luck-warn-soft">
          <i className="ti ti-info-circle" />
          <div>
            <strong>
              {capped.length} trade{capped.length === 1 ? "" : "s"} tracked the
              benchmark very closely.
            </strong>{" "}
            Their correlation was capped at 0.95 before the variance strip.
            Without the cap, a near-index name divides by an almost-zero
            residual sigma and manufactures a large z out of estimation noise.
            {capped.map((t) => ` ${t.ticker} (ρ ${t.rho?.toFixed(3)})`).join(",")}
          </div>
        </div>
      )}

      {unadjusted.length > 0 && (
        <div className="luck-warn luck-warn-soft">
          <i className="ti ti-info-circle" />
          <div>
            <strong>Not market-adjusted:</strong>{" "}
            {unadjusted.map((t) => `${t.ticker} — ${t.note}`).join(" ")}
          </div>
        </div>
      )}

      <div className="luck-combine mono">
        {/* Effect size first: mean z is the edge PER TRADE and does not grow
            with sample size, unlike combined Z which scales with sqrt(n). */}
        <span title="Average market-adjusted edge per trade, in sigmas. This is the effect size — it does not inflate as you add trades.">
          mean z/trade: {result.mean_z != null ? (result.mean_z >= 0 ? "+" : "") + result.mean_z.toFixed(3) : "—"}
        </span>
        <span title="Stouffer combined z = mean z × √n. Grows with sample size, so read it together with n.">
          combined Z: {result.z_combined != null ? result.z_combined.toFixed(3) : "—"}
        </span>
        <span>two-tailed p: {fmtP(result.p_two_tailed)}</span>
        <span>
          one-tailed p ({result.direction ?? "—"}): {fmtP(result.p_directional)}
        </span>
        <span>
          {result.n_winners}W · {result.n_losers}L
        </span>
        <span className="luck-secondary" title="Secondary diagnostic: Fisher answers 'is any ONE trade unusual', and one outlier can dominate it. Not the headline.">
          Fisher (2nd): {fmtP(result.fisher_p)}
        </span>
      </div>

      <table className="rot-table luck-breakdown">
        <thead>
          <tr>
            <th className="c-etf">ticker</th>
            <th className="c-num">return</th>
            <th className="c-num">IV</th>
            <th className="c-bd">bench</th>
            <th className="c-num">β</th>
            <th className="c-num">ρ</th>
            <th className="c-num">z raw</th>
            <th className="c-num">z adj</th>
            <th className="c-num">p</th>
          </tr>
        </thead>
        <tbody>
          {result.trades.map((t, i) => {
            const num = (v: number | null | undefined, dp = 2) =>
              v == null || isNaN(v as number) ? "—" : (v as number).toFixed(dp);
            if (t.error) {
              return (
                <tr key={i}>
                  <td className="c-etf tick">{t.ticker}</td>
                  <td className="c-num" colSpan={8} style={{ color: "var(--down)" }}>
                    {t.error}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={i} className={t.adjusted ? "" : "luck-row-unadj"}>
                <td className="c-etf tick">
                  {t.ticker}
                  {t.note && (
                    <span className="luck-flag" title={t.note}>
                      <i className="ti ti-info-circle" />
                    </span>
                  )}
                </td>
                <td className={`c-num ${t.r_actual >= 0 ? "up" : "down"}`}>
                  {pct(t.r_actual)}
                </td>
                <td className="c-num center">{num(t.iv * 100, 0)}%</td>
                <td className="c-bd">{t.benchmark ?? "—"}</td>
                <td className="c-num center">{num(t.beta)}</td>
                <td className={`c-num center ${t.rho_capped ? "luck-capped" : ""}`}>
                  {num(t.rho)}
                  {t.rho_capped && <span className="luck-cap-mark">↓</span>}
                </td>
                <td className="c-num center">{num(t.z_raw)}</td>
                <td className="c-num center">{num(t.z_adj)}</td>
                <td className="c-num center">
                  {t.p == null
                    ? "—"
                    : t.p < 0.001
                    ? t.p.toExponential(1)
                    : t.p.toFixed(3)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="luck-caveats">
        <span className="luck-caveats-label">read this before believing the number</span>
        <ul>
          {result.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
        <p className="luck-math-note">
          Per trade, <em>z adj</em> strips the market’s pull from both your
          return and the stock’s normal volatility (β on the mean, √(1−ρ²) on the
          variance). The trades are then combined with Stouffer’s method —
          Z&nbsp;=&nbsp;Σz∕√n — which tests whether your <em>average</em>
          market-adjusted return beats zero. Losers correctly cancel winners, and
          no single outlier can carry the result.
        </p>
      </div>
    </div>
  );
}
