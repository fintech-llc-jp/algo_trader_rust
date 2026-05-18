import { AppConfig, ConfigDraftState, VotePolicy } from './types';

type Props = {
  draft: AppConfig;
  applied: AppConfig;
  draftState: ConfigDraftState;
  killSwitchActive: boolean;
  errors: string[];
  onDraftChange: (next: AppConfig) => void;
  onApply: () => void;
  onRollback: () => void;
  onToggleKillSwitch: () => void;
};

export default function MvpRuntimeConfig({
  draft,
  applied,
  draftState,
  killSwitchActive,
  errors,
  onDraftChange,
  onApply,
  onRollback,
  onToggleKillSwitch,
}: Props) {
  const vote = draft.vote;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Runtime & Config</h1>

      <section className="rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Runtime Control</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="text-sm">
            execution_mode
            <select
              className="mt-1 w-full rounded border px-2 py-1"
              value={draft.runtime.executionMode}
              onChange={(e) =>
                onDraftChange({
                  ...draft,
                  runtime: {
                    ...draft.runtime,
                    executionMode: e.target.value as 'dry_run' | 'live',
                  },
                })
              }
            >
              <option value="dry_run">dry_run</option>
              <option value="live">live</option>
            </select>
          </label>
          <label className="text-sm">
            tick_interval_ms
            <input
              className="mt-1 w-full rounded border px-2 py-1"
              value={draft.runtime.tickIntervalMs}
              onChange={(e) =>
                onDraftChange({
                  ...draft,
                  runtime: {
                    ...draft.runtime,
                    tickIntervalMs: Number(e.target.value),
                  },
                })
              }
            />
          </label>
          <label className="text-sm">
            default_order_quantity
            <input
              className="mt-1 w-full rounded border px-2 py-1"
              value={draft.runtime.defaultOrderQuantity}
              onChange={(e) =>
                onDraftChange({
                  ...draft,
                  runtime: {
                    ...draft.runtime,
                    defaultOrderQuantity: Number(e.target.value),
                  },
                })
              }
            />
          </label>
        </div>
      </section>

      <section className="rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Vote Policy</h2>
        <label className="text-sm">
          mode
          <select
            className="mt-1 w-full rounded border px-2 py-1 md:w-72"
            value={vote.mode}
            onChange={(e) =>
              onDraftChange({
                ...draft,
                vote: switchVoteMode(vote, e.target.value as VotePolicy['mode']),
              })
            }
          >
            <option value="weighted_majority">weighted_majority</option>
            <option value="quorum">quorum</option>
            <option value="simple_plurality">simple_plurality</option>
          </select>
        </label>

        {vote.mode === 'weighted_majority' && (
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="text-sm">
              min_net_strength
              <input
                className="mt-1 w-full rounded border px-2 py-1"
                value={vote.min_net_strength}
                onChange={(e) =>
                  onDraftChange({
                    ...draft,
                    vote: { ...vote, min_net_strength: Number(e.target.value) },
                  })
                }
              />
            </label>
          </div>
        )}

        {vote.mode === 'quorum' && (
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="text-sm">
              required_same_side
              <input
                className="mt-1 w-full rounded border px-2 py-1"
                value={vote.required_same_side}
                onChange={(e) =>
                  onDraftChange({
                    ...draft,
                    vote: {
                      ...vote,
                      required_same_side: Number(e.target.value),
                    },
                  })
                }
              />
            </label>
            <label className="text-sm">
              min_strength_per_vote
              <input
                className="mt-1 w-full rounded border px-2 py-1"
                value={vote.min_strength_per_vote}
                onChange={(e) =>
                  onDraftChange({
                    ...draft,
                    vote: {
                      ...vote,
                      min_strength_per_vote: Number(e.target.value),
                    },
                  })
                }
              />
            </label>
          </div>
        )}
      </section>

      <section className="rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Config Diff</h2>
        <pre className="overflow-auto rounded bg-gray-50 p-3 text-xs">
{JSON.stringify({ applied, draft }, null, 2)}
        </pre>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="rounded border px-3 py-2 text-sm" onClick={onRollback}>
            Rollback to applied
          </button>
          <button
            className="rounded bg-blue-600 px-3 py-2 text-sm text-white"
            onClick={() => {
              if (
                draft.runtime.executionMode === 'live' &&
                !window.confirm('live に切替えます。リスク閾値を確認しましたか？')
              ) {
                return;
              }
              onApply();
            }}
          >
            Apply Config
          </button>
          <button className="rounded bg-red-600 px-3 py-2 text-sm text-white" onClick={onToggleKillSwitch}>
            {killSwitchActive ? 'KillSwitch OFF' : 'KillSwitch ON'}
          </button>
          <span className="self-center text-sm text-gray-600">state: {draftState}</span>
        </div>
        {errors.length > 0 && (
          <ul className="mt-3 list-disc pl-5 text-sm text-red-700">
            {errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function switchVoteMode(prev: VotePolicy, mode: VotePolicy['mode']): VotePolicy {
  if (mode === prev.mode) return prev;
  if (mode === 'weighted_majority') {
    return {
      mode,
      min_net_strength: 0.15,
      weights: {
        market_maker: 1,
        arbitrage: 0.5,
        price_prediction: 1.2,
        momentum: 1,
      },
    };
  }
  if (mode === 'quorum') {
    return {
      mode,
      required_same_side: 2,
      min_strength_per_vote: 0.4,
    };
  }
  return { mode };
}
