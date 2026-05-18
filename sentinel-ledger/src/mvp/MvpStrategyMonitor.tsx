import { useMemo, useState } from 'react';
import { TickDecision, VoteSide } from './types';

type Props = {
  ticks: TickDecision[];
  selectedTickId: number | null;
  onSelectTick: (id: number) => void;
  autoFollow: boolean;
  onToggleAutoFollow: () => void;
};

export default function MvpStrategyMonitor({
  ticks,
  selectedTickId,
  onSelectTick,
  autoFollow,
  onToggleAutoFollow,
}: Props) {
  const [strategyFilter, setStrategyFilter] = useState('');
  const [sideFilter, setSideFilter] = useState<'all' | VoteSide>('all');

  const selected = useMemo(() => {
    if (selectedTickId == null) return ticks[0] ?? null;
    return ticks.find((t) => t.id === selectedTickId) ?? ticks[0] ?? null;
  }, [selectedTickId, ticks]);

  const visibleVotes = useMemo(() => {
    if (!selected) return [];
    return selected.votes.filter((v) => {
      const strategyOk =
        strategyFilter.trim() === '' || v.strategyId.includes(strategyFilter.trim());
      const sideOk = sideFilter === 'all' || v.side === sideFilter;
      return strategyOk && sideOk;
    });
  }, [selected, strategyFilter, sideFilter]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Strategy & Vote Monitor</h1>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">
          Tick:
          <select
            className="ml-2 rounded border px-2 py-1"
            value={selected?.id ?? ''}
            onChange={(e) => onSelectTick(Number(e.target.value))}
          >
            {ticks.slice(0, 50).map((t) => (
              <option key={t.id} value={t.id}>
                #{t.id} ({t.at.slice(11, 19)})
              </option>
            ))}
          </select>
        </label>
        <button
          className="rounded border px-3 py-1 text-sm"
          onClick={onToggleAutoFollow}
        >
          {autoFollow ? '追従中（クリックで停止）' : '追従停止中（クリックで再開）'}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <section className="rounded border p-4 lg:col-span-2">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <input
              className="rounded border px-2 py-1 text-sm"
              placeholder="strategy_id filter"
              value={strategyFilter}
              onChange={(e) => setStrategyFilter(e.target.value)}
            />
            <select
              className="rounded border px-2 py-1 text-sm"
              value={sideFilter}
              onChange={(e) => setSideFilter(e.target.value as 'all' | VoteSide)}
            >
              <option value="all">all sides</option>
              <option value="buy">buy</option>
              <option value="sell">sell</option>
              <option value="hold">hold</option>
              <option value="abstain">abstain</option>
            </select>
          </div>

          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b text-xs uppercase text-gray-500">
                <th className="py-2">Strategy</th>
                <th className="py-2">Side</th>
                <th className="py-2">Strength</th>
                <th className="py-2">Weight</th>
              </tr>
            </thead>
            <tbody>
              {visibleVotes.map((v) => (
                <tr key={v.strategyId} className="border-b">
                  <td className="py-2">{v.strategyId}</td>
                  <td className="py-2">{v.side}</td>
                  <td className="py-2">{v.strength}</td>
                  <td className="py-2">{v.weight}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="rounded border p-4 text-sm">
          <h2 className="mb-2 text-xs uppercase text-gray-500">Aggregation / Intent</h2>
          {selected ? (
            <div className="space-y-2">
              <p>
                <b>Outcome:</b> {selected.outcome.side} ({selected.outcome.netStrength})
              </p>
              <p>
                <b>Detail:</b> {selected.outcome.detail}
              </p>
              <p>
                <b>Intent:</b>{' '}
                {selected.intent.type === 'place_order'
                  ? `place_order ${selected.intent.side} ${selected.intent.quantity}`
                  : `no_trade (${selected.intent.reason})`}
              </p>
              <p>
                <b>Risk:</b>{' '}
                {selected.risk.blocked ? (
                  <span className="text-red-600">{selected.risk.reason}</span>
                ) : (
                  <span className="text-green-700">passed</span>
                )}
              </p>
            </div>
          ) : (
            <p className="text-gray-500">No tick data.</p>
          )}
        </section>
      </div>
    </div>
  );
}
