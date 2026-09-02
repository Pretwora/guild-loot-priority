import { readableColor, f1, f2 } from "../lib.js";
import { PlayerName } from "./Priority.jsx";

const SLOT_LABEL = {
  head: "Гол", neck: "Шея", shoulder: "Плч", back: "Плащ", chest: "Грудь", wrist: "Нар",
  hands: "Рук", waist: "Пояс", legs: "Ноги", feet: "Бот", finger: "Кольцо", trinket: "Трин",
  one_hand: "1H", two_hand: "2H", ranged: "Даль",
};

function recencyClass(dateStr) {
  if (!dateStr) return "recv-none";
  const days = (Date.now() - new Date(dateStr).getTime()) / 86400000;
  if (days <= 56) return "recv-recent";
  if (days <= 112) return "recv-mid";
  return "recv-old";
}

export default function LootBoard({ data, onOpenPlayer }) {
  const { slots, players } = data.lootboard;
  return (
    <>
      <h2 className="screen">Лут-борд</h2>
      <p className="sub">
        Матрица «слот × игрок»: <span className="dot recv-recent" /> недавно закрыт,{" "}
        <span className="dot recv-mid" /> давно, <span className="dot recv-none" /> ещё нужен.
        Ниже — незакрытые дропы с кандидатами по <b>S×F</b> и расшифровкой.
      </p>

      <div className="table-wrap" style={{ marginBottom: 20 }}>
        <table className="matrix">
          <thead>
            <tr>
              <th>Игрок</th>
              <th className="r">Рейтинг</th>
              {slots.map((s) => <th key={s} className="c" title={s}>{SLOT_LABEL[s] || s}</th>)}
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <tr key={p.id} className="clickable" onClick={() => onOpenPlayer(p.id)}>
                <td className="player" style={{ "--klass": readableColor(p.class_color) }}>
                  <span className="pname" style={{ color: readableColor(p.class_color) }}>{p.display}</span>
                </td>
                <td className="r num">{f1(p.score)}</td>
                {slots.map((s) => (
                  <td key={s} className="cell" title={p.per_slot[s] ? `выдано ${p.per_slot[s]}` : "нужен"}>
                    <span className={"dot " + recencyClass(p.per_slot[s])} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ margin: "6px 0 10px", fontSize: 14 }}>
        Незакрытые дропы <span className="num" style={{ color: "var(--ink-faint)" }}>({data.unclosed_drops.length})</span>
      </h3>
      <div className="grid2">
        {data.unclosed_drops.slice(0, 60).map((d) => (
          <Drop key={d.record_id + "-" + d.entry} d={d} onOpenPlayer={onOpenPlayer} />
        ))}
      </div>
    </>
  );
}

function Drop({ d, onOpenPlayer }) {
  return (
    <div className="panel">
      <h3>
        {d.icon ? <img src={d.icon} alt="" width="18" height="18" style={{ verticalAlign: "-4px", marginRight: 6, borderRadius: 3 }} /> : null}
        {d.item}
        {d.ambiguous && <span title="Требует ручной разметки" className="frozen-mark"> ⚑</span>}
      </h3>
      <div className="body">
        <div className="reason" style={{ marginBottom: 8 }}>
          {d.boss} · {d.date} · слот {d.slot}
        </div>
        {d.candidates.length === 0 ? (
          <div className="reason">Нет очевидных кандидатов — размётка предмета или ростер.</div>
        ) : (
          <div className="table-scroll">
          <table style={{ fontSize: 12 }}>
            <tbody>
              {d.candidates.map((c) => (
                <tr key={c.player} className="clickable" onClick={() => onOpenPlayer(c.player)}>
                  <td className="num r" style={{ color: "var(--accent)", fontWeight: 700, width: "3.4em" }}>{f2(c.priority)}</td>
                  <td>{c.display}</td>
                  <td className="reason">{c.fit.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </div>
  );
}
