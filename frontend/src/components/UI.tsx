import type { ReactNode } from 'react';
import { Activity, WifiOff } from 'lucide-react';

export function Signal({ value }: { value: string }) {
  return <span className={`signal ${value.toLowerCase().replace(' ', '-')}`}>{value}</span>;
}
export function ErrorBox({ message }: { message: string }) {
  return <div className="error"><WifiOff size={16}/>{message}</div>;
}
export function Empty({ children = 'No records yet' }: { children?: string }) {
  return <div className="empty"><span className="empty-icon"><Activity size={20}/></span><b>{children}</b><span>Data will appear here when available from your API.</span></div>;
}
export function Metric({ icon, label, value, sub, tone = '' }: { icon: ReactNode; label: string; value: string; sub: string; tone?: string }) {
  return <div className="metric"><div className="metric-head"><span>{label}</span><span className="metric-icon">{icon}</span></div><strong className={tone}>{value}</strong><small>{sub}</small></div>;
}
export function PanelTitle({ title, action }: { title: string; action: () => void }) {
  return <div className="panel-title"><b>{title}</b><button className="dots" onClick={action}>···</button></div>;
}
