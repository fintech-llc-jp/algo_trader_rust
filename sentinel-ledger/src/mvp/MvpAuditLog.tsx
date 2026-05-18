import { useMemo, useState } from 'react';
import { AuditEvent } from './types';

type Props = {
  events: AuditEvent[];
};

export default function MvpAuditLog({ events }: Props) {
  const [actorFilter, setActorFilter] = useState('all');
  const [eventFilter, setEventFilter] = useState('all');

  const actors = useMemo(
    () => ['all', ...Array.from(new Set(events.map((e) => e.actor)))],
    [events],
  );
  const eventTypes = useMemo(
    () => ['all', ...Array.from(new Set(events.map((e) => e.eventType)))],
    [events],
  );

  const filtered = events.filter((e) => {
    const actorOk = actorFilter === 'all' || e.actor === actorFilter;
    const eventOk = eventFilter === 'all' || e.eventType === eventFilter;
    return actorOk && eventOk;
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Audit Log</h1>
      <div className="flex flex-wrap gap-3">
        <label className="text-sm">
          actor
          <select
            className="ml-2 rounded border px-2 py-1"
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
          >
            {actors.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          event
          <select
            className="ml-2 rounded border px-2 py-1"
            value={eventFilter}
            onChange={(e) => setEventFilter(e.target.value)}
          >
            {eventTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="rounded border p-4">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b text-xs uppercase text-gray-500">
              <th className="py-2">Timestamp</th>
              <th className="py-2">Actor</th>
              <th className="py-2">Event</th>
              <th className="py-2">Correlation ID</th>
              <th className="py-2">Status</th>
              <th className="py-2">Message</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.id} className="border-b">
                <td className="py-2 font-mono text-xs">{e.at}</td>
                <td className="py-2">{e.actor}</td>
                <td className="py-2">{e.eventType}</td>
                <td className="py-2 font-mono text-xs">{e.correlationId}</td>
                <td className="py-2">
                  <span
                    className={
                      e.status === 'success'
                        ? 'text-green-700'
                        : e.status === 'warning'
                          ? 'text-yellow-700'
                          : 'text-red-700'
                    }
                  >
                    {e.status}
                  </span>
                </td>
                <td className="py-2">{e.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
