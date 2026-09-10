import { useState } from "react";
import "../styles/calendar.css";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ymd(y: number, m: number, d: number) {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/**
 * Two-click range picker, ported from rotation.py's interactive calendar.
 *
 * First click sets the start (and clears the end). Second click sets the end,
 * auto-ordering if you picked an earlier date second. Trading days are
 * clickable; weekends/holidays render but are inert. The selected span
 * highlights, and month nav lets you move back/forward.
 *
 * `tradingDates` is the sorted list of dates that actually have price data —
 * the union of all ETF series, same as the original.
 */
export function Calendar({
  tradingDates,
  start,
  end,
  onChange,
}: {
  tradingDates: string[];
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}) {
  const tradingSet = new Set(tradingDates);
  const last = tradingDates[tradingDates.length - 1].split("-");
  const [viewYear, setViewYear] = useState(parseInt(last[0]));
  const [viewMonth, setViewMonth] = useState(parseInt(last[1]) - 1);
  const [awaitingEnd, setAwaitingEnd] = useState(false);

  function pick(ds: string) {
    if (!awaitingEnd) {
      onChange(ds, ds);
      setAwaitingEnd(true);
    } else {
      if (ds < start) onChange(ds, start);
      else onChange(start, ds);
      setAwaitingEnd(false);
    }
  }

  function prevMonth() {
    let m = viewMonth - 1, y = viewYear;
    if (m < 0) { m = 11; y--; }
    setViewMonth(m);
    setViewYear(y);
  }
  function nextMonth() {
    let m = viewMonth + 1, y = viewYear;
    if (m > 11) { m = 0; y++; }
    setViewMonth(m);
    setViewYear(y);
  }

  const firstDow = (new Date(viewYear, viewMonth, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const cells: React.ReactNode[] = [];
  for (let i = 0; i < firstDow; i++) {
    cells.push(<div key={`e${i}`} className="cal-day empty" />);
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = ymd(viewYear, viewMonth, d);
    if (tradingSet.has(ds)) {
      let cls = "cal-day trade";
      if (ds === start || ds === end) cls = "cal-day endpoint";
      else if (ds > start && ds < end) cls = "cal-day inrange";
      cells.push(
        <div key={ds} className={cls} onClick={() => pick(ds)}>
          {d}
        </div>
      );
    } else {
      cells.push(
        <div key={ds} className="cal-day notrade">
          {d}
        </div>
      );
    }
  }

  const sessions = tradingDates.filter((d) => d >= start && d <= end).length - 1;

  return (
    <div className="cal">
      <div className="cal-top">
        <button className="cal-nav" onClick={prevMonth} aria-label="Previous month">
          <i className="ti ti-chevron-left" />
        </button>
        <span className="cal-month">{MONTHS[viewMonth]} {viewYear}</span>
        <button className="cal-nav" onClick={nextMonth} aria-label="Next month">
          <i className="ti ti-chevron-right" />
        </button>
      </div>

      <div className="cal-grid">
        {DOW.map((d) => (
          <div key={d} className="cal-dow">{d}</div>
        ))}
        {cells}
      </div>

      <div className="cal-foot">
        <span className="cal-hint">
          {awaitingEnd ? "Now click the end date" : "Click a start date, then an end date"}
        </span>
        <span className="cal-span mono">
          {start} → {end} · {sessions} {sessions === 1 ? "session" : "sessions"}
        </span>
      </div>
    </div>
  );
}
