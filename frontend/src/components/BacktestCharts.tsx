import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { money } from '../utils/format';
import type { Backtest } from '../types/api';

const validPoints = <T extends { date: string }>(points: T[], fields: (keyof T)[]) =>
  points.filter((point) => Boolean(point) && typeof point.date === 'string' && Number.isFinite(Date.parse(point.date)) && fields.every((field) =>
    typeof point[field] === 'number' && Number.isFinite(point[field]),
  ));

function Chart({ data, fields, names }: { data: Array<Record<string, string | number>>; fields: string[]; names: string[] }) {
  return <div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data}>
    <CartesianGrid stroke="#202b38" vertical={false}/>
    <XAxis dataKey="date" tickFormatter={(x: string) => x.slice(0, 7)} tick={{fill:'#778697',fontSize:11}} axisLine={false} tickLine={false}/>
    <YAxis tickFormatter={(x: number) => `$${(x/1000).toFixed(0)}k`} tick={{fill:'#778697',fontSize:11}} axisLine={false} tickLine={false}/>
    <Tooltip contentStyle={{background:'#141d28',border:'1px solid #293747',borderRadius:8,color:'#e7edf4'}} formatter={(v) => money(typeof v === 'number' ? v : Number(v))}/>
    {fields.map((field, index) => <Area key={field} type="monotone" dataKey={field} name={names[index]} stroke={index ? '#6e7f90' : '#55a5ff'} fill={index ? 'none' : 'url(#eqFill)'} fillOpacity={index ? 0 : 1} strokeWidth={2} dot={false} isAnimationActive={false}/>)}
    <defs><linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4d9cf4" stopOpacity={.22}/><stop offset="100%" stopColor="#4d9cf4" stopOpacity={0}/></linearGradient></defs>
  </AreaChart></ResponsiveContainer></div>;
}

export function EquityChart({ data }: { data: Backtest }) {
  const rows = validPoints(data.equity_curve ?? [], ['total_equity']).map((x) => ({ date: x.date, equity: x.total_equity }));
  return rows.length ? <Chart data={rows} fields={['equity']} names={['Portfolio value']}/> : <div className="chart-empty">No valid equity curve observations were returned.</div>;
}

export function BenchmarkChart({ data }: { data: Backtest }) {
  const rows = validPoints(data.benchmark_equity_curve ?? [], ['strategy_equity', 'benchmark_equity']).map((x) => ({ date: x.date, strategy: x.strategy_equity, benchmark: x.benchmark_equity }));
  return rows.length ? <Chart data={rows} fields={['strategy', 'benchmark']} names={['Strategy', String(data.benchmark?.benchmark_symbol || 'Benchmark')]}/> : <div className="chart-empty">No valid benchmark observations were returned.</div>;
}
