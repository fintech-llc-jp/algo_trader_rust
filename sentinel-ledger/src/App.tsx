import React, { useState } from 'react';
import { 
  LayoutDashboard, 
  TrendingUp, 
  ShieldAlert, 
  Settings2, 
  History, 
  Search, 
  Bell, 
  Settings, 
  Power,
  Shield,
  BookOpen,
  HelpCircle
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from './lib/utils';

// Views
import Dashboard from './components/Dashboard';
import StrategyMonitor from './components/StrategyMonitor';
import RiskControl from './components/RiskControl';
import RuntimeConfig from './components/RuntimeConfig';
import AuditLog from './components/AuditLog';

type View = 'DASHBOARD' | 'STRATEGY' | 'RISK' | 'RUNTIME' | 'AUDIT';

export default function App() {
  const [currentView, setCurrentView] = useState<View>('DASHBOARD');

  const navItems = [
    { id: 'DASHBOARD', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'STRATEGY', label: 'Strategy & Vote', icon: TrendingUp },
    { id: 'RISK', label: 'Risk Control', icon: ShieldAlert },
    { id: 'RUNTIME', label: 'Runtime & Config', icon: Settings2 },
    { id: 'AUDIT', label: 'Audit Log', icon: History },
  ];

  const renderView = () => {
    switch (currentView) {
      case 'DASHBOARD': return <Dashboard />;
      case 'STRATEGY': return <StrategyMonitor />;
      case 'RISK': return <RiskControl />;
      case 'RUNTIME': return <RuntimeConfig />;
      case 'AUDIT': return <AuditLog />;
      default: return <Dashboard />;
    }
  };

  return (
    <div className="flex min-h-screen bg-background text-on-surface font-sans">
      {/* SideNavBar */}
      <aside className="fixed left-0 top-0 h-full w-64 z-40 bg-surface flex flex-col pt-20 pb-6 border-r border-outline-variant/15">
        <div className="px-6 mb-8">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-8 h-8 bg-primary-container flex items-center justify-center rounded-sm">
              <Shield className="w-5 h-5 text-primary fill-primary" />
            </div>
            <div>
              <div className="text-[0.75rem] font-bold tracking-[0.15em] text-on-surface uppercase font-label">SENTINEL</div>
              <div className="text-[10px] text-on-surface-variant/50 font-mono">v4.2.0-stable</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setCurrentView(item.id as View)}
              className={cn(
                "w-full flex items-center px-6 py-3 text-[0.75rem] font-bold tracking-wider font-label uppercase transition-all duration-200 ease-in-out",
                currentView === item.id 
                  ? "text-primary border-r-2 border-primary bg-surface-container" 
                  : "text-on-surface/50 hover:text-on-surface hover:bg-surface-container"
              )}
            >
              <item.icon className="w-5 h-5 mr-4" />
              {item.label}
            </button>
          ))}
        </nav>

        <div className="px-6 mt-auto space-y-4">
          <div className="py-3 px-4 bg-primary-container/30 border border-primary/20 rounded-sm">
            <div className="text-[10px] text-primary mb-1 font-bold font-label tracking-widest uppercase">Engine Status</div>
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></div>
              <span className="text-[0.7rem] font-bold text-on-primary-container tracking-tighter">RUNNING</span>
            </div>
          </div>
          <div className="space-y-1">
            <button className="w-full flex items-center py-2 text-[0.65rem] font-bold tracking-widest text-on-surface-variant/50 hover:text-on-surface uppercase font-label">
              <BookOpen className="w-4 h-4 mr-3" />
              Documentation
            </button>
            <button className="w-full flex items-center py-2 text-[0.65rem] font-bold tracking-widest text-on-surface-variant/50 hover:text-on-surface uppercase font-label">
              <HelpCircle className="w-4 h-4 mr-3" />
              Support
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 ml-64">
        {/* TopNavBar */}
        <header className="fixed top-0 right-0 left-64 z-50 bg-surface flex justify-between items-center h-14 px-6 border-b border-outline-variant/15">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 px-3 py-1 bg-surface-container-low rounded-sm">
              <Search className="w-4 h-4 text-primary" />
              <input 
                className="bg-transparent border-none focus:ring-0 text-xs w-64 placeholder-on-surface-variant/50" 
                placeholder="Search logs, symbols, or TXIDs..." 
                type="text"
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button className="px-3 py-1 text-xs font-bold bg-primary text-on-primary rounded-sm transition-all scale-95 active:duration-100">LIVE</button>
            <button className="px-3 py-1 text-xs font-medium border border-outline-variant/30 text-on-surface/70 hover:bg-surface-container transition-colors rounded-sm">DRY_RUN</button>
            <div className="flex items-center gap-4 ml-4">
              <button className="text-on-surface-variant hover:text-primary transition-colors">
                <Bell className="w-5 h-5" />
              </button>
              <button className="text-on-surface-variant hover:text-primary transition-colors">
                <Settings className="w-5 h-5" />
              </button>
              <button className="text-on-surface-variant hover:text-error transition-colors">
                <Power className="w-5 h-5" />
              </button>
              <img 
                alt="User profile" 
                className="w-7 h-7 rounded-full border border-outline-variant/20 ml-2" 
                src="https://lh3.googleusercontent.com/aida-public/AB6AXuB0_1oj8XjGrn8pHCXLDAncx780i6vgw7sDVTVP28UQZXP73fAG_1XQ8cwaOJknQYF6oIpSxxg_A0lZ36bpDYERY4GZqnr6fP6qB6z0aTjqC_KcRs1NdnDaAy-QoYOo_hPrJjqEO0s-QXnFw2GliV7F5poPOprFOjKg-xW_VzMOEH5WDyjtWLF_rxvsMHTvji0eQ-y3HqedrwrpHYD9kpdwKe-uwoj2FKIIgoy-941ne2UHAM2wgi2ENJAfSEfxjmhtuGaaGdlF8vkJ"
                referrerPolicy="no-referrer"
              />
            </div>
          </div>
        </header>

        {/* View Container */}
        <main className="mt-14 p-8 min-h-[calc(100vh-3.5rem)] overflow-y-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentView}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className="max-w-[1400px] mx-auto"
            >
              {renderView()}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
