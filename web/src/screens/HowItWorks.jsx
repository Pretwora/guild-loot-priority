import { readableColor } from "../lib.js";

export default function HowItWorks({ data }) {
  const w = data.formula.weights;
  const classes = data.formula.classes;
  return (
    <>
      <h2 className="screen">Как это считается</h2>
      <p className="sub">
        Страница генерируется из <kbd>config/weights.yml</kbd>, а не пишется руками.
        Веса заморожены на тир и меняются только через PR с обоснованием — иначе правка
        посреди тира обесценивает накопленное. LLM не считает ни одного числа: весь скоринг — Python.
      </p>

      <div className="grid2">
        <Panel title="Итоговый рейтинг S">
          <div className="formula-block">
            S = {w.score.scale} × ({w.score.w_attendance}·A_eff + {w.score.w_perf}·P) / (1 + {w.score.loot_penalty_k}·L_norm) × rank_gate
          </div>
          <p className="reason">Вклад перформанса ограничен {Math.round(w.score.w_perf * 100)}% сознательно: выше — и топ-дпс в лучшей экипировке забирает всё, разрыв сам себя усиливает.</p>
          <dl className="kv">
            <dt>rank_gate триал</dt><dd className="num">{w.score.rank_gate.trial}</dd>
            <dt>rank_gate состав</dt><dd className="num">{w.score.rank_gate.member}</dd>
          </dl>
        </Panel>

        <Panel title="A — посещаемость (0..1)">
          <div className="formula-block">A = Σ(λ^дней · кредит) / Σ(λ^дней),&nbsp; λ={w.attendance.decay_lambda}<br/>A_eff = A·conf + медиана·(1−conf),&nbsp; conf=min(1, вечеров/{w.attendance.confidence_nights})</div>
          <p className="reason">Окно: последние {w.attendance.window_weeks} недель или {w.attendance.window_nights} вечеров — что больше. Бенч = полный кредит. Вечер чужого состава не идёт в знаменатель. Сжатие к среднему не даёт новичку с двумя рейдами обойти того, кто ходит полгода.</p>
        </Panel>

        <Panel title="P — перформанс (0..1), только ДД">
          <div className="formula-block">p = ранг / (n−1) внутри пары «спек + босс»<br/>P = медиана p за последние {w.performance.window_kills} килов</div>
          <p className="reason"><b>Меряется только у ДД</b> ({(w.performance.measured_roles || ["dps"]).join(", ")}): урон, перцентиль внутри своего спека на своём боссе (сырые dps между классами не сравниваются). При n&lt;{w.performance.min_sample} записях p={w.performance.neutral} (мало данных = нейтрально).</p>
          <p className="reason"><b>Танки и хилы перформансом не оцениваются</b> — слишком ситуативно (мейн- vs офф-танк, оверхил, беготня по механике), а полезны они по определению. Их вес перформанса ({Math.round(w.score.w_perf * 100)}%) уходит в посещаемость: судятся по посещаемости и луту.</p>
          <p className="reason">Модификаторы ДД (покилово, под потолком {Math.round(w.score.w_perf * 100)}%): перебивания+диспелы до +{Math.round(w.performance.util_weight * 100)}% (перцентиль внутри роли), смерть −{Math.round(w.performance.death_penalty * 100)}%. Боевой лог есть у {data.meta.combat?.kills_with_log ?? 0} из {data.meta.combat?.kills_counted ?? 0} зачётных килов.</p>
        </Panel>

        <Panel title="L — полученный лут">
          <div className="formula-block">L = Σ(вес_слота · множитель_типа · {w.loot.decay_lambda}^дней)<br/>L_norm = clip(L / (медиана+ε), 0, {w.loot.norm_clip_max})</div>
          <table style={{ fontSize: 12, marginTop: 6 }}>
            <thead><tr><th>тип выдачи</th><th className="r">множитель</th></tr></thead>
            <tbody>
              {Object.entries(w.loot.award_type_mult).map(([k, v]) => (
                <tr key={k}><td>{k}</td><td className="r num">{v == null ? "не учитывается" : v}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Вес предмета по слоту">
          <table style={{ fontSize: 12 }}>
            <tbody>
              {Object.entries(w.loot.slot_weight).map(([k, v]) => (
                <tr key={k}><td>{k}</td><td className="r num">{v}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Fit — соответствие предмета (0..1)">
          <div className="formula-block">F = need · slot_gap · set_bonus</div>
          <dl className="kv">
            <dt>need основной спек</dt><dd className="num">{w.fit.need_main}</dd>
            <dt>need запасной</dt><dd className="num">{w.fit.need_offspec}</dd>
            <dt>slot_gap насыщение</dt><dd className="num">{w.fit.slot_gap_saturation_weeks} нед.</dd>
            <dt>set_bonus (2/4-сет)</dt><dd className="num">{w.fit.set_bonus_completes}</dd>
          </dl>
          <p className="reason">Кандидаты на предмет сортируются по S×F, показываются топ-{w.candidates.top_n} с разбивкой — именно расшифровка делает решение защитимым в споре.</p>
        </Panel>
      </div>

      <Panel title="Цвета классов">
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
          {Object.values(classes).map((c) => (
            <span key={c.name} style={{ color: readableColor(c.color), fontWeight: 600 }}>{c.name}</span>
          ))}
        </div>
      </Panel>
    </>
  );
}

function Panel({ title, children }) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      <div className="body">{children}</div>
    </div>
  );
}
