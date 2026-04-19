import React from 'react';
import { TrendingUp, Activity, ShieldAlert, AlertCircle, Filter, Download, PieChart, Cpu } from 'lucide-react';
import { cn } from '../lib/utils';

export default function Dashboard() {
  return (
    <div className="space-y-8">
      {/* Header Section */}
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-on-surface">Execution Command Center</h1>
          <p className="text-on-surface-variant text-sm mt-1">Real-time oversight of the Sentinel Ledger execution engine.</p>
        </div>
        <div className="flex gap-4">
          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/60 font-bold font-label">Global Latency</span>
            <span className="text-xl font-bold text-primary font-label">1.24ms</span>
          </div>
        </div>
      </div>

      {/* Bento Grid Layout */}
      <div className="grid grid-cols-12 gap-6">
        {/* System Status Column */}
        <div className="col-span-12 lg:col-span-3 space-y-6">
          <div className="bg-surface-container p-5 rounded-sm border border-outline-variant/10">
            <div className="text-[10px] text-on-surface-variant/60 uppercase font-bold tracking-widest font-label mb-4">Core Engine</div>
            <div className="space-y-4">
              <div className="flex justify-between items-center bg-surface-container-low p-3 rounded-sm">
                <span className="text-xs font-medium">Execution Engine</span>
                <span className="px-2 py-0.5 bg-primary/20 text-primary text-[10px] font-bold uppercase rounded-sm">Running</span>
              </div>
              <div className="flex justify-between items-center bg-surface-container-low p-3 rounded-sm">
                <span className="text-xs font-medium">Operation Mode</span>
                <span className="px-2 py-0.5 bg-tertiary-container text-tertiary text-[10px] font-bold uppercase rounded-sm">dry_run</span>
              </div>
              <div className="bg-error-container/20 border border-error/30 p-3 rounded-sm">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-xs font-bold text-error">KillSwitch Status</span>
                  <span className="px-2 py-0.5 bg-surface-container-lowest text-on-surface/50 text-[10px] font-bold uppercase rounded-sm">Inactive</span>
                </div>
                <button className="w-full py-2 bg-error text-on-error text-xs font-black uppercase tracking-tighter rounded-sm hover:brightness-110 transition-all">
                  Engage Emergency Stop
                </button>
              </div>
            </div>
          </div>

          {/* Alerts List */}
          <div className="bg-surface-container p-5 rounded-sm border border-outline-variant/10">
            <div className="flex justify-between items-center mb-4">
              <div className="text-[10px] text-on-surface-variant/60 uppercase font-bold tracking-widest font-label">System Alerts</div>
              <span className="px-2 py-0.5 bg-error-container text-on-error-container text-[10px] font-bold rounded-full">3 Active</span>
            </div>
            <div className="space-y-3">
              <div className="p-3 bg-error-container/10 border-l-2 border-error rounded-sm">
                <div className="text-xs font-bold text-error mb-1">Risk limit exceeded: BTC/USD</div>
                <div className="text-[10px] text-on-surface-variant">Max position 5.0 exceeds limit 4.5. Triggered by Strategy_A.</div>
              </div>
              <div className="p-3 bg-tertiary-container/10 border-l-2 border-tertiary rounded-sm">
                <div className="text-xs font-bold text-tertiary mb-1">Config failed to sync</div>
                <div className="text-[10px] text-on-surface-variant">Node_04 rejected runtime params update. Retrying in 5s.</div>
              </div>
              <div className="p-3 bg-surface-container-low border-l-2 border-outline-variant rounded-sm">
                <div className="text-xs font-bold text-on-surface mb-1">Connection error: CME</div>
                <div className="text-[10px] text-on-surface-variant">Gateway latency spike detected (450ms). Monitoring...</div>
              </div>
            </div>
          </div>
        </div>

        {/* Main Content Column */}
        <div className="col-span-12 lg:col-span-9 space-y-6">
          {/* KPI Cards Row */}
          <div className="grid grid-cols-4 gap-4">
            <KPICard title="Tick Throughput" value="1.4M" unit="/sec" trend="+12% from avg" trendType="up" />
            <KPICard title="Orders Placed" value="24,802" trend="+12% from avg" trendType="up" />
            <KPICard title="No-Trade Sig" value="182.4K" trend="Normal range" trendType="neutral" />
            <KPICard title="Risk Blocks" value="42" trend="Action Required" trendType="warning" valueColor="text-tertiary" />
          </div>

          {/* Decision Timeline */}
          <div className="bg-surface-container rounded-sm border border-outline-variant/10 overflow-hidden">
            <div className="px-6 py-4 flex justify-between items-center bg-surface-container-high/40">
              <div className="text-[10px] text-on-surface-variant/60 uppercase font-bold tracking-widest font-label">Decision Timeline</div>
              <div className="flex gap-4">
                <button className="text-[10px] font-bold text-primary flex items-center gap-1">
                  <Filter className="w-3.5 h-3.5" /> FILTER
                </button>
                <button className="text-[10px] font-bold text-on-surface-variant flex items-center gap-1">
                  <Download className="w-3.5 h-3.5" /> EXPORT
                </button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-container-low text-on-surface-variant/70">
                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider font-label">Timestamp</th>
                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider font-label">Symbol</th>
                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider font-label">Vote Outcome</th>
                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider font-label">Intent</th>
                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider font-label text-right">Risk Decision</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/5">
                  <TimelineRow time="14:02:11.452" symbol="BTCUSD_PERP" outcome="BULLISH_SIGNAL" intent="Place Order" decision="PASSED (98.4%)" status="success" />
                  <TimelineRow time="14:02:09.121" symbol="ETHUSD_PERP" outcome="VOL_THRESHOLD_FAIL" intent="No Trade" decision="SKIPPED" status="neutral" />
                  <TimelineRow time="14:02:05.882" symbol="SOLUSD_PERP" outcome="MOMENTUM_CROSS" intent="Place Order" decision="REJECTED (Slippage)" status="error" />
                  <TimelineRow time="14:02:04.001" symbol="BTCUSD_PERP" outcome="BULLISH_SIGNAL" intent="Place Order" decision="PASSED (99.1%)" status="success" />
                  <TimelineRow time="14:01:58.234" symbol="LINKUSD_PERP" outcome="HEDGE_TRIGGER" intent="Modify Order" decision="PASSED (100%)" status="warning" />
                </tbody>
              </table>
            </div>
            <div className="px-6 py-3 bg-surface-container-low/50 flex justify-center">
              <button className="text-[10px] font-bold tracking-widest uppercase text-on-surface-variant hover:text-primary transition-colors font-label">View Full Audit History</button>
            </div>
          </div>

          {/* Bottom Grid */}
          <div className="grid grid-cols-2 gap-6">
            <div className="bg-surface-container p-5 rounded-sm border border-outline-variant/5">
              <div className="flex items-center gap-3 mb-4">
                <PieChart className="w-4 h-4 text-primary" />
                <div className="text-[10px] text-on-surface-variant/60 uppercase font-bold tracking-widest font-label">Current Distribution</div>
              </div>
              <div className="flex items-center gap-4">
                <div className="relative w-20 h-20">
                  <svg className="w-full h-full transform -rotate-90">
                    <circle className="text-surface-container-low" cx="40" cy="40" fill="transparent" r="35" stroke="currentColor" strokeWidth="8" />
                    <circle className="text-primary" cx="40" cy="40" fill="transparent" r="35" stroke="currentColor" strokeDasharray="220" strokeDashoffset="66" strokeWidth="8" />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center text-[10px] font-bold">70%</div>
                </div>
                <div className="flex-1 space-y-2">
                  <DistributionRow label="Long Exposure" value="$4.2M" color="text-primary" />
                  <DistributionRow label="Short Exposure" value="$1.8M" color="text-tertiary" />
                  <DistributionRow label="Cash Balance" value="$2.1M" color="text-on-surface" />
                </div>
              </div>
            </div>
            <div className="bg-surface-container p-5 rounded-sm border border-outline-variant/5">
              <div className="flex items-center gap-3 mb-4">
                <Cpu className="w-4 h-4 text-primary" />
                <div className="text-[10px] text-on-surface-variant/60 uppercase font-bold tracking-widest font-label">Worker Nodes (Live)</div>
              </div>
              <div className="grid grid-cols-4 gap-2">
                <NodeStatus id="1" status="UP" active />
                <NodeStatus id="2" status="UP" active />
                <NodeStatus id="3" status="UP" active />
                <NodeStatus id="4" status="OFF" />
              </div>
              <button className="mt-4 w-full py-2 border border-outline-variant/20 text-[10px] font-bold uppercase tracking-widest hover:bg-surface-container-high transition-colors rounded-sm">Cluster Management</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function KPICard({ title, value, unit, trend, trendType, valueColor = "text-on-surface" }: any) {
  return (
    <div className="bg-surface-container p-5 rounded-sm border border-outline-variant/5">
      <div className="text-[10px] text-on-surface-variant/60 uppercase font-bold tracking-widest font-label mb-2">{title}</div>
      <div className={cn("text-2xl font-bold font-label", valueColor)}>
        {value}
        {unit && <span className="text-xs text-primary/60 font-normal ml-1">{unit}</span>}
      </div>
      <div className={cn(
        "text-[10px] mt-4 flex items-center gap-1 font-bold",
        trendType === 'up' ? "text-primary" : trendType === 'warning' ? "text-tertiary" : "text-on-surface-variant"
      )}>
        {trendType === 'up' && <TrendingUp className="w-3.5 h-3.5" />}
        {trendType === 'warning' && <ShieldAlert className="w-3.5 h-3.5" />}
        {trendType === 'neutral' && <Activity className="w-3.5 h-3.5" />}
        {trend}
      </div>
    </div>
  );
}

function TimelineRow({ time, symbol, outcome, intent, decision, status }: any) {
  const statusColor = status === 'success' ? 'bg-primary' : status === 'warning' ? 'bg-tertiary' : 'bg-on-surface-variant/40';
  const decisionColor = status === 'success' ? 'text-primary' : status === 'error' ? 'text-error' : 'text-on-surface-variant/50';

  return (
    <tr className="hover:bg-surface-container-high transition-colors">
      <td className="px-6 py-4 text-xs font-mono text-on-surface-variant/80">{time}</td>
      <td className="px-6 py-4 text-xs font-bold font-label">{symbol}</td>
      <td className="px-6 py-4">
        <div className="flex items-center gap-2">
          <span className={cn("w-2 h-2 rounded-full", statusColor)}></span>
          <span className="text-xs font-medium">{outcome}</span>
        </div>
      </td>
      <td className="px-6 py-4">
        <span className={cn(
          "text-[10px] px-2 py-0.5 font-bold uppercase rounded-sm",
          intent === 'No Trade' ? "bg-surface-container-lowest text-on-surface-variant" : "bg-primary-container text-primary"
        )}>
          {intent}
        </span>
      </td>
      <td className="px-6 py-4 text-right">
        <span className={cn("text-[10px] font-bold font-label uppercase", decisionColor)}>{decision}</span>
      </td>
    </tr>
  );
}

function DistributionRow({ label, value, color }: any) {
  return (
    <div className="flex justify-between text-[10px]">
      <span className="text-on-surface-variant">{label}</span>
      <span className={cn("font-bold", color)}>{value}</span>
    </div>
  );
}

function NodeStatus({ id, status, active }: any) {
  return (
    <div className={cn(
      "h-10 border rounded-sm flex flex-col items-center justify-center",
      active ? "bg-primary/20 border-primary/40" : "bg-surface-container-low border-outline-variant/20 grayscale opacity-50"
    )}>
      <div className={cn("text-[8px] font-bold", active ? "text-primary/60" : "text-on-surface-variant")}>NODE_{id}</div>
      <div className="text-[10px] font-bold">{status}</div>
    </div>
  );
}
