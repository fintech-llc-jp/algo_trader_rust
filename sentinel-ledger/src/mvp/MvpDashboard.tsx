import { TickDecision, EngineStatus, ExecutionMode } from './types';

type AlertItem = {
  level: 'info' | 'warn' | 'error';
  message: string;
};

type Props = {
  engineStatus: EngineStatus;
  executionMode: ExecutionMode;
  killSwitchActive: boolean;
  ticks: TickDecision[];
  alerts: AlertItem[];
};

export default function MvpDashboard({
  engineStatus,
  executionMode,
  killSwitchActive,
  ticks,
  alerts,
}: Props) {
  const recent = ticks.slice(0, 30);
  const placeOrderCount = recent.filter((t) => t.intent.type === 'place_order').length;
  const noTradeCount = recent.length - placeOrderCount;
  const blockedCount = recent.filter((t) => t.risk.blocked).length;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      {killSwitchActive && (
        <div className="rounded bg-red-100 px-4 py-2 text-red-800">
          Kill switch is active. New trading intents are blocked.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="Engine Status" value={engineStatus.toUpperCase()} />
        <Stat label="Execution Mode" value={executionMode} />
        <Stat label="PlaceOrder (30 ticks)" value={String(placeOrderCount)} />
        <Stat label="NoTrade / Blocked" value={`${noTradeCount} / ${blockedCount}`} />
      </div>

      <section className="rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Latest Decision Timeline</h2>
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b text-xs uppercase text-gray-500">
                <th className="py-2">Timestamp</th>
                <th className="py-2">Symbol</th>
                <th className="py-2">Outcome</th>
                <th className="py-2">Intent</th>
                <th className="py-2">Risk</th>
              </tr>
            </thead>
            <tbody>
              {ticks.slice(0, 20).map((tick) => (
                <tr key={tick.id} className="border-b">
                  <td className="py-2 font-mono text-xs">{tick.at}</td>
                  <td className="py-2">{tick.symbol}</td>
                  <td className="py-2">
                    {tick.outcome.side} ({tick.outcome.netStrength})
                  </td>
                  <td className="py-2">
                    {tick.intent.type === 'place_order'
                      ? `place_order ${tick.intent.side} ${tick.intent.quantity}`
                      : `no_trade (${tick.intent.reason})`}
                  </td>
                  <td className="py-2">
                    {tick.risk.blocked ? (
                      <span className="text-red-600">{tick.risk.reason}</span>
                    ) : (
                      <span className="text-green-700">passed</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Alerts</h2>
        <div className="space-y-2 text-sm">
          {alerts.length === 0 ? (
            <p className="text-gray-500">No active alerts.</p>
          ) : (
            alerts.map((a, idx) => (
              <div
                key={`${a.message}-${idx}`}
                className={`rounded px-3 py-2 ${
                  a.level === 'error'
                    ? 'bg-red-50 text-red-700'
                    : a.level === 'warn'
                      ? 'bg-yellow-50 text-yellow-800'
                      : 'bg-blue-50 text-blue-700'
                }`}
              >
                {a.message}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
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
