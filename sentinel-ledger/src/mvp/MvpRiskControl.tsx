import { useState } from 'react';
import { RiskLimits, TickDecision } from './types';

type Props = {
  limits: RiskLimits;
  dailyPnl: number;
  ticks: TickDecision[];
  onUpdateLimits: (next: RiskLimits) => Promise<{ ok: boolean; error?: string }>;
  onUpdateDailyPnl: (next: number) => Promise<void>;
};

export default function MvpRiskControl({
  limits,
  dailyPnl,
  ticks,
  onUpdateLimits,
  onUpdateDailyPnl,
}: Props) {
  const [draft, setDraft] = useState<RiskLimits>(limits);
  const [pnlDraft, setPnlDraft] = useState(String(dailyPnl));
  const [message, setMessage] = useState('');

  const blocked = ticks.filter((t) => t.risk.blocked).slice(0, 20);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Risk Control</h1>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="max_position_units" value={String(limits.maxPositionUnits)} />
        <Stat label="max_order_size" value={String(limits.maxOrderSize)} />
        <Stat label="max_daily_loss_abs" value={String(limits.maxDailyLossAbs)} />
        <Stat label="daily_pnl" value={dailyPnl.toFixed(2)} />
      </div>

      <section className="grid grid-cols-1 gap-4 rounded border p-4 lg:grid-cols-2">
        <div className="space-y-3">
          <h2 className="text-sm font-semibold">Update Risk Limits</h2>
          <Field
            label="max_position_units"
            value={draft.maxPositionUnits}
            onChange={(v) => setDraft((prev) => ({ ...prev, maxPositionUnits: v }))}
          />
          <Field
            label="max_order_size"
            value={draft.maxOrderSize}
            onChange={(v) => setDraft((prev) => ({ ...prev, maxOrderSize: v }))}
          />
          <Field
            label="max_daily_loss_abs"
            value={draft.maxDailyLossAbs}
            onChange={(v) => setDraft((prev) => ({ ...prev, maxDailyLossAbs: v }))}
          />
          <button
            className="rounded bg-blue-600 px-3 py-2 text-sm text-white"
            onClick={async () => {
              if (!window.confirm('RiskLimits を更新しますか？')) return;
              const result = await onUpdateLimits(draft);
              setMessage(result.ok ? 'Risk limits updated.' : `Failed: ${result.error}`);
            }}
          >
            Save RiskLimits
          </button>
        </div>

        <div className="space-y-3">
          <h2 className="text-sm font-semibold">Update Daily PnL</h2>
          <label className="block text-sm">
            daily_pnl
            <input
              className="mt-1 w-full rounded border px-2 py-1"
              value={pnlDraft}
              onChange={(e) => setPnlDraft(e.target.value)}
            />
          </label>
          <button
            className="rounded bg-blue-600 px-3 py-2 text-sm text-white"
            onClick={async () => {
              const n = Number(pnlDraft);
              if (!Number.isFinite(n)) {
                setMessage('daily_pnl must be a number.');
                return;
              }
              await onUpdateDailyPnl(n);
              setMessage('Daily PnL updated.');
            }}
          >
            Update daily_pnl
          </button>
          {message && <p className="text-sm text-gray-700">{message}</p>}
        </div>
      </section>

      <section className="rounded border p-4">
        <h2 className="mb-2 text-sm font-semibold">Risk Block Log (latest)</h2>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b text-xs uppercase text-gray-500">
              <th className="py-2">Timestamp</th>
              <th className="py-2">Symbol</th>
              <th className="py-2">Intent</th>
              <th className="py-2">Reason</th>
            </tr>
          </thead>
          <tbody>
            {blocked.map((t) => (
              <tr key={t.id} className="border-b">
                <td className="py-2 font-mono text-xs">{t.at}</td>
                <td className="py-2">{t.symbol}</td>
                <td className="py-2">
                  {t.intent.type === 'place_order'
                    ? `place_order ${t.intent.side}`
                    : t.intent.type}
                </td>
                <td className="py-2 text-red-600">{t.risk.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block text-sm">
      {label}
      <input
        className="mt-1 w-full rounded border px-2 py-1"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border p-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className="mt-1 text-lg font-bold">{value}</div>
    </div>
  );
}
