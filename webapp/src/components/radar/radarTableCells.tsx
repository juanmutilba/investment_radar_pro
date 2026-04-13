import type { ReactNode } from "react";

import type { RadarRow } from "@/services/api";

import type { ColumnDef } from "./radarTableModel";
import {
  rsiToneClass,
  totalScoreToneClass,
} from "./radarTableCore";

export function convictionBadgeClassForSemaforo(text: string): string | null {
  const t = text.trim().toUpperCase();
  if (t === "ALTA") {
    return "radar-badge radar-badge--conv-alta";
  }
  if (t === "MEDIA") {
    return "radar-badge radar-badge--conv-media";
  }
  if (t === "BAJA") {
    return "radar-badge radar-badge--conv-baja";
  }
  return null;
}

export function trendBadgeClass(text: string): string {
  if (text === "Alcista") {
    return "radar-badge radar-badge--trend-alcista";
  }
  if (text === "No alcista") {
    return "radar-badge radar-badge--trend-bajista";
  }
  return "radar-badge radar-badge--trend-neutral";
}

export type RenderCellKeys = {
  totalKeys: string[];
  rsiKeys: string[];
};

export function renderCellInner(
  c: ColumnDef,
  row: RadarRow,
  text: string,
  missing: boolean,
  keys: RenderCellKeys,
): ReactNode {
  if (missing) {
    return text;
  }
  if (c.id === "trend") {
    return <span className={trendBadgeClass(text)}>{text}</span>;
  }
  if (c.id === "macd") {
    const yes = text === "Sí";
    return (
      <span className={yes ? "radar-badge radar-badge--macd-yes" : "radar-badge radar-badge--macd-no"}>
        {text}
      </span>
    );
  }
  if (c.id === "conv") {
    const convCls = convictionBadgeClassForSemaforo(text);
    if (!convCls) {
      return text;
    }
    return <span className={convCls}>{text}</span>;
  }
  if (c.id === "total") {
    const tone = totalScoreToneClass(row, keys.totalKeys);
    return tone ? <span className={tone}>{text}</span> : text;
  }
  if (c.id === "rsi") {
    const tone = rsiToneClass(row, keys.rsiKeys);
    return tone ? <span className={tone}>{text}</span> : text;
  }
  return text;
}
