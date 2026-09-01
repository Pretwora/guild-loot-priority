import { useEffect, useState } from "react";
import { setColorTheme } from "./lib.js";
import Priority from "./screens/Priority.jsx";
import LootBoard from "./screens/LootBoard.jsx";
import Raids from "./screens/Raids.jsx";
import PlayerCard from "./screens/Player.jsx";
import HowItWorks from "./screens/HowItWorks.jsx";

const TABS = [
  ["priority", "Приоритет"],
  ["loot", "Лут-борд"],
  ["raids", "Рейды"],
  ["how", "Как считается"],
];

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("priority");
  const [player, setPlayer] = useState(null); // id для экрана «Игрок»
  const [scope, setScope] = useState("25"); // ладдер по умолчанию — РТ 25 (посещаемость всегда по 25)
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("loot-theme")
        || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    } catch { return "dark"; }
  });

  // применяем тему до рендера детей — readableColor читает её при отрисовке
  setColorTheme(theme);

  useEffect(() => {
    try {
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("loot-theme", theme);
    } catch { /* приватный режим — не критично */ }
  }, [theme]);

  useEffect(() => {
    fetch("./dashboard.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("dashboard.json " + r.status); return r.json(); })
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="error">Не загрузился dashboard.json: {error}</div>;
  if (!data) return <div className="loading">Загрузка…</div>;

  const openPlayer = (id) => { setPlayer(id); setTab("player"); };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Приоритет лута
          <small>
            гильдия {data.meta.guild_id} · {data.meta.realm} · тир {data.meta.tier} ·
            собрано {data.generated_at}
          </small>
        </div>
        <nav className="tabs" aria-label="Экраны">
          {TABS.map(([id, label]) => (
            <button key={id} aria-current={tab === id} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
          {tab === "player" && (
            <button aria-current={true} onClick={() => setTab("player")}>Игрок</button>
          )}
        </nav>
        <button className="theme-toggle" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
                aria-label={theme === "dark" ? "Переключить на светлую тему" : "Переключить на тёмную тему"}
                title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}>
          {theme === "dark" ? "☀︎" : "☾"}
        </button>
      </header>

      <main className="content">
        <IssuesBar issues={data.issues} meta={data.meta} onOpen={() => setTab("raids")} />
        {(tab === "priority" || tab === "raids") && data.scopes && (
          <ScopeSwitch scopes={data.scopes} scope={scope} setScope={setScope} />
        )}
        {tab === "priority" && <Priority data={data} scope={scope} onOpenPlayer={openPlayer} />}
        {tab === "loot" && <LootBoard data={data} onOpenPlayer={openPlayer} />}
        {tab === "raids" && <Raids data={data} scope={scope} />}
        {tab === "how" && <HowItWorks data={data} />}
        {tab === "player" && <PlayerCard data={data} scope={scope} playerId={player} onOpenPlayer={openPlayer} />}
      </main>
    </div>
  );
}

function ScopeSwitch({ scopes, scope, setScope }) {
  return (
    <div className="scope-switch" role="tablist" aria-label="Ладдер по составу">
      {scopes.map((s) => (
        <button key={s.key} role="tab" aria-selected={scope === s.key}
                onClick={() => setScope(s.key)}>
          {s.label} <span className="num">({s.kills_counted})</span>
        </button>
      ))}
    </div>
  );
}

function IssuesBar({ issues, meta }) {
  const unknown = issues.unknown_characters?.filter((u) => !u.is_pug).length || 0;
  const pugs = issues.unknown_characters?.filter((u) => u.is_pug).length || 0;
  const unmarked = issues.unmarked_items?.length || 0;
  const unclosed = issues.unclosed_count || 0;
  const auto = issues.loot_auto_count || 0;
  const ambiguous = issues.loot_ambiguous?.length || 0;
  const signupUnmatched = issues.signup_unmatched?.length || 0;
  const combat = meta.combat || {};
  return (
    <div className="issues">
      <span className="chip">килов зачтено: <b>{meta.kills_counted}</b> из {meta.kills_total}</span>
      {combat.kills_with_log != null && (
        <span className="chip">боевые логи: <b>{combat.kills_with_log}</b>/{combat.kills_counted}</span>
      )}
      {auto > 0 && <span className="chip">лут распознан автоматически: <b>{auto}</b></span>}
      {unclosed > 0 && <span className="chip alert">незакрытых дропов: <b>{unclosed}</b></span>}
      {ambiguous > 0 && <span className="chip alert">спорная атрибуция: <b>{ambiguous}</b></span>}
      {unknown > 0 && <span className="chip alert">в ростер: <b>{unknown}</b></span>}
      {unmarked > 0 && <span className="chip alert">размётка предметов: <b>{unmarked}</b></span>}
      {signupUnmatched > 0 && <span className="chip alert">записи без ростера: <b>{signupUnmatched}</b></span>}
      {pugs > 0 && <span className="chip">пугов вне ростера: <b>{pugs}</b></span>}
    </div>
  );
}
