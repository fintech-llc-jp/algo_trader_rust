import { TrainingJobRequest, TrainingJobStatus } from './api';

type TrainingFormDraft = {
  modelName: string;
  symbol: string;
  trainingWindowDays: string;
  predictionHorizon: string;
  modelsCsv: string;
  timeframesCsv: string;
};

type Props = {
  draft: TrainingFormDraft;
  running: boolean;
  latestJob: TrainingJobStatus | null;
  error: string | null;
  onDraftChange: (next: TrainingFormDraft) => void;
  onStart: () => void;
  onCancel: () => void;
  onRefresh: () => void;
};

export type { TrainingFormDraft };

export default function MvpTraining({
  draft,
  running,
  latestJob,
  error,
  onDraftChange,
  onStart,
  onCancel,
  onRefresh,
}: Props) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">ML Training</h1>

      <section className="rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Start Training Job</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field
            label="model_name"
            value={draft.modelName}
            onChange={(v) => onDraftChange({ ...draft, modelName: v })}
          />
          <Field
            label="symbol"
            value={draft.symbol}
            onChange={(v) => onDraftChange({ ...draft, symbol: v })}
          />
          <Field
            label="training_window_days"
            value={draft.trainingWindowDays}
            onChange={(v) => onDraftChange({ ...draft, trainingWindowDays: v })}
          />
          <Field
            label="prediction_horizon"
            value={draft.predictionHorizon}
            onChange={(v) => onDraftChange({ ...draft, predictionHorizon: v })}
          />
          <Field
            label="models (comma separated)"
            value={draft.modelsCsv}
            onChange={(v) => onDraftChange({ ...draft, modelsCsv: v })}
          />
          <Field
            label="timeframes (comma separated)"
            value={draft.timeframesCsv}
            onChange={(v) => onDraftChange({ ...draft, timeframesCsv: v })}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
            onClick={onStart}
            disabled={running}
          >
            Start Training
          </button>
          <button
            className="rounded border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
            onClick={onCancel}
            disabled={!latestJob || latestJob.done}
          >
            Cancel Job
          </button>
          <button className="rounded border px-3 py-2 text-sm" onClick={onRefresh}>
            Refresh Status
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
      </section>

      <section className="rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Latest Training Job</h2>
        {!latestJob ? (
          <p className="text-sm text-gray-600">No training job yet.</p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-2 text-sm md:grid-cols-4">
              <Stat label="job_id" value={latestJob.job_id} mono />
              <Stat label="status" value={latestJob.status} />
              <Stat
                label="progress"
                value={
                  latestJob.progress == null ? '-' : `${Math.round(latestJob.progress * 100)}%`
                }
              />
              <Stat label="done" value={latestJob.done ? 'true' : 'false'} />
            </div>
            <p className="text-sm text-gray-700">
              {latestJob.message ?? 'No message from backend.'}
            </p>
            <pre className="max-h-80 overflow-auto rounded bg-gray-50 p-3 text-xs">
{JSON.stringify(latestJob.result ?? latestJob.upstream ?? {}, null, 2)}
            </pre>
          </div>
        )}
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
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <label className="text-sm">
      {label}
      <input
        className="mt-1 w-full rounded border px-2 py-1"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded border p-2">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className={`mt-1 text-sm ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  );
}

export function buildTrainingRequest(draft: TrainingFormDraft): TrainingJobRequest {
  const modelName = draft.modelName.trim();
  const symbol = draft.symbol.trim();
  if (!modelName || !symbol) {
    throw new Error('model_name と symbol は必須です。');
  }

  const trainingWindowDays = Number(draft.trainingWindowDays);
  if (!Number.isInteger(trainingWindowDays) || trainingWindowDays <= 0) {
    throw new Error('training_window_days は正の整数を指定してください。');
  }

  const predictionHorizon = Number(draft.predictionHorizon);
  if (!Number.isInteger(predictionHorizon) || predictionHorizon <= 0) {
    throw new Error('prediction_horizon は正の整数を指定してください。');
  }

  const models = draft.modelsCsv
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const timeframes = draft.timeframesCsv
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isInteger(n) && n > 0);

  if (models.length === 0) {
    throw new Error('models は 1 つ以上指定してください。');
  }
  if (timeframes.length === 0) {
    throw new Error('timeframes は 1 つ以上指定してください。');
  }

  return {
    model_name: modelName,
    symbol,
    training_window_days: trainingWindowDays,
    prediction_horizon: predictionHorizon,
    models,
    timeframes,
  };
}
