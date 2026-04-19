import React, { useState } from 'react';
import { Download, Terminal, Search, CheckCircle2, AlertCircle, Info, X, ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '../lib/utils';

export default function AuditLog() {
  const [expandedRow, setExpandedRow] = useState<number | null>(0);

  return (
    <div className="space-y-8">
      {/* Header Section */}
      <div className="flex flex-col md:flex-row justify-between items-end mb-10 gap-6">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-black tracking-tight text-on-surface mb-2 font-headline uppercase">Audit Ledger</h1>
          <p className="text-on-surface-variant text-sm leading-relaxed">
            Immutable record of system operations, configuration overrides, and risk parameter adjustments. Use Correlation IDs to trace asynchronous execution threads across the engine.
          </p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 bg-surface-container-highest px-4 py-2 rounded-sm text-xs font-label font-bold uppercase tracking-widest hover:bg-surface-bright transition-colors text-on-surface">
            <Download className="w-4 h-4" />
            Export CSV
          </button>
          <button className="flex items-center gap-2 bg-primary px-4 py-2 rounded-sm text-xs font-label font-bold uppercase tracking-widest hover:brightness-110 transition-all text-on-primary">
            <Terminal className="w-4 h-4" />
            JSON Stream
          </button>
        </div>
      </div>

      {/* Filter Panel */}
      <div className="bg-surface-container-low p-6 rounded-sm mb-8 border-l-2 border-primary/30">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <FilterSelect label="Actor Identity" options={['ALL_ENTITIES', 'SYSTEM_ROOT', 'STRATEGY_BOT_01', 'ADMIN_USER_42']} />
          <FilterSelect label="Event Category" options={['ALL_EVENTS', 'CONFIG_CHANGE', 'RISK_BREACH', 'AUTH_SUCCESS']} />
          <div>
            <label className="block text-[0.65rem] font-label font-bold text-primary tracking-widest uppercase mb-2">Time Horizon</label>
            <div className="flex items-center gap-2">
              <input className="bg-surface-container border-none text-on-surface text-[0.7rem] rounded-sm w-full font-label p-2" type="date" />
              <span className="text-on-surface-variant text-xs">to</span>
              <input className="bg-surface-container border-none text-on-surface text-[0.7rem] rounded-sm w-full font-label p-2" type="date" />
            </div>
          </div>
          <div className="flex items-end">
            <button className="w-full bg-surface-container-highest hover:bg-surface-bright py-2 rounded-sm text-[0.65rem] font-label font-bold tracking-widest uppercase transition-colors">Apply Filters</button>
          </div>
        </div>
      </div>

      {/* Audit Table */}
      <div className="overflow-hidden bg-surface">
        <table className="w-full border-separate border-spacing-y-1">
          <thead>
            <tr className="text-left">
              <th className="pb-4 px-4 text-[0.65rem] font-label font-bold text-on-surface-variant tracking-widest uppercase">Timestamp</th>
              <th className="pb-4 px-4 text-[0.65rem] font-label font-bold text-on-surface-variant tracking-widest uppercase">Actor</th>
              <th className="pb-4 px-4 text-[0.65rem] font-label font-bold text-on-surface-variant tracking-widest uppercase">Event Type</th>
              <th className="pb-4 px-4 text-[0.65rem] font-label font-bold text-on-surface-variant tracking-widest uppercase">Correlation ID</th>
              <th className="pb-4 px-4 text-[0.65rem] font-label font-bold text-on-surface-variant tracking-widest uppercase">Status</th>
              <th className="pb-4 px-4 text-right text-[0.65rem] font-label font-bold text-on-surface-variant tracking-widest uppercase">Action</th>
            </tr>
          </thead>
          <tbody className="space-y-1">
            <AuditRow 
              index={0}
              time="2024-05-20 14:02:11.902" 
              actor="ADMIN_USER_42" 
              type="CONFIG_UPDATE" 
              corrId="tx-77a2-f81d-00c9" 
              status="SUCCESS"
              isExpanded={expandedRow === 0}
              onToggle={() => setExpandedRow(expandedRow === 0 ? null : 0)}
            />
            {expandedRow === 0 && (
              <tr>
                <td className="p-0" colSpan={6}>
                  <div className="bg-surface-container-lowest mx-4 mb-2 p-6 border-t border-primary/10">
                    <div className="grid grid-cols-2 gap-8">
                      <div>
                        <h4 className="text-[0.6rem] font-label font-bold text-on-surface-variant uppercase tracking-widest mb-3">STATE_BEFORE</h4>
                        <div className="bg-error-container/10 p-4 rounded-sm font-mono text-[0.75rem] text-on-surface/70 leading-relaxed">
                          max_leverage: <span className="text-error font-bold">10.0</span><br />
                          slippage_tolerance: 0.05<br />
                          circuit_breaker_active: false
                        </div>
                      </div>
                      <div>
                        <h4 className="text-[0.6rem] font-label font-bold text-on-surface-variant uppercase tracking-widest mb-3">STATE_AFTER</h4>
                        <div className="bg-primary-container/20 p-4 rounded-sm font-mono text-[0.75rem] text-on-surface/70 leading-relaxed">
                          max_leverage: <span className="text-primary font-bold">5.0</span><br />
                          slippage_tolerance: 0.05<br />
                          circuit_breaker_active: false
                        </div>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            )}
            <AuditRow index={1} time="2024-05-20 13:45:00.012" actor="SYSTEM_ROOT" type="AUTO_REBALANCE" corrId="tx-11b0-99c2-dae2" status="SUCCESS" />
            <AuditRow index={2} time="2024-05-20 13:12:44.221" actor="STRATEGY_BOT_01" type="RISK_VIOLATION" corrId="tx-fe09-0012-77bc" status="BLOCKED" />
            <AuditRow index={3} time="2024-05-20 12:59:10.551" actor="ADMIN_USER_42" type="AUTH_LOGIN" corrId="tx-cc31-9a10-ff01" status="SUCCESS" />
          </tbody>
        </table>
      </div>

      {/* Footer Stats */}
      <div className="mt-8 pt-6 border-t border-outline-variant/10 flex flex-col md:flex-row justify-between items-center gap-6">
        <div className="flex gap-8">
          <div>
            <div className="text-[0.6rem] font-label font-bold text-on-surface-variant uppercase tracking-widest">Showing</div>
            <div className="text-sm font-label font-bold text-on-surface">50 / 12,942 Events</div>
          </div>
          <div>
            <div className="text-[0.6rem] font-label font-bold text-on-surface-variant uppercase tracking-widest">Integrity Hash</div>
            <div className="text-sm font-mono text-primary truncate w-48">sha256:7b2d...f901</div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <PaginationButton icon={<ChevronLeft className="w-4 h-4" />} />
          <PaginationButton label="1" active />
          <PaginationButton label="2" />
          <PaginationButton label="3" />
          <span className="px-2 text-on-surface-variant">...</span>
          <PaginationButton label="259" />
          <PaginationButton icon={<ChevronRight className="w-4 h-4" />} />
        </div>
      </div>

      {/* Trace Detail Panel */}
      <div className="fixed bottom-8 right-8 w-80 bg-surface-container-high/80 backdrop-blur-xl p-6 rounded-sm border border-primary/20 shadow-2xl z-40">
        <div className="flex justify-between items-start mb-4">
          <div className="flex items-center gap-2">
            <Info className="w-4 h-4 text-primary" />
            <span className="text-[0.7rem] font-label font-bold uppercase tracking-widest">Trace Detail</span>
          </div>
          <button className="text-on-surface-variant hover:text-on-surface"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-xs text-on-surface-variant mb-4 leading-relaxed">
          Correlation ID <span className="text-primary font-mono">tx-77a2...</span> represents a sequence of <span className="text-on-surface font-bold">4 events</span> triggered by a manual override in the Order Engine.
        </p>
        <div className="space-y-3">
          <TraceItem time="14:02:11" label="Manual Request" />
          <TraceItem time="14:02:11" label="Policy Validation" />
          <TraceItem time="14:02:12" label="Commit (Config)" />
        </div>
      </div>
    </div>
  );
}

function FilterSelect({ label, options }: any) {
  return (
    <div>
      <label className="block text-[0.65rem] font-label font-bold text-primary tracking-widest uppercase mb-2">{label}</label>
      <select className="w-full bg-surface-container border-none text-on-surface text-sm rounded-sm focus:ring-1 focus:ring-primary p-2">
        {options.map((opt: string) => <option key={opt}>{opt}</option>)}
      </select>
    </div>
  );
}

function AuditRow({ time, actor, type, corrId, status, isExpanded, onToggle }: any) {
  return (
    <tr className={cn("group hover:bg-surface-container-high transition-colors", isExpanded && "bg-surface-container-high")}>
      <td className="bg-surface-container py-4 px-4 font-mono text-[0.75rem] text-on-surface-variant">{time}</td>
      <td className="bg-surface-container py-4 px-4 font-label text-[0.75rem] font-medium text-primary">{actor}</td>
      <td className="bg-surface-container py-4 px-4">
        <span className={cn(
          "text-[0.65rem] font-label font-bold px-2 py-0.5 rounded-sm",
          type === 'RISK_VIOLATION' ? "bg-error/10 text-error" : type === 'AUTO_REBALANCE' ? "bg-tertiary/10 text-tertiary" : "bg-primary/10 text-primary"
        )}>
          {type}
        </span>
      </td>
      <td className="bg-surface-container py-4 px-4 font-mono text-[0.7rem] text-on-surface-variant">
        <span className="border-b border-dotted border-on-surface-variant hover:text-primary cursor-pointer">{corrId}</span>
      </td>
      <td className="bg-surface-container py-4 px-4">
        <div className={cn(
          "flex items-center gap-1.5 text-[0.65rem] font-label font-bold",
          status === 'SUCCESS' ? "text-primary" : "text-error"
        )}>
          {status === 'SUCCESS' ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertCircle className="w-3.5 h-3.5" />}
          {status}
        </div>
      </td>
      <td className="bg-surface-container py-4 px-4 text-right">
        <button 
          onClick={onToggle}
          className="text-[0.65rem] font-label font-bold text-primary hover:underline uppercase tracking-tighter"
        >
          View Diff
        </button>
      </td>
    </tr>
  );
}

function PaginationButton({ label, icon, active }: any) {
  return (
    <button className={cn(
      "w-8 h-8 flex items-center justify-center rounded-sm transition-colors",
      active ? "bg-primary text-on-primary font-bold" : "bg-surface-container hover:bg-surface-container-high text-xs font-label"
    )}>
      {icon || label}
    </button>
  );
}

function TraceItem({ time, label }: any) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-1 h-1 rounded-full bg-primary"></div>
      <span className="text-[0.65rem] font-mono text-on-surface-variant">{time} - {label}</span>
    </div>
  );
}
