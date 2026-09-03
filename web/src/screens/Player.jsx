import { readableColor, pct, f1, f2, deltaClass, deltaText, deltaPartsList } from "../lib.js";
import { RankBadge, LootIcons } from "./Priority.jsx";

const ROLE_RU = { tank: "танк", heal: "хил", dps: "дпс" };

const STATE_LABEL = {
  full: "был", partial: "частично", bench: "бенч", late: "опоздал",
  absent: "не пришёл", excused: "отпросился", "excused>2": "отпросился (3-й подряд)",
  team_off: "играла другая команда",
  before_join: "до вступления",
};

export default function PlayerCard({ data, scope, playerId, onOpenPlayer }) {
  // карточка следует активному ладдеру (перформанс/лут/Δ различаются по скоупу)
  const scopePlayers = (data.scopes || []).find((s) => s.key === scope)?.players || data.players;
  const p = scopePlayers.find((x) => x.id === playerId) || scopePlayers[0];
  if (!p) return <p className="sub">Нет данных.</p>;
  const w = data.formula.weights;
  const color = readableColor(p.class_color);
  const c = p.components;

  // разбивка посещаемости: зачётные (знаменатель), посещённые, до вступления, вне счёта
  const att = p.attendance;
  const det = att.detail || [];
  const excludedStates = ["before_join", "team_off", "excused"];
  const beforeJoin = det.filter((d) => d.state === "before_join").length;
  const excluded = det.filter((d) => excludedStates.includes(d.state)).length;
  const attended = det.filter((d) => d.credit != null && d.credit > 0).length;
  const eligible = det.length - excluded;

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
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 4 }}>
              <span className="score num" style={{ fontSize: 26 }}>{f1(p.score)}</span>
              <span className={"num delta " + deltaClass(p.delta)}>{deltaText(p.delta)} с прошлого рейда</span>
            </div>
            {deltaPartsList(p.delta_parts).length > 0 && (
              <div className="reason" style={{ marginBottom: 10 }}>
                из чего Δ:{" "}
                {deltaPartsList(p.delta_parts).map((x, i) => (
                  <span key={x.key}>
                    {i > 0 ? " · " : ""}{x.label}{" "}
                    <span className={"num delta " + (x.value > 0 ? "up" : "down")}>
                      {x.value > 0 ? "+" : ""}{x.value.toFixed(1)}
                    </span>
                  </span>
                ))}
              </div>
            )}
            {p.perf_measured ? (
              <div className="formula-block">
                S = {w.score.scale} × ({w.score.w_attendance}·A_eff + {w.score.w_perf}·P) × gate<br />
                &nbsp;&nbsp;= {w.score.scale} × ({w.score.w_attendance}·{f2(c.A_eff)} + {w.score.w_perf}·{f2(c.P)}) × {p.rank_gate}<br />
                &nbsp;&nbsp;= <b>{f1(p.score)}</b>
              </div>
            ) : (
              <div className="formula-block">
                S = {w.score.scale} × A_eff × gate&nbsp;&nbsp;<span style={{ color: "var(--ink-faint)" }}>// перформанс не применяется (танк/хил)</span><br />
                &nbsp;&nbsp;= {w.score.scale} × {f2(c.A_eff)} × {p.rank_gate}<br />
                &nbsp;&nbsp;= <b>{f1(p.score)}</b>
              </div>
            )}
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
              <dt>Посещаемость A_eff</dt><dd className="num">{att.no_raid_data
                ? <span className="reason">нет 25-к — не был ни разу</span>
                : <>{pct(c.A_eff)} <span className="reason">(факт {pct(att.A)}; стаж {attended} рейд., доверие {f2(att.conf)} → сжатие к медиане {pct(att.A_median_guild)})</span></>}</dd>
              <dt>Перформанс P</dt><dd className="num">{p.perf_measured
                ? <>{pct(c.P)} <span className="reason">{p.performance.neutral_fallback ? "мало данных → нейтрально" : `медиана перцентилей за ${p.performance.kills_counted} килов`}</span></>
                : <span className="reason">не применяется — {ROLE_RU[p.performance.role] || "роль"} судится по посещаемости (слишком ситуативно)</span>}</dd>
              <dt>Ранг-гейт</dt><dd className="num">{p.rank_gate}</dd>
              {p.signup_bonus > 0 && (<><dt>Запись на рейд</dt><dd className="num delta up">+{p.signup_bonus} <span className="reason">бонус за запись (raid-helper)</span></dd></>)}
              {p.signup_bonus < 0 && (<><dt>Запись на рейд</dt><dd className="num delta down">{p.signup_bonus} <span className="reason">штраф — не отметился на РТ в raid-helper</span></dd></>)}
            </dl>
          </div>
        </div>

        <div className="panel">
          <h3>Полученный лут <span className="reason" style={{ fontWeight: 400 }}>· последние 3 КД · на рейтинг не влияет</span></h3>
          <div className="body">
            {p.recent_loot?.length ? (
              <ul className="loot-list">
                {p.recent_loot.map((it, i) => (
                  <li key={i}>
                    {it.icon
                      ? <img className="loot-icon" src={it.icon} alt="" loading="lazy" />
                      : <span className="loot-icon noimg">{(it.item || "?")[0]}</span>}
                    <span className="loot-name">{it.item}</span>
                    <span className="reason">{it.boss ? it.boss + " · " : ""}КД {it.date}</span>
                  </li>
                ))}
              </ul>
            ) : <div className="reason">За последние 3 КД ничего не получал.</div>}
          </div>
        </div>

        <div className="panel">
          <h3>Посещаемость по вечерам (окно)</h3>
          <div className="body">
            <div className="reason" style={{ marginBottom: 8 }}>
              {eligible === 0 ? (
                <>Не был ни на одной 25-ке{beforeJoin > 0 ? ` · ${beforeJoin} рейдов до вступления` : ""}</>
              ) : (
                <>Посещено <b style={{ color: "var(--ink)" }}>{attended} из {eligible}</b>
                  {beforeJoin > 0 ? ` · ${beforeJoin} до вступления` : ""}
                  {excluded - beforeJoin > 0 ? ` · ${excluded - beforeJoin} вне счёта` : ""}</>
              )}
            </div>
            <div className="table-scroll">
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
        </div>

        <div className="panel">
          <h3>Перформанс по последним килам</h3>
          <div className="body">
            {!p.perf_measured && p.performance.recent.length > 0 && (
              <div className="reason" style={{ marginBottom: 8 }}>
                Справочно — в рейтинг не идёт: {ROLE_RU[p.performance.role] || "роль"} по перформансу не оценивается.
              </div>
            )}
            {p.performance.recent.length === 0 ? <div className="reason">Нет килов в зачёте.</div> : (
              <div className="table-scroll">
              <table style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Босс</th><th>Роль</th><th className="r">База</th>
                    <th className="r" title="Перебивания + диспелы">Утил</th>
                    <th className="c" title="Смерти в бою">†</th><th className="r">Итог</th>
                  </tr>
                </thead>
                <tbody>
                  {p.performance.recent.slice().reverse().map((m, i) => (
                    <tr key={i}>
                      <td>{m.boss}</td>
                      <td className="reason">
                        {ROLE_RU[m.role] || m.role}
                        {m.role === "tank" && m.taken_ps != null ? <span style={{ color: "var(--ink-faint)" }}> · {Math.round(m.taken_ps)}/с</span> : null}
                      </td>
                      <td className="num r">{m.base != null ? pct(m.base) : "—"}{m.n ? <span style={{ color: "var(--ink-faint)" }} title="размер пула"> n{m.n}</span> : null}</td>
                      <td className="num r" title={`${m.utility || 0} перебиваний/диспелов`}>
                        {m.util_bonus > 0 ? <span className="delta up">+{Math.round(m.util_bonus * 100)}</span> : (m.utility ? m.utility : "")}
                      </td>
                      <td className="c num">{m.deaths > 0 ? <span className="delta down">{m.deaths}</span> : ""}</td>
                      <td className="num r" style={{ fontWeight: 600 }}>{pct(m.p)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </div>
        </div>

      </div>
    </>
  );
}
