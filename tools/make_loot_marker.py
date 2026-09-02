#!/usr/bin/env python3
"""Визуальный инструмент разметки лута → HTML-артефакт (claude.ai).

Читает data/manual/loot_log.csv (скелет из make_loot_sheet.py) и рендерит страницу:
рейды по вечерам, у каждой шмотки выпадашка «кто получил» + кнопки Мейн/Офф/Фри.
Отметки сохраняются в artifact-db (Клод забирает их read_db) и в localStorage, плюс
кнопка «скопировать для Клода» как запасной путь.

Запуск:  python3 -m tools.make_loot_marker [-o scratchpad/loot_marker.html]
Данные авторитетны из CSV — правки лута меняются там, потом перегенерировать.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.common import Config, REPO_ROOT
from core import normalize as N

TEMPLATE = r"""<title>Разметка лута</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&display=swap">
<style>
:root{
  --bg:#f4f1f7; --surface:#ffffff; --surface-2:#f1ecf6; --ink:#1b1622; --ink-soft:#655c72;
  --line:#e4dcee; --accent:#7c3aed; --accent-soft:#ede4fb;
  --main:#0d9d63; --main-soft:#d9f5e8; --off:#bf720a; --off-soft:#fbeed4;
  --free:#6b7280; --free-soft:#eceef1; --alert:#d63a5c; --alert-soft:#fbe1e8;
  --shadow:0 1px 2px rgba(27,22,34,.06),0 4px 16px rgba(27,22,34,.05);
}
:root:not([data-theme="light"]){ @media (prefers-color-scheme:dark){
  --bg:#14111b; --surface:#1d1928; --surface-2:#272033; --ink:#ece7f3; --ink-soft:#9b91ab;
  --line:#322b40; --accent:#a988f7; --accent-soft:#2c2440;
  --main:#33d18f; --main-soft:#123528; --off:#e5a13c; --off-soft:#3a2c14;
  --free:#8b93a1; --free-soft:#2a2f38; --alert:#f2708f; --alert-soft:#3a1c26;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25);
}}
:root[data-theme="dark"]{
  --bg:#14111b; --surface:#1d1928; --surface-2:#272033; --ink:#ece7f3; --ink-soft:#9b91ab;
  --line:#322b40; --accent:#a988f7; --accent-soft:#2c2440;
  --main:#33d18f; --main-soft:#123528; --off:#e5a13c; --off-soft:#3a2c14;
  --free:#8b93a1; --free-soft:#2a2f38; --alert:#f2708f; --alert-soft:#3a1c26;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25);
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:920px;margin:0 auto;padding:0 16px 120px}
h1{font-family:Cinzel,Georgia,serif;font-weight:700;font-size:26px;letter-spacing:.02em;margin:0;color:var(--accent)}
.sub{color:var(--ink-soft);font-size:13px;margin:2px 0 0}
.tabnum{font-variant-numeric:tabular-nums}

/* шапка */
header{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.head-in{max-width:920px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.head-in .grow{flex:1;min-width:180px}
.progress{display:flex;align-items:center;gap:12px}
.pbar{width:120px;height:8px;border-radius:99px;background:var(--surface-2);overflow:hidden;border:1px solid var(--line)}
.pbar>i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),color-mix(in srgb,var(--accent) 60%,var(--main)));transition:width .3s}
.pnum{font-weight:700;font-size:15px}
.pnum b{color:var(--accent)}
.need{font-size:12px;color:var(--alert);font-weight:600}
.iconbtn{width:36px;height:36px;border:1px solid var(--line);background:var(--surface);color:var(--ink);
  border-radius:9px;cursor:pointer;font-size:16px;display:grid;place-items:center}
.iconbtn:hover{border-color:var(--accent)}

/* секции-вечера */
.night{margin-top:26px}
.night>h2{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 10px;padding-bottom:8px;
  border-bottom:2px solid var(--line)}
.night>h2 .date{font-size:19px;font-weight:700}
.night>h2 .inst{font-size:13px;color:var(--ink-soft)}
.night>h2 .cnt{margin-left:auto;font-size:12px;color:var(--ink-soft)}

/* строка предмета */
.row{display:grid;grid-template-columns:1fr 200px auto;gap:12px;align-items:center;
  background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:11px 14px;margin-bottom:8px;
  box-shadow:var(--shadow);position:relative;overflow:hidden}
.row::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:transparent}
.row.need::before{background:var(--alert)}
.row.done::before{background:var(--main)}
.iname{font-weight:600;color:var(--accent);line-height:1.25}
.chips{display:flex;gap:6px;margin-top:4px;flex-wrap:wrap}
.chip{font-size:11px;color:var(--ink-soft);background:var(--surface-2);border:1px solid var(--line);
  border-radius:6px;padding:1px 7px;letter-spacing:.02em}
.chip.boss{color:var(--ink-soft)}

select{width:100%;font:inherit;font-size:13px;color:var(--ink);background:var(--surface-2);
  border:1px solid var(--line);border-radius:8px;padding:7px 8px;cursor:pointer;appearance:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path d='M2 4l4 4 4-4' fill='none' stroke='%23888' stroke-width='1.5'/></svg>");
  background-repeat:no-repeat;background-position:right 8px center;padding-right:24px}
select:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
select.empty{color:var(--alert);border-color:var(--alert);border-style:dashed}

.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface-2)}
.seg button{border:0;background:transparent;color:var(--ink-soft);font:inherit;font-size:13px;font-weight:600;
  padding:7px 12px;cursor:pointer;border-right:1px solid var(--line)}
.seg button:last-child{border-right:0}
.seg button[aria-pressed="true"][data-v="main"]{background:var(--main-soft);color:var(--main)}
.seg button[aria-pressed="true"][data-v="off"]{background:var(--off-soft);color:var(--off)}
.seg button[aria-pressed="true"][data-v="free"]{background:var(--free-soft);color:var(--free)}
.row.none .seg{opacity:.4;pointer-events:none}

/* нижняя панель */
.bar{position:fixed;left:0;right:0;bottom:0;z-index:30;background:color-mix(in srgb,var(--bg) 92%,transparent);
  backdrop-filter:blur(10px);border-top:1px solid var(--line)}
.bar-in{max-width:920px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;gap:14px}
.status{font-size:13px;color:var(--ink-soft);flex:1}
.status b{color:var(--main)}
.cta{border:0;background:var(--accent);color:#fff;font:inherit;font-weight:700;font-size:14px;
  padding:11px 18px;border-radius:10px;cursor:pointer;box-shadow:var(--shadow)}
.cta:hover{filter:brightness(1.06)}
.cta.ghost{background:var(--surface);color:var(--ink);border:1px solid var(--line)}
dialog{border:0;border-radius:14px;padding:0;max-width:560px;width:92vw;background:var(--surface);color:var(--ink);box-shadow:var(--shadow)}
dialog::backdrop{background:rgba(10,8,14,.5)}
.dlg{padding:20px}
.dlg h3{margin:0 0 8px;font-family:Cinzel,serif;color:var(--accent)}
.dlg textarea{width:100%;height:200px;font:12px/1.5 ui-monospace,Menlo,monospace;color:var(--ink);
  background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:10px;resize:vertical}
@media (max-width:640px){
  .row{grid-template-columns:1fr;gap:9px}
  .seg{width:100%}.seg button{flex:1}
  select{width:100%}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>

<header>
  <div class="head-in">
    <div class="grow">
      <h1>Разметка лута</h1>
      <p class="sub">Гильдийные 25-ки с 13.08 · тыкай «кто получил» и Мейн / Офф / Фри</p>
    </div>
    <div class="progress">
      <div class="pbar"><i id="pfill" style="width:0%"></i></div>
      <div>
        <div class="pnum tabnum"><b id="pdone">0</b> / <span id="ptot">0</span></div>
        <div class="need" id="pneed"></div>
      </div>
    </div>
    <button class="iconbtn" id="theme" title="Тема">◐</button>
  </div>
</header>

<main class="wrap" id="app"></main>

<div class="bar"><div class="bar-in">
  <div class="status" id="status">Загрузка…</div>
  <button class="cta ghost" id="copy">Скопировать для Клода</button>
</div></div>

<dialog id="dlg"><div class="dlg">
  <h3>Готово — отправь Клоду</h3>
  <p class="sub" style="margin:0 0 10px">Скопируй текст ниже и вставь в чат. (Если Клод уже подтягивает отметки сам — можно не отправлять.)</p>
  <textarea id="out" readonly></textarea>
  <div style="display:flex;gap:10px;margin-top:12px;justify-content:flex-end">
    <button class="cta ghost" id="dlgclose">Закрыть</button>
    <button class="cta" id="dlgcopy">Скопировать</button>
  </div>
</div></dialog>

<script>
const DATA = __DATA__;
const NONE = "__none__";
const itemsById = {}; DATA.items.forEach(it=>itemsById[it.id]=it);
const KEY = "lootmarks_v1";
let state = {};
DATA.items.forEach(it=>state[it.id]={player:it.player||"", spec:it.spec||""});
try{const s=JSON.parse(localStorage.getItem(KEY)||"{}");for(const k in s)if(itemsById[k])state[k]=s[k];}catch(e){}

let db=null;
function saveLocal(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(e){}}
function setStatus(t,ok){const s=document.getElementById("status");s.innerHTML=ok?("<b>"+t+"</b>"):t;}
function pushDb(id){
  if(!db)return;
  const it=itemsById[id],v=state[id];
  db.doc("marks/"+id).set({player:v.player,spec:v.spec,item:it.item,date:it.date,boss:it.boss,rid:it.rid,entry:it.entry,ts:Date.now()})
    .then(()=>setStatus("сохранено ✓",true)).catch(()=>setStatus("сохранено локально (Клод подтянет позже)"));
}

/* тема */
const root=document.documentElement;
try{const t=localStorage.getItem("theme");if(t)root.setAttribute("data-theme",t);}catch(e){}
document.getElementById("theme").onclick=()=>{
  const cur=root.getAttribute("data-theme")||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light");
  const next=cur==="dark"?"light":"dark";root.setAttribute("data-theme",next);
  try{localStorage.setItem("theme",next);}catch(e){}
};

function rowStatus(id){
  const v=state[id];
  if(v.player===NONE)return "none";       // ГМ оставил / не роздан — решено
  if(v.player&&v.spec)return "done";
  return "need";
}
function render(){
  const app=document.getElementById("app");
  const groups={};DATA.items.forEach(it=>{(groups[it.date]=groups[it.date]||[]).push(it);});
  const dates=Object.keys(groups).sort();
  app.innerHTML="";
  for(const date of dates){
    const list=groups[date];
    const insts=[...new Set(list.map(x=>x.boss))];
    const sec=document.createElement("section");sec.className="night";
    const doneN=list.filter(x=>rowStatus(x.id)!=="need").length;
    sec.innerHTML='<h2><span class="date tabnum">'+date+'</span>'+
      '<span class="inst">'+insts.slice(0,3).join(" · ")+(insts.length>3?" …":"")+'</span>'+
      '<span class="cnt tabnum">'+doneN+' / '+list.length+'</span></h2>';
    for(const it of list){
      const v=state[it.id];const st=rowStatus(it.id);
      const row=document.createElement("div");row.className="row "+st+(v.player===NONE?" none":"");
      row.dataset.id=it.id;
      let opts='<option value="">— выбери получателя —</option><option value="'+NONE+'">— не роздан / ГМ оставил —</option>';
      const names=DATA.players.slice();if(v.player&&v.player!==NONE&&!names.includes(v.player))names.unshift(v.player);
      for(const nm of names)opts+='<option value="'+nm.replace(/"/g,'&quot;')+'"'+(v.player===nm?" selected":"")+'>'+nm+'</option>';
      const chips='<span class="chip">il'+(it.ilvl||"—")+'</span><span class="chip">'+it.slot+'</span>'+
        '<span class="chip boss">'+it.boss+'</span>';
      const spec=v.player&&v.player!==NONE?v.spec:"";
      row.innerHTML=
        '<div><div class="iname">'+it.item+'</div><div class="chips">'+chips+'</div></div>'+
        '<select class="rcv'+(v.player===""?" empty":"")+'">'+opts+'</select>'+
        '<div class="seg">'+
          '<button data-v="main" aria-pressed="'+(spec==="main")+'">Мейн</button>'+
          '<button data-v="off" aria-pressed="'+(spec==="off")+'">Офф</button>'+
          '<button data-v="free" aria-pressed="'+(spec==="free")+'">Фри</button>'+
        '</div>';
      const sel=row.querySelector("select");
      sel.onchange=()=>{
        state[it.id].player=sel.value;
        if(sel.value&&sel.value!==NONE&&!state[it.id].spec)state[it.id].spec="main";
        saveLocal();pushDb(it.id);render();
      };
      row.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{
        if(!state[it.id].player||state[it.id].player===NONE)return;
        state[it.id].spec=b.dataset.v;saveLocal();pushDb(it.id);render();
      });
      sec.appendChild(row);
    }
    app.appendChild(sec);
  }
  updateProgress();
}
function updateProgress(){
  const tot=DATA.items.length;
  const done=DATA.items.filter(x=>rowStatus(x.id)!=="need").length;
  const need=DATA.items.filter(x=>state[x.id].player==="").length;
  document.getElementById("ptot").textContent=tot;
  document.getElementById("pdone").textContent=done;
  document.getElementById("pfill").style.width=(done/tot*100)+"%";
  document.getElementById("pneed").textContent=need?("нужен получатель: "+need):"всё решено ✓";
}

/* экспорт для Клода (запасной путь) */
function buildCsv(){
  let out="record_id,item_entry,player,award_type\n";
  for(const it of DATA.items){
    const v=state[it.id];
    if(v.player===NONE){out+=it.rid+","+it.entry+",,\n";continue;}
    if(v.player&&v.spec)out+=it.rid+","+it.entry+","+v.player+","+v.spec+"\n";
  }
  return out;
}
const dlg=document.getElementById("dlg");
document.getElementById("copy").onclick=()=>{document.getElementById("out").value=buildCsv();dlg.showModal();};
document.getElementById("dlgclose").onclick=()=>dlg.close();
document.getElementById("dlgcopy").onclick=()=>{const t=document.getElementById("out");t.select();
  try{navigator.clipboard.writeText(t.value);}catch(e){document.execCommand("copy");}
  document.getElementById("dlgcopy").textContent="Скопировано ✓";};

render();
setStatus("отметки сохраняются автоматически на этом устройстве");
(async()=>{
  try{db=window.claude&&window.claude.use?await window.claude.use("db"):null;}catch(e){db=null;}
  if(!db){setStatus("сохранение локальное — в конце жми «Скопировать для Клода»");return;}
  try{
    const snap=await db.collection("marks").get();
    let n=0;snap.docs.forEach(d=>{const v=d.data();if(v&&itemsById[d.id]){state[d.id]={player:v.player||"",spec:v.spec||""};n++;}});
    if(n){saveLocal();render();}
    setStatus("подключено — Клод видит твои отметки ✓",true);
  }catch(e){setStatus("отметки сохраняются локально (Клод подтянет позже)");}
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("-i", "--input", default="data/manual/loot_log.csv")
    ap.add_argument("-o", "--out", default="scratchpad/loot_marker.html")
    args = ap.parse_args()

    cfg = Config(os.path.join(REPO_ROOT, args.config))
    roster = N.load_roster(cfg)
    kills = N.load_kills(cfg)
    N.augment_roster_with_parses(roster, kills, cfg)

    # игроки для выпадашки: приоритет реальным согильдийцам, потом все из ростера
    our = cfg.raw.get("guild_name_api", "")
    guildies = {p.name for k in kills for p in k.players if p.guild_name == our}
    names = set()
    for pid, pl in roster.players.items():
        d = pl.get("display", pid)
        names.add(d)
    players = sorted(names, key=lambda n: (n not in guildies, n.lower()))

    rows = list(csv.DictReader(open(os.path.join(REPO_ROOT, args.input), encoding="utf-8")))
    items = [{
        "id": f'{r["record_id"]}_{r["item_entry"]}',
        "rid": r["record_id"], "entry": r["item_entry"],
        "date": r["date"], "boss": r["boss"], "item": r["item_name"],
        "ilvl": r["ilvl"], "slot": r["slot"],
        "player": r["player"], "spec": r["award_type"],
    } for r in rows]

    data = {"items": items, "players": players}
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out_path = os.path.join(REPO_ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"предметов: {len(items)}, игроков: {len(players)} → {args.out}")


if __name__ == "__main__":
    main()
