import { useEffect, useState } from "react";
import { checkHealth } from "./lib/api";
import { Sidebar, type ToolId } from "./Sidebar";
import { RotationView } from "./tools/RotationView";
import { ListsView } from "./tools/ListsView";
import { LevelsView } from "./tools/LevelsView";
import { LuckView } from "./tools/LuckView";
import { FxView } from "./tools/FxView";
import { RotationProvider } from "./lib/rotationStore";
// @ts-expect-error — Ledger is a .jsx file ported from the original, no types
import Ledger from "./tools/Ledger.jsx";
import "./styles/tokens.css";
import "./styles/shell.css";

export default function App() {
  const [active, setActive] = useState<ToolId>("rotation");
  const [ready, setReady] = useState<boolean | null>(null);

  // Poll the sidecar on startup. Tauri spawns it in parallel with the webview,
  // so it may take a moment to come up. Show an honest "starting" state until
  // the health check passes rather than letting a tool render against a dead
  // backend.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const ok = await checkHealth();
      if (cancelled) return;
      if (ok) setReady(true);
      else {
        setReady(false);
        setTimeout(tick, 800);
      }
    };
    tick();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="shell">
      <Sidebar active={active} onSelect={setActive} ready={ready} />
      <main className="content">
        {ready === false && (
          <div className="boot">
            <span className="boot-dot" />
            Starting engine…
          </div>
        )}
        {ready === true && (
          // Provider lives above the tabs and stays mounted as you switch, so
          // rotation data, drill position, and calendar range survive. Mounted
          // only once the sidecar is up so its startup cache-fetch has a live
          // backend to hit.
          <RotationProvider>
            <div style={{ display: active === "rotation" ? "block" : "none", height: "100%" }}>
              <RotationView />
            </div>
            {active === "levels" && <LevelsView />}
            {active === "ledger" && <Ledger />}
            {active === "luck" && <LuckView />}
            {active === "fx" && <FxView />}
            {active === "lists" && <ListsView />}
          </RotationProvider>
        )}
      </main>
    </div>
  );
}
