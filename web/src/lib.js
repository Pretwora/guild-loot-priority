import { useMemo, useState } from "react";

// ── Контраст-флор для классовых цветов ──
// Тёмные классовые цвета (шаман, рыцарь смерти, чернокнижник) на тёмном фоне не
// проходят AA. Осветляем цвет к белому, пока контраст не станет читаемым. Никогда
// не рисуем нечитаемое имя (раздел 9.3 SPEC).

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function rgbToHex([r, g, b]) {
  return "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}
function luminance([r, g, b]) {
  const a = [r, g, b].map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
}
function contrast(rgb, bgRgb) {
  const l1 = luminance(rgb), l2 = luminance(bgRgb);
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

const DARK_BG = [22, 22, 26]; // --bg

export function readableColor(hex, target = 4.5) {
  if (!hex) return "#e6e6ea";
  let rgb = hexToRgb(hex.startsWith("#") ? hex : "#" + hex);
  let guard = 0;
  while (contrast(rgb, DARK_BG) < target && guard < 24) {
    rgb = rgb.map((v) => v + (255 - v) * 0.14); // подмешиваем белый
    guard++;
  }
  return rgbToHex(rgb);
}

// ── Форматтеры ──
export const pct = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
export const f2 = (x) => (x == null ? "—" : Number(x).toFixed(2));
export const f1 = (x) => (x == null ? "—" : Number(x).toFixed(1));

export function deltaClass(d) {
  if (d == null || Math.abs(d) < 0.005) return "flat";
  return d > 0 ? "up" : "down";
}
export function deltaText(d) {
  if (d == null) return "—";
  if (Math.abs(d) < 0.005) return "0";
  return (d > 0 ? "▲ " : "▼ ") + Math.abs(d).toFixed(1);
}

// ── Хук сортировки таблиц ──
export function useSort(rows, initialKey, initialDir = "desc") {
  const [key, setKey] = useState(initialKey);
  const [dir, setDir] = useState(initialDir);
  const sorted = useMemo(() => {
    const arr = [...rows];
    arr.sort((a, b) => {
      const va = valueAt(a, key), vb = valueAt(b, key);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string" || typeof vb === "string") {
        return dir === "asc" ? String(va).localeCompare(String(vb), "ru") : String(vb).localeCompare(String(va), "ru");
      }
      return dir === "asc" ? va - vb : vb - va;
    });
    return arr;
  }, [rows, key, dir]);

  function onSort(nextKey) {
    if (nextKey === key) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setKey(nextKey); setDir(typeof valueAt(rows[0], nextKey) === "string" ? "asc" : "desc"); }
  }
  return { sorted, key, dir, onSort };
}

function valueAt(obj, path) {
  if (!obj) return null;
  return path.split(".").reduce((o, k) => (o == null ? null : o[k]), obj);
}
