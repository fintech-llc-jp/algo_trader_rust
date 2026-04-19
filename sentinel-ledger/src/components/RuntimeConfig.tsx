import React from 'react';
import { 
  Settings2, 
  AlertTriangle, 
  Code, 
  Lock, 
  CheckCircle2, 
  Info, 
  Zap,
  ArrowRightLeft
} from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '../lib/utils';

export default function RuntimeConfig() {
  return (
    <div className="space-y-8">
      {/* Hero Header & Execution Switch */}
      <div className="flex justify-between items-end pb-4 border-b border-outline-variant/10">
        <div>
          <h1 className="font-headline font-black text-3xl tracking-tighter text-on-surface">Runtime Configuration</h1>
          <p className="text-on-surface-variant text-sm mt-1">Configure real-time engine parameters and consensus thresholds.</p>
        </div>
        <div className="flex items-center gap-4 p-4 bg-surface-container-low rounded-lg shadow-xl shadow-black/20">
          <div className="text-right">
            <span className="block font-label text-[0.65rem] uppercase tracking-widest text-on-surface-variant">Execution Authority</span>
            <span className="font-label text-sm font-bold text-primary">LIVE MAINNET</span>
          </div>
          <div className="h-10 w-[1px] bg-outline-variant/30"></div>
          <button className="bg-surface-container-highest hover:bg-surface-bright px-4 py-2 rounded-sm font-label text-[0.75rem] uppercase tracking-widest font-bold transition-all flex items-center gap-2">
            <ArrowRightLeft className="w-4 h-4" />
            Switch to Dry Run
          </button>
        </div>
      </div>

      {/* Dashboard Layout: Bento Grid */}
      <div className="grid grid-cols-12 gap-6">
        {/* Runtime Settings (Left Side) */}
        <div className="col-span-12 lg:col-span-8 space-y-6">
          {/* Config Tabs */}
          <div className="bg-surface-container p-6 rounded-lg">
            <div className="flex items-center gap-8 mb-8 border-b border-outline-variant/10">
              <button className="pb-4 font-label text-[0.75rem] font-bold uppercase tracking-widest text-primary border-b-2 border-primary">Runtime Control</button>
              <button className="pb-4 font-label text-[0.75rem] font-medium uppercase tracking-widest text-on-surface-variant hover:text-on-surface">Vote Strategy</button>
              <button className="pb-4 font-label text-[0.75rem] font-medium uppercase tracking-widest text-on-surface-variant hover:text-on-surface">Risk Parameters</button>
            </div>
            
            <div className="grid grid-cols-2 gap-8">
              <div className="space-y-6">
                <ConfigField label="Tick Interval (ms)" value="100" badge="STABLE" helper="Minimum recommended interval is 50ms for low latency pools." />
                <ConfigField label="Default Quantity (USD)" value="50,000.00" />
                <div>
                  <label className="block font-label text-[0.7rem] uppercase tracking-widest text-on-surface-variant mb-2">Max Slippage Tolerance</label>
                  <div className="flex items-center gap-4">
                    <input className="flex-1 accent-primary" type="range" defaultValue={5} />
                    <span className="font-label font-bold text-primary">0.05%</span>
                  </div>
                </div>
              </div>
              <div className="space-y-6">
                <ConfigField label="Gas Ceiling (Gwei)" value="250" />
                <div className="bg-surface-container-low p-4 rounded-sm border-l-2 border-tertiary">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle className="w-4 h-4 text-tertiary" />
                    <span className="font-label text-[0.7rem] uppercase tracking-widest text-tertiary font-bold">Optimization Notice</span>
                  </div>
                  <p className="text-[0.75rem] text-on-surface-variant leading-relaxed">
                    Current gas settings may cause transaction failure if network congestion exceeds 300 Gwei.
                  </p>
                </div>
              </div>
            </div>
            
            <div className="mt-10 flex justify-end gap-3">
              <button className="px-6 py-2 bg-surface-container-highest text-on-surface font-label text-[0.75rem] uppercase tracking-widest font-bold rounded-sm hover:bg-surface-bright">Discard Changes</button>
              <button className="px-6 py-2 bg-primary text-on-primary font-label text-[0.75rem] uppercase tracking-widest font-bold rounded-sm hover:brightness-110 shadow-lg shadow-primary/10">Commit & Restart Engine</button>
            </div>
          </div>

          {/* Raw TOML Preview / Diff Viewer */}
          <div className="bg-surface-container-low rounded-lg overflow-hidden flex flex-col border border-outline-variant/10">
            <div className="px-6 py-3 bg-surface-container border-b border-outline-variant/10 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <Code className="w-4 h-4 text-on-surface-variant" />
                <span className="font-label text-[0.75rem] uppercase tracking-widest font-bold">Config Diff Viewer</span>
              </div>
              <span className="font-label text-[0.65rem] text-on-surface-variant">runtime.toml — (Unsaved Changes)</span>
            </div>
            <div className="p-6 bg-surface-container-lowest font-mono text-[0.8rem] leading-relaxed overflow-x-auto min-h-[300px]">
              <DiffLine num={12} content="[runtime]" />
              <DiffLine num={13} content="tick_interval = 100" />
              <DiffLine num={14} content="- default_quantity = 25000" type="removed" />
              <DiffLine num={15} content="+ default_quantity = 50000" type="added" />
              <DiffLine num={16} content="gas_ceiling = 250" />
              <DiffLine num={17} content='slippage_tolerance = "0.0005"' />
              <DiffLine num={18} content="" />
              <DiffLine num={19} content="[consensus]" />
              <DiffLine num={20} content="quorum_threshold = 0.66" />
            </div>
          </div>
        </div>

        {/* Global Safety & Validation (Right Side) */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          {/* Kill Switch */}
          <div className="bg-surface-container p-8 rounded-lg flex flex-col items-center text-center space-y-6 relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-t from-error/5 to-transparent pointer-events-none"></div>
            <motion.div 
              whileHover={{ scale: 1.05 }}
              className="relative"
            >
              <div className="w-24 h-24 rounded-full bg-error-container flex items-center justify-center border-4 border-error/30 cursor-pointer shadow-[0_0_40px_rgba(255,180,171,0.2)]">
                <Zap className="w-10 h-10 text-error fill-error" />
              </div>
            </motion.div>
            <div>
              <h3 className="font-headline font-extrabold text-xl tracking-tight text-on-surface">Emergency Kill Switch</h3>
              <p className="text-on-surface-variant text-xs mt-2 font-label uppercase tracking-wider">Instant cessation of all active liquidations</p>
            </div>
            <button className="w-full py-4 bg-error text-on-error font-black uppercase tracking-[0.2em] rounded-sm hover:brightness-110 active:scale-[0.98] transition-all">
              Engage Protocol
            </button>
            <div className="flex items-center gap-2 text-[0.65rem] font-label font-bold text-on-surface-variant/50">
              <Lock className="w-3.5 h-3.5" />
              MFA AUTHORIZATION REQUIRED
            </div>
          </div>

          {/* Validation Feed */}
          <div className="bg-surface-container-low rounded-lg border border-outline-variant/10 overflow-hidden">
            <div className="px-6 py-4 bg-surface-container border-b border-outline-variant/10">
              <h4 className="font-label text-[0.7rem] uppercase tracking-widest font-bold">Validation Feedback</h4>
            </div>
            <div className="p-4 space-y-4 max-h-[300px] overflow-y-auto">
              <ValidationItem 
                type="success" 
                title="Syntax Check Passed" 
                desc="TOML formatting is compliant with v4 schema." 
              />
              <ValidationItem 
                type="warning" 
                title="Quantity Out of Bounds" 
                desc="50,000 USD is 200% above moving average. Verify intent." 
              />
              <ValidationItem 
                type="info" 
                title="Quorum Update Required" 
                desc="Changes to vote strategy require multi-sig consensus." 
              />
            </div>
          </div>

          {/* System Status Panel */}
          <div className="bg-surface-container p-6 rounded-lg space-y-4">
            <h4 className="font-label text-[0.7rem] uppercase tracking-widest font-bold text-on-surface-variant mb-2">Infrastructure Health</h4>
            <StatusProgress label="RPC Node Latency" value="12ms" progress={88} color="bg-primary" />
            <StatusProgress label="Mem-Pool Depth" value="842 tx/s" progress={62} color="bg-tertiary" />
            <div className="flex justify-between items-center text-xs">
              <span className="text-on-surface-variant">Vault Connectivity</span>
              <span className="font-label font-bold text-primary">SECURE</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ConfigField({ label, value, badge, helper }: any) {
  return (
    <div>
      <label className="block font-label text-[0.7rem] uppercase tracking-widest text-on-surface-variant mb-2">{label}</label>
      <div className="relative">
        <input 
          className="w-full bg-surface-container-lowest border-none focus:ring-1 focus:ring-primary rounded-sm font-label text-lg p-3 text-on-surface" 
          type="text" 
          defaultValue={value} 
        />
        {badge && (
          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[0.65rem] font-label font-bold text-primary">{badge}</span>
        )}
      </div>
      {helper && <p className="text-[0.65rem] mt-2 text-on-surface-variant/70 italic">{helper}</p>}
    </div>
  );
}

function DiffLine({ num, content, type }: any) {
  return (
    <div className={cn(
      "flex gap-4 px-6 -mx-6",
      type === 'removed' ? "bg-error-container/20 text-error" : type === 'added' ? "bg-primary-container/30 text-primary" : "opacity-50"
    )}>
      <span className="w-6 text-right select-none">{num}</span>
      <span>{content}</span>
    </div>
  );
}

function ValidationItem({ type, title, desc }: any) {
  const icon = type === 'success' ? <CheckCircle2 className="w-4 h-4 text-primary" /> : type === 'warning' ? <AlertTriangle className="w-4 h-4 text-tertiary" /> : <Info className="w-4 h-4 text-on-surface-variant" />;
  const border = type === 'success' ? 'border-primary' : type === 'warning' ? 'border-tertiary' : 'border-outline-variant';
  const bg = type === 'success' ? 'bg-primary-container/10' : type === 'warning' ? 'bg-tertiary-container/20' : 'bg-surface-container-high/40';

  return (
    <div className={cn("flex gap-4 p-3 border-l-2", border, bg)}>
      {icon}
      <div>
        <p className="text-[0.75rem] font-bold text-on-surface">{title}</p>
        <p className="text-[0.7rem] text-on-surface-variant mt-1">{desc}</p>
      </div>
    </div>
  );
}

function StatusProgress({ label, value, progress, color }: any) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center text-xs">
        <span className="text-on-surface-variant">{label}</span>
        <span className={cn("font-label font-bold", color.replace('bg-', 'text-'))}>{value}</span>
      </div>
      <div className="h-1 bg-surface-container-lowest overflow-hidden rounded-full">
        <div className={cn("h-full", color)} style={{ width: `${progress}%` }}></div>
      </div>
    </div>
  );
}
