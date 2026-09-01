import { readableColor, pct, f2, f1, deltaClass, deltaText, deltaTooltip, useSort } from "../lib.js";

function Caret({ active, dir }) {
  if (!active) return null;
  return <span className="caret">{dir === "asc" ? "▲" : "▼"}</span>;
}

export function Meter({ value, kind }) {
  const w = Math.max(0, Math.min(1, value ?? 0)) * 100;
  return (
    <span className="meter">
      <span className="track"><span className={"fill" + (kind === "perf" ? " perf" : "")} style={{ width: w + "%" }} /></span>
      <span className="val num">{pct(value)}</span>
    </span>
  );
}

export function PlayerName({ p }) {
  return (
    <>
      <span className="pname" style={{ color: readableColor(p.class_color) }}>{p.display}</span>
      <span className="spec">{p.spec_name}</span>
      {p.frozen && <span className="frozen-mark" title="Рейтинг заморожен советом">❄</span>}
    </>
  );
}

const COLS = [
  { key: "score", label: "Рейтинг", sortable: true, cls: "r" },
  { key: "delta", label: "Δ рейд", sortable: true, cls: "r" },
  { key: "attendance.A", label: "Посещаемость", sortable: true },
  { key: "components.P", label: "Перформанс", sortable: true },
  { key: "components.L_norm", label: "Лут", sortable: true, cls: "r" },
];

export default function Priority({ data, scope, onOpenPlayer }) {
  const active = (data.scopes || []).find((s) => s.key === scope) || { players: data.players };
  const { sorted, key, dir, onSort } = useSort(active.players, "score", "desc");

  return (
    <>
      <h2 className="screen">Приоритет</h2>
      <p className="sub">
        Кто заслужил{scope !== "all" ? ` (ладдер ${active.label})` : ""}. Сортировка по любой
        колонке. Строка → карточка игрока с расшифровкой. Система — советник, а не судья.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="r">#</th>
              <th>Игрок</th>
              <th>Ранг</th>
              {COLS.map((c) => (
                <th key={c.key} className={(c.cls || "") + " sortable"} onClick={() => onSort(c.key)}
                    role="button" tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && onSort(c.key)}>
                  {c.label} <Caret active={key === c.key} dir={dir} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((p, i) => (
              <tr key={p.id} className="clickable" onClick={() => onOpenPlayer(p.id)}
                  tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpenPlayer(p.id)}>
                <td className="rank-idx num">{i + 1}</td>
                <td className="player" style={{ "--klass": readableColor(p.class_color) }}>
                  <PlayerName p={p} />
                </td>
                <td><RankBadge rank={p.rank} /></td>
                <td className="r num score">{f1(p.score)}</td>
                <td className={"r num delta " + deltaClass(p.delta)} title={deltaTooltip(p.delta_parts)}>
                  <span className={deltaTooltip(p.delta_parts) ? "hinted" : ""}>{deltaText(p.delta)}</span>
                </td>
                <td title={p.attendance.no_raid_data
                    ? "не был ни на одной 25-ке (нет данных)"
                    : `факт. посещаемость; в рейтинге A_eff ${pct(p.components.A_eff)} (сжатие малой выборки)`}>
                  {p.attendance.no_raid_data
                    ? <span className="reason">нет 25-к</span>
                    : <Meter value={p.attendance.A} />}
                </td>
                <td title={p.perf_measured ? undefined : "перформанс не применяется к танкам/хилам — судятся по посещаемости"}>
                  {p.perf_measured
                    ? <Meter value={p.components.P} kind="perf" />
                    : <span className="reason">—</span>}
                </td>
                <td className="r num" title="Нормированный полученный лут">{f2(p.components.L_norm)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function RankBadge({ rank }) {
  const label = { trial: "триал", member: "состав", officer: "офицер" }[rank] || rank;
  return <span className={"badge " + rank}>{label}</span>;
}
