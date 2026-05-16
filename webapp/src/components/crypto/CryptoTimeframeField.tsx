import { useCallback, useEffect, useMemo, useState } from "react";
import {
  formatTimeframe,
  normalizeTimeframeString,
  parseTimeframe,
  TIMEFRAME_PRESETS,
  TIMEFRAME_UNIT_OPTIONS,
  type TimeframeParts,
  type TimeframeUnit,
} from "@/components/crypto/cryptoTimeframe";

type CryptoTimeframeFieldProps = {
  value: string;
  onChange: (timeframe: string) => void;
  disabled?: boolean;
  className?: string;
  label?: string;
  showPresets?: boolean;
  id?: string;
};

export function CryptoTimeframeField({
  value,
  onChange,
  disabled = false,
  className,
  label = "Timeframe",
  showPresets = true,
  id,
}: CryptoTimeframeFieldProps) {
  const [parts, setParts] = useState<TimeframeParts>(() => parseTimeframe(value));

  useEffect(() => {
    setParts(parseTimeframe(value));
  }, [value]);

  const emit = useCallback(
    (next: TimeframeParts) => {
      const safe: TimeframeParts = {
        value: Math.max(1, Math.floor(Number(next.value)) || 1),
        unit: next.unit,
      };
      setParts(safe);
      onChange(formatTimeframe(safe));
    },
    [onChange],
  );

  const preview = useMemo(() => normalizeTimeframeString(formatTimeframe(parts)), [parts]);

  const onValueChange = (raw: string) => {
    const n = Number.parseInt(raw, 10);
    if (raw === "" || !Number.isFinite(n)) {
      emit({ ...parts, value: 1 });
      return;
    }
    emit({ ...parts, value: Math.max(1, n) });
  };

  const onUnitChange = (unit: TimeframeUnit) => {
    emit({ ...parts, unit });
  };

  const applyPreset = (preset: string) => {
    const p = parseTimeframe(preset);
    emit(p);
  };

  const fieldId = id ?? "crypto-timeframe";

  return (
    <label className={className ?? "radar-toolbar__field"}>
      <span className="radar-toolbar__label">{label}</span>
      <div
        className="crypto-timeframe-field"
        style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.35rem" }}
      >
        <input
          id={fieldId}
          className="radar-toolbar__input"
          type="number"
          min={1}
          step={1}
          value={parts.value}
          onChange={(ev) => onValueChange(ev.target.value)}
          disabled={disabled}
          style={{ width: "4.25rem", minWidth: "3.5rem" }}
          aria-label={`${label} valor`}
        />
        <select
          className="radar-toolbar__select"
          value={parts.unit}
          onChange={(ev) => onUnitChange(ev.target.value as TimeframeUnit)}
          disabled={disabled}
          style={{ minWidth: "6.5rem" }}
          aria-label={`${label} unidad`}
        >
          {TIMEFRAME_UNIT_OPTIONS.map((o) => (
            <option key={o.unit} value={o.unit}>
              {o.label}
            </option>
          ))}
        </select>
        <span
          className="msg-muted"
          style={{ fontSize: "0.78rem", whiteSpace: "nowrap" }}
          title="Cadena enviada al backend"
        >
          → {preview}
        </span>
      </div>
      {showPresets ? (
        <div
          className="crypto-timeframe-presets"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.3rem",
            marginTop: "0.35rem",
          }}
        >
          {TIMEFRAME_PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              className="radar-refresh-btn"
              style={{ fontSize: "0.72rem", padding: "0.15rem 0.45rem" }}
              disabled={disabled}
              onClick={() => applyPreset(p)}
            >
              {p}
            </button>
          ))}
        </div>
      ) : null}
    </label>
  );
}
