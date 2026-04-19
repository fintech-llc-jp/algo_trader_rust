import React from 'react';
import { Shield, AlertTriangle, Search, Download, Info, BarChart3, PieChart, AlertCircle } from 'lucide-react';
import { cn } from '../lib/utils';
import { BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip, Cell } from 'recharts';

const velocityData = [
  { time: '00:00', value: 20 },
  { time: '02:00', value: 35 },
  { time: '04:00', value: 30 },
  { time: '06:00', value: 55 },
  { time: '08:00', value: 85 },
  { time: '10:00', value: 95 },
  { time: '12:00', value: 40 },
  { time: '14:00', value: 25 },
  { time: '16:00', value: 30 },
  { time: '18:00', value: 15 },
  { time: '20:00', value: 45 },
  { time: '22:00', value: 50 },
];

export default function RiskControl() {
  return (
    <div className="space-y-10">
      {/* Header Section */}
      <header className="flex flex-col lg:flex-row justify-between items-start lg:items-end gap-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-on-surface mb-2">Risk Control</h1>
          <p className="text-on-surface-variant max-w-2xl text-sm">Real-time exposure management and systemic safety thresholds. Changes to risk parameters require multi-sig validation.</p>
        </div>
        <div className="bg-surface-container p-6 rounded-lg border-l-4 border-primary min-w-[280px]">
          <span className="text-[10px] font-label uppercase tracking-widest text-primary block mb-1">Daily PnL Realized</span>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-black font-label text-primary">$142,890.42</span>
            <span className="text-primary text-xs font-bold font-label">+2.4%</span>
          </div>
          <div className="mt-4 h-8 w-full">
            <div className="flex items-end h-full gap-[2px]">
              {[30, 45, 60, 40, 75, 100].map((h, i) => (
                <div key={i} className={cn("w-full bg-primary/20", i === 5 && "bg-primary")} style={{ height: `${h}%` }}></div>
              ))}
            </div>
          </div>
        </div>
      </header>

      {/* Risk Limits Bento Grid */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <LimitCard title="Max Position Size" value="50.0 BTC" utilization={65} current="32.5 BTC" icon={<BarChart3 className="w-5 h-5 text-primary/50" />} />
        <LimitCard title="Max Order Size" value="5.0 BTC" utilization={12} current="0.6 BTC" icon={<BarChart3 className="w-5 h-5 text-primary/50" />} />
        <LimitCard 
          title="Max Daily Loss" 
          value="$250,000" 
          utilization={88.5} 
          current="-$221,400" 
          alert="THRESHOLD NEAR" 
          isError 
          icon={<AlertTriangle className="w-5 h-5 text-error/50" />} 
        />
      </section>

      {/* Main Content Area */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-8">
        {/* Risk Decision Log */}
        <div className="xl:col-span-8 flex flex-col gap-6">
          <div className="bg-surface-container-low rounded-lg p-6 border border-outline-variant/10">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant">Risk Decision Log</h3>
              <button className="text-[10px] font-label text-primary hover:underline">EXPORT REPORT</button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-separate border-spacing-y-1">
                <thead className="text-[10px] font-label text-on-surface-variant uppercase tracking-widest">
                  <tr>
                    <th className="pb-3 px-4 font-medium">Timestamp</th>
                    <th className="pb-3 px-4 font-medium">Trigger</th>
                    <th className="pb-3 px-4 font-medium">Action</th>
                    <th className="pb-3 px-4 font-medium">Status</th>
                    <th className="pb-3 px-4 text-right font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="text-xs font-label">
                  <DecisionRow time="14:22:01.004" trigger="LATENCY_SPIKE" action="THROTTLE_ORDERS" status="ACTIVE" detail="MS_LIMIT > 250ms" statusType="primary" />
                  <DecisionRow time="14:18:45.923" trigger="POS_CONCENTRATION" action="BLOCK_NEW_POS" status="BLOCKED" detail="XBTUSD > 40% EXP" statusType="error" />
                  <DecisionRow time="14:05:12.112" trigger="MANUAL_OVERRIDE" action="RESET_DAILY_LOSS" status="COMPLETED" detail="AUTH: ADMIN_04" statusType="neutral" />
                  <DecisionRow time="13:58:22.094" trigger="ORDER_SIZE_LIM" action="REJECT_ORDER" status="REJECTED" detail="8.2 BTC > 5.0 BTC" statusType="error" />
                  <DecisionRow time="13:42:01.442" trigger="FEE_ANOMALY" action="LOG_ONLY" status="MONITOR" detail="TakerFee > 5bps" statusType="neutral" />
                </tbody>
              </table>
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-surface-container-low p-6 rounded-lg border border-outline-variant/10">
              <h3 className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-6 text-center">Block Reason Distribution</h3>
              <div className="flex justify-center items-center py-4">
                <div className="relative w-32 h-32 rounded-full border-8 border-primary-container flex items-center justify-center">
                  <div className="absolute inset-0 rounded-full border-t-8 border-error border-l-8 border-transparent rotate-45"></div>
                  <div className="absolute inset-0 rounded-full border-r-8 border-tertiary border-b-8 border-transparent -rotate-12"></div>
                  <span className="text-xl font-bold font-label">984</span>
                </div>
                <div className="ml-8 space-y-2">
                  <LegendItem color="bg-error" label="LOSS LIMIT (62%)" />
                  <LegendItem color="bg-tertiary" label="POS LIMIT (28%)" />
                  <LegendItem color="bg-primary" label="OTHER (10%)" />
                </div>
              </div>
            </div>
            <div className="bg-surface-container-low p-6 rounded-lg border border-outline-variant/10">
              <h3 className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-4">Risk Velocity (24h)</h3>
              <div className="h-32 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={velocityData}>
                    <Bar dataKey="value" radius={[2, 2, 0, 0]}>
                      {velocityData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.value > 80 ? '#ffb4ab' : '#7bd0ff4d'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-between mt-2">
                <span className="text-[8px] font-label text-on-surface-variant">00:00</span>
                <span className="text-[8px] font-label text-on-surface-variant">12:00</span>
                <span className="text-[8px] font-label text-on-surface-variant">23:59</span>
              </div>
            </div>
          </div>
        </div>

        {/* Update Thresholds Form */}
        <div className="xl:col-span-4">
          <div className="bg-surface-container-high p-6 rounded-lg border border-primary/20 sticky top-24">
            <div className="flex items-center gap-3 mb-8">
              <Shield className="w-5 h-5 text-primary" />
              <h3 className="text-[10px] font-label uppercase tracking-widest text-on-surface font-bold">Update Thresholds</h3>
            </div>
            <form className="space-y-6">
              <FormField label="Max Position Size (BTC)" value="50.0" helper="Minimum change increment: 0.1 BTC" />
              <FormField label="Max Order Size (BTC)" value="5.0" />
              <FormField label="Max Daily Loss (USD)" value="250,000" isError errorMsg="Input value must exceed current realized daily loss ($221k)" />
              
              <div className="pt-4 border-t border-outline-variant/10">
                <div className="flex items-center mb-6 bg-error/5 p-4 rounded-sm border border-error/20">
                  <AlertTriangle className="w-5 h-5 text-error mr-3" />
                  <div>
                    <p className="text-[10px] font-bold text-error uppercase">Master KillSwitch</p>
                    <p className="text-[8px] text-on-surface-variant">Immediately cancel all orders and flatten positions.</p>
                  </div>
                </div>
                <div className="flex flex-col gap-3">
                  <button className="w-full bg-primary py-4 text-on-primary font-label font-bold text-xs rounded-sm tracking-widest hover:brightness-110 transition-all">
                    REQUEST UPDATE
                  </button>
                  <button className="w-full border border-outline-variant/30 py-3 text-on-surface-variant font-label text-[10px] font-bold rounded-sm tracking-widest hover:bg-surface-container transition-all">
                    CANCEL CHANGES
                  </button>
                </div>
              </div>
            </form>
            <div className="mt-8 flex justify-between text-[10px] text-on-surface-variant font-label">
              <span className="flex items-center"><span className="w-1.5 h-1.5 bg-primary rounded-full mr-2"></span> System Ready</span>
              <span>Session: 14:42:10 UTC</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LimitCard({ title, value, utilization, current, icon, alert, isError }: any) {
  return (
    <div className={cn(
      "bg-surface-container p-6 rounded-lg border relative overflow-hidden",
      isError ? "border-error/30" : "border-outline-variant/10"
    )}>
      {alert && (
        <div className="absolute top-0 right-0 p-2">
          <div className="bg-error/10 text-error text-[8px] font-bold px-1.5 py-0.5 rounded-sm animate-pulse">{alert}</div>
        </div>
      )}
      <div className="flex justify-between items-start mb-4">
        <span className={cn("text-[10px] font-label uppercase tracking-widest", isError ? "text-error" : "text-on-surface-variant")}>{title}</span>
        {icon}
      </div>
      <div className="flex flex-col">
        <span className="text-3xl font-label font-bold text-on-surface mb-1">{value}</span>
        <div className="w-full bg-surface-container-lowest h-1.5 mt-2 overflow-hidden">
          <div className={cn("h-full", isError ? "bg-error" : "bg-primary")} style={{ width: `${utilization}%` }}></div>
        </div>
        <div className="flex justify-between mt-2">
          <span className={cn("text-[10px] font-label", isError ? "text-error" : "text-on-surface-variant")}>CURRENT: {current}</span>
          <span className={cn("text-[10px] font-label", isError ? "text-error" : "text-on-surface-variant")}>UTILIZATION: {utilization}%</span>
        </div>
      </div>
    </div>
  );
}

function DecisionRow({ time, trigger, action, status, statusType, detail }: any) {
  const statusColor = statusType === 'primary' ? 'bg-primary/10 text-primary' : statusType === 'error' ? 'bg-error/10 text-error' : 'bg-surface-container-highest text-on-surface-variant';
  return (
    <tr className="bg-surface-container hover:bg-surface-container-high transition-colors group">
      <td className="py-3 px-4 text-on-surface-variant">{time}</td>
      <td className="py-3 px-4 font-bold">{trigger}</td>
      <td className={cn("py-3 px-4", action.includes('THROTTLE') ? "text-tertiary" : action.includes('BLOCK') || action.includes('REJECT') ? "text-error" : "text-on-surface")}>{action}</td>
      <td className="py-3 px-4"><span className={cn("px-2 py-0.5 rounded-sm", statusColor)}>{status}</span></td>
      <td className="py-3 px-4 text-right text-on-surface-variant">{detail}</td>
    </tr>
  );
}

function LegendItem({ color, label }: any) {
  return (
    <div className="flex items-center gap-2">
      <div className={cn("w-2 h-2 rounded-sm", color)}></div>
      <span className="text-[10px] font-label text-on-surface-variant">{label}</span>
    </div>
  );
}

function FormField({ label, value, helper, isError, errorMsg }: any) {
  return (
    <div>
      <label className={cn("text-[10px] font-label uppercase tracking-widest mb-2 block", isError ? "text-error" : "text-on-surface-variant")}>{label}</label>
      <div className="relative">
        <input 
          className={cn(
            "w-full bg-surface-container-lowest border-none font-label p-3 rounded-sm focus:ring-1 focus:ring-primary",
            isError ? "ring-1 ring-error text-error" : "text-on-surface"
          )} 
          type="text" 
          defaultValue={value} 
        />
        {isError && <AlertCircle className="absolute right-3 top-3 text-error w-4 h-4" />}
      </div>
      {helper && <p className="text-[10px] text-on-surface-variant mt-1.5 italic">{helper}</p>}
      {isError && <p className="text-[10px] text-error mt-1.5 font-medium">{errorMsg}</p>}
    </div>
  );
}
