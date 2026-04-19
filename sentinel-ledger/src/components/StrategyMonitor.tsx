import React from 'react';
import { 
  ChevronLeft, 
  ChevronRight, 
  ChevronsLeft, 
  ChevronsRight, 
  Terminal, 
  Filter, 
  Search, 
  Edit3, 
  TrendingUp, 
  Rocket, 
  CheckCircle2,
  Zap
} from 'lucide-react';
import { cn } from '../lib/utils';
import { LineChart, Line, ResponsiveContainer } from 'recharts';

const sparkData = [
  { v: 30 }, { v: 45 }, { v: 60 }, { v: 50 }, { v: 75 }, { v: 95 }, { v: 80 }, { v: 90 }
];

export default function StrategyMonitor() {
  return (
    <div className="space-y-8">
      {/* Header & Tick Selector */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-on-surface">Strategy & Vote Monitor</h1>
          <p className="text-on-surface-variant text-sm mt-1">Real-time signal reconciliation and order intent validation.</p>
        </div>
        
        {/* Tick Selector */}
        <div className="flex items-center bg-surface-container rounded-sm p-1 border border-outline-variant/10 shadow-2xl">
          <div className="flex items-center border-r border-outline-variant/20 pr-2">
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><ChevronsLeft className="w-4 h-4" /></button>
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><ChevronLeft className="w-4 h-4" /></button>
          </div>
          <div className="flex gap-1 px-4 items-center">
            <span className="text-[10px] font-label text-on-surface-variant uppercase tracking-tighter">Current Tick:</span>
            <span className="font-label font-bold text-primary tracking-widest">#842,109,223</span>
          </div>
          <div className="flex items-center border-l border-outline-variant/20 pl-2">
            <div className="flex items-center gap-2 px-4">
              <span className="w-1 h-1 rounded-full bg-primary"></span>
              <span className="text-[10px] font-label text-on-surface uppercase tracking-widest">T - 0s</span>
            </div>
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><ChevronRight className="w-4 h-4" /></button>
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><ChevronsRight className="w-4 h-4" /></button>
          </div>
        </div>
      </div>

      {/* Bento Grid Layout */}
      <div className="grid grid-cols-12 gap-6">
        {/* Strategy Votes Table */}
        <section className="col-span-12 lg:col-span-8 flex flex-col bg-surface-container-low rounded-lg overflow-hidden min-h-[500px]">
          <div className="flex justify-between items-center px-6 py-4 bg-surface-container">
            <div className="flex items-center gap-4">
              <h2 className="text-sm font-label font-bold uppercase tracking-widest">Strategy Votes</h2>
              <div className="h-4 w-[1px] bg-outline-variant/30"></div>
              <div className="flex items-center gap-2 text-[10px] font-label text-on-surface-variant">
                <Filter className="w-3.5 h-3.5" />
                <span>12 ACTIVE SOURCES</span>
              </div>
            </div>
            <div className="flex gap-4">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-on-surface-variant" />
                <input 
                  className="bg-surface-container-lowest border-none text-[10px] font-label uppercase tracking-widest w-32 pl-8 focus:ring-1 focus:ring-primary rounded-sm" 
                  placeholder="STRATEGY_ID" 
                  type="text"
                />
              </div>
              <select className="bg-surface-container-lowest border-none text-[10px] font-label uppercase tracking-widest pr-8 focus:ring-1 focus:ring-primary rounded-sm">
                <option>ALL SIDES</option>
                <option>BUY</option>
                <option>SELL</option>
              </select>
            </div>
          </div>
          
          <div className="flex-1 overflow-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-container-lowest/50 text-[10px] font-label font-bold text-on-surface-variant uppercase tracking-widest">
                  <th className="px-6 py-4">Strategy ID</th>
                  <th className="px-4 py-4">Side</th>
                  <th className="px-4 py-4 text-right">Strength</th>
                  <th className="px-4 py-4 text-right">Weight</th>
                  <th className="px-6 py-4 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/5">
                <VoteRow id="ALPHA_TREND_V4" side="BUY" strength="0.892" weight="0.45" status="VERIFIED" />
                <VoteRow id="MEAN_REV_SCALPER" side="SELL" strength="0.210" weight="0.12" status="VERIFIED" />
                <VoteRow id="VOLATILITY_BREAK_X" side="BUY" strength="0.654" weight="0.30" status="STALE_DATA" statusColor="text-tertiary" />
                <VoteRow id="HFT_LIQUIDITY_MAP" side="NEUTRAL" strength="0.000" weight="0.10" status="VERIFIED" />
                <VoteRow id="MOMENTUM_PULSE_SR" side="BUY" strength="0.441" weight="0.03" status="VERIFIED" />
              </tbody>
            </table>
          </div>
          
          <div className="p-6 bg-surface-container-lowest/30 border-t border-outline-variant/10">
            <div className="flex items-center justify-between">
              <div className="flex gap-2">
                <div className="w-1.5 h-1.5 bg-primary rounded-full"></div>
                <div className="w-1.5 h-1.5 bg-primary/40 rounded-full"></div>
                <div className="w-1.5 h-1.5 bg-primary/20 rounded-full"></div>
              </div>
              <span className="text-[10px] font-label text-on-surface-variant uppercase tracking-[0.2em]">Live Data Stream Synchronized</span>
            </div>
          </div>
        </section>

        {/* Aggregation & Intent Panels */}
        <section className="col-span-12 lg:col-span-4 flex flex-col gap-6">
          <div className="bg-surface-container-high p-6 rounded-lg border border-outline-variant/5 shadow-xl relative overflow-hidden">
            <h2 className="text-xs font-label font-bold uppercase tracking-widest mb-6 flex items-center gap-2">
              <TrendingUp className="w-3.5 h-3.5 text-primary" />
              Aggregation Panel
            </h2>
            <div className="space-y-6">
              <div className="flex justify-between items-end border-b border-outline-variant/10 pb-4">
                <div>
                  <div className="text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-1">Policy Mode</div>
                  <div className="text-lg font-bold text-primary font-headline">WEIGHTED_CONSENSUS</div>
                </div>
                <Edit3 className="w-5 h-5 text-primary cursor-pointer" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-surface-container-low p-4 rounded-sm border border-outline-variant/5">
                  <div className="text-[9px] font-label text-on-surface-variant uppercase tracking-widest mb-2">Buy Totals</div>
                  <div className="text-xl font-label font-bold text-primary">12.42M</div>
                </div>
                <div className="bg-surface-container-low p-4 rounded-sm border border-outline-variant/5">
                  <div className="text-[9px] font-label text-on-surface-variant uppercase tracking-widest mb-2">Sell Totals</div>
                  <div className="text-xl font-label font-bold text-on-surface-variant">2.15M</div>
                </div>
              </div>
              <div className="bg-surface-container-lowest p-5 rounded-sm">
                <div className="flex justify-between items-center mb-3">
                  <span className="text-[10px] font-label text-on-surface-variant uppercase tracking-widest">Net Strength</span>
                  <span className="text-[10px] font-label text-primary uppercase font-bold">+ 78.4%</span>
                </div>
                <div className="h-2 w-full bg-surface-container-high rounded-full overflow-hidden">
                  <div className="h-full bg-primary" style={{ width: '78.4%' }}></div>
                </div>
              </div>
              <div className="mt-8 pt-6 border-t border-primary/20">
                <div className="text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-2">Final Vote Outcome</div>
                <div className="flex items-center gap-4">
                  <div className="text-4xl font-black font-headline text-primary tracking-tighter">BULLISH</div>
                  <div className="flex-1 h-[1px] bg-primary/20"></div>
                  <TrendingUp className="w-8 h-8 text-primary" />
                </div>
              </div>
            </div>
          </div>

          <div className="bg-surface-container p-6 rounded-lg border border-outline-variant/5 shadow-xl relative overflow-hidden flex-1">
            <h2 className="text-xs font-label font-bold uppercase tracking-widest mb-6 flex items-center gap-2">
              <Rocket className="w-3.5 h-3.5 text-primary" />
              Intent Panel
            </h2>
            <div className="flex flex-col h-full justify-between gap-6">
              <div className="space-y-4">
                <div className="p-4 rounded-sm border border-primary/30 bg-primary/5">
                  <div className="flex items-center gap-3 mb-2">
                    <CheckCircle2 className="w-5 h-5 text-primary" />
                    <div className="text-sm font-bold text-on-surface font-headline uppercase tracking-tight">Intent: PlaceOrder</div>
                  </div>
                  <div className="text-[11px] text-on-surface-variant leading-relaxed">
                    Consensus threshold met (78.4% &gt; 65.0%). Risk validation engine cleared for execution. Execution Venue: BINANCE_FUTURES_USDT.
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <div className="text-[9px] font-label text-on-surface-variant uppercase tracking-widest">Target Size</div>
                    <div className="text-sm font-label font-bold">12.5 BTC</div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-[9px] font-label text-on-surface-variant uppercase tracking-widest">Entry Limit</div>
                    <div className="text-sm font-label font-bold">42,912.50</div>
                  </div>
                </div>
              </div>
              <div className="space-y-3 pt-6 border-t border-outline-variant/10 mt-auto">
                <button className="w-full py-4 bg-primary text-on-primary font-label font-bold uppercase tracking-widest text-xs hover:opacity-90 active:scale-[0.98] transition-all">
                  Authorize Manual Override
                </button>
                <button className="w-full py-4 bg-surface-container-highest text-on-surface font-label font-bold uppercase tracking-widest text-xs hover:bg-surface-bright transition-all">
                  Discard Intent
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* Footer Sparklines */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <FooterMetric label="Latency" value="12ms" />
        <FooterMetric label="Signals/Sec" value="1,204" />
        <FooterMetric label="Risk Buffer" value="94.2%" />
        <FooterMetric label="Total PnL (D)" value="+$4,210" />
      </div>

      {/* Global KillSwitch */}
      <div className="fixed bottom-8 right-8 z-[100]">
        <button className="flex items-center gap-3 px-6 py-4 bg-error text-on-error font-label font-bold uppercase tracking-widest rounded-sm shadow-[0_0_40px_rgba(255,180,171,0.2)] hover:scale-105 active:scale-95 transition-all group">
          <Zap className="w-5 h-5 group-hover:animate-pulse" />
          KillSwitch: GLOBAL_HALT
        </button>
      </div>
    </div>
  );
}

function VoteRow({ id, side, strength, weight, status, statusColor = "text-primary" }: any) {
  const sideColor = side === 'BUY' ? 'bg-primary-container text-primary' : side === 'SELL' ? 'bg-error-container text-error' : 'bg-surface-container-highest text-on-surface-variant';
  return (
    <tr className="hover:bg-surface-container-high transition-colors group">
      <td className="px-6 py-4 text-[11px] font-label text-primary font-medium tracking-tight">{id}</td>
      <td className="px-4 py-4">
        <span className={cn("px-2 py-0.5 text-[9px] font-bold rounded-sm tracking-widest uppercase", sideColor)}>{side}</span>
      </td>
      <td className="px-4 py-4 text-right font-label text-xs">{strength}</td>
      <td className="px-4 py-4 text-right font-label text-xs">{weight}</td>
      <td className="px-6 py-4 text-right">
        <span className={cn("text-[10px] font-label tracking-widest", statusColor)}>{status}</span>
      </td>
    </tr>
  );
}

function FooterMetric({ label, value }: any) {
  return (
    <div className="bg-surface-container-low p-4 rounded-lg flex items-center justify-between border border-outline-variant/5">
      <div>
        <div className="text-[9px] font-label text-on-surface-variant uppercase tracking-widest mb-1">{label}</div>
        <div className="text-lg font-label font-bold text-primary">{value}</div>
      </div>
      <div className="w-16 h-8 bg-primary/10 rounded-sm overflow-hidden">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={sparkData}>
            <Line type="monotone" dataKey="v" stroke="#7bd0ff" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
