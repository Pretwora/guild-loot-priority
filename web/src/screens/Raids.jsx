import { readableColor } from "../lib.js";

export default function Raids({ data, scope }) {
  const active = (data.scopes || []).find((s) => s.key === scope) || { nights: data.nights };
  const byId = Object.fromEntries(data.players.map((p) => [p.id, p]));
  return (
    <>
      <h2 className="screen">Рейды</h2>
      <p className="sub">История рейд-вечеров{scope !== "all" ? ` (${active.label})` : ""}: кто был, кто в бенче, кто не пришёл. Границы вечера — по серверному времени, разрыв больше 3 часов рвёт на два.</p>
      {active.nights.map((n) => (
        <div className="night" key={n.date + n.started_at}>
          <header>
            <span className="date">{n.date}</span>
            <span className="meta num">{n.started_at}–{n.ended_at}</span>
            <span className="meta">состав {n.size ?? "?"}</span>
            <span className="meta num">килов {n.kill_count}</span>
            <span className="meta">{n.bosses.slice(0, 6).join(", ")}{n.bosses.length > 6 ? "…" : ""}</span>
          </header>
          <div className="roster">
            <Group label={`Присутствовали (${n.present.length})`} ids={n.present.map((x) => x.id)} byId={byId}
                   extra={(id) => { const pr = n.present.find((x) => x.id === id)?.presence; return pr != null && pr < 1 ? ` ${Math.round(pr * 100)}%` : ""; }} />
            {n.bench.length > 0 && <Group label={`Бенч (${n.bench.length})`} ids={n.bench} byId={byId} />}
            {n.late.length > 0 && <Group label={`Опоздали (${n.late.length})`} ids={n.late} byId={byId} />}
            {n.excused.length > 0 && <Group label={`Отпросились (${n.excused.length})`} ids={n.excused} byId={byId} />}
          </div>
        </div>
      ))}
    </>
  );
}

function Group({ label, ids, byId, extra }) {
  return (
    <div>
      <div className="grp-label">{label}</div>
      {ids.map((id) => {
        const p = byId[id];
        const color = p ? readableColor(p.class_color) : "var(--ink)";
        return (
          <div key={id} className="pill">
            <span style={{ color }}>{p ? p.display : id}</span>
            {extra ? <span className="num" style={{ color: "var(--ink-faint)" }}>{extra(id)}</span> : null}
          </div>
        );
      })}
    </div>
  );
}
