import { readableColor, pct, f1, f2, deltaClass, deltaText } from "../lib.js";
import { RankBadge } from "./Priority.jsx";

const STATE_LABEL = {
  full: "был", partial: "частично", bench: "бенч", late: "опоздал",
  absent: "не пришёл", excused: "отпросился", "excused>2": "отпросился (3-й подряд)",
  team_off: "играла другая команда",
};

export default function PlayerCard({ data, playerId, onOpenPlayer }) {
  const p = data.players.find((x) => x.id === playerId) || data.players[0];
  if (!p) return <p className="sub">Нет данных.</p>;
  const w = data.formula.weights;
  const color = readableColor(p.class_color);
  const c = p.components;

  return (
    <>
      <h2 className="screen" style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span style={{ color }}>{p.display}</span>
        <span className="spec">{p.class_name} · {p.spec_name}</span>
        <RankBadge rank={p.rank} />
      </h2>
      <p className="sub">
        Карточка игрока. Каждое число объяснимо одной фразой — на этом система и держится.
        {" "}Другой игрок:{" "}
        <select value={p.id} onChange={(e) => onOpenPlayer(e.target.value)}
                style={{ background: "var(--bg-panel)", color: "var(--ink)", border: "1px solid var(--line-strong)", borderRadius: 4, padding: "2px 6px" }}>
          {[...data.players].sort((a, b) => a.display.localeCompare(b.display, "ru")).map((x) => (
            <option key={x.id} value={x.id}>{x.display}</option>
          ))}
        </select>
      </p>

      <div className="grid2">
        <div className="panel">
          <h3>Итоговый рейтинг</h3>
          <div className="body">
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 10 }}>
              <span className="score num" style={{ fontSize: 26 }}>{f1(p.score)}</span>
              <span className={"num delta " + deltaClass(p.delta)}>{deltaText(p.delta)} с прошлого рейда</span>
            </div>
            <div className="formula-block">
              S = {w.score.scale} × ({w.score.w_attendance}·A_eff + {w.score.w_perf}·P) / (1 + {w.score.loot_penalty_k}·L_norm) × gate<br />
              &nbsp;&nbsp;= {w.score.scale} × ({w.score.w_attendance}·{f2(c.A_eff)} + {w.score.w_perf}·{f2(c.P)}) / (1 + {w.score.loot_penalty_k}·{f2(c.L_norm)}) × {p.rank_gate}<br />
              &nbsp;&nbsp;= <b>{f1(p.score)}</b>
            </div>
            {p.adjustments?.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div className="grp-label">Ручные корректировки совета</div>
                {p.adjustments.map((a, i) => (
                  <div key={i} className="reason">{a.type} {a.value ?? ""} — {a.reason} {a.expires ? `(до ${a.expires})` : ""}</div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          <h3>Компоненты</h3>
          <div className="body">
            <dl className="kv">
              <dt>Посещаемость A_eff</dt><dd className="num">{pct(c.A_eff)} <span className="reason">(A={pct(p.attendance.A)}, сжатие conf={f2(p.attendance.conf)} к медиане {pct(p.attendance.A_median_guild)})</span></dd>
              <dt>Перформанс P</dt><dd className="num">{pct(c.P)} <span className="reason">{p.performance.neutral_fallback ? "мало данных → нейтрально" : `медиана перцентилей за ${p.performance.kills_counted} килов`}</span></dd>
              <dt>Лут L_norm</dt><dd className="num">{f2(c.L_norm)} <span className="reason">чем больше уже получил, тем ниже приоритет</span></dd>
              <dt>Ранг-гейт</dt><dd className="num">{p.rank_gate}</dd>
            </dl>
          </div>
        </div>

        <div className="panel">
          <h3>Посещаемость по вечерам (окно)</h3>
          <div className="body">
            <table style={{ fontSize: 12 }}>
              <tbody>
                {p.attendance.detail.slice().reverse().map((d, i) => (
                  <tr key={i}>
                    <td className="num">{d.date}</td>
                    <td className="reason">{STATE_LABEL[d.state] || d.state}</td>
                    <td className="num r">{d.credit == null ? "—" : d.credit}</td>
                    <td className="num r" style={{ color: "var(--ink-faint)" }}>вес {d.weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <h3>Перформанс по последним килам</h3>
          <div className="body">
            {p.performance.recent.length === 0 ? <div className="reason">Нет килов в зачёте.</div> : (
              <table style={{ fontSize: 12 }}>
                <tbody>
                  {p.performance.recent.slice().reverse().map((m, i) => (
                    <tr key={i}>
                      <td>{m.boss}</td>
                      <td className="reason">{m.role}{m.role === "tank" ? " (нейтрально)" : ""}</td>
                      <td className="num r">{pct(m.p)}</td>
                      <td className="num r" style={{ color: "var(--ink-faint)" }}>{m.n ? `n=${m.n}` : ""} {"metric" in m && m.metric != null ? `· ${m.metric}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel">
          <h3>Полученный лут</h3>
          <div className="body">
            {p.loot.awards.length === 0 ? <div className="reason">Пока ничего не получено.</div> : (
              <table style={{ fontSize: 12 }}>
                <tbody>
                  {p.loot.awards.map((a, i) => (
                    <tr key={i}>
                      <td className="num">{a.date}</td>
                      <td>{a.item}</td>
                      <td className="reason">{a.slot} · {a.award_type} ×{a.mult}</td>
                      <td>{a.source === "auto"
                        ? <span className="badge" title="Распознано по ленте действий">авто</span>
                        : <span className="badge officer" title="Внесено вручную">рука</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
