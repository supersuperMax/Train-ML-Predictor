import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ForecastResponse, Point } from '../types';
import { num, periodLabel, SOURCE_LABEL } from '../format';

const FACT = '#f59e0b';
const FACT_DARK = '#fbbf24';
const COLOR = { model: '#2563eb', baseline: '#94a3b8', mixed: '#60a5fa', none: '#e2e8f0', fact: FACT } as const;
const COLOR_DARK = { model: '#3b82f6', baseline: '#475569', mixed: '#60a5fa', none: '#1e293b', fact: FACT_DARK } as const;

interface Props {
  data: ForecastResponse;
  dark?: boolean;
  /** Весь график из одного источника (выбран baseline) — столбцы основным цветом, серый нужен только рядом с моделью. */
  solid?: boolean;
}

export default function ForecastChart({ data, dark = false, solid = false }: Props) {
  const colors = dark ? COLOR_DARK : COLOR;
  const fact = dark ? FACT_DARK : FACT;
  const tick = { fontSize: 12, fill: dark ? '#94a3b8' : '#64748b' };
  const g = data.query.granularity;
  const multiDay = data.query.from !== data.query.to;
  // Залит файл валидаций — рядом с прогнозом показываем факт из файла.
  const hasFact = data.fact_total !== undefined;
  const rows = data.points.map((p: Point) => ({
    ...p,
    label: g === 'hour' && multiDay ? `${p.t.slice(8, 10)}.${p.t.slice(5, 7)} ${p.t.slice(11, 13)}` : periodLabel(p.t, g, true),
    full: g === 'hour' ? `${p.t.slice(0, 10)} ${p.t.slice(11)}` : periodLabel(p.t, g),
  }));

  const tooltip = (
    <Tooltip
      contentStyle={dark ? { background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0' } : undefined}
      cursor={{ fill: dark ? '#1e293b' : '#f1f5f9' }}
      formatter={(v, name) => [v === null || v === undefined ? '—' : num(Number(v)), hasFact ? String(name) : 'Посадки']}
      labelFormatter={(_, payload) => {
        const p = payload?.[0]?.payload as (Point & { full: string }) | undefined;
        if (!p) return '';
        // до начала прогноза есть только факт из файла
        return `${p.full} · ${p.value === null && p.fact != null ? SOURCE_LABEL.fact : SOURCE_LABEL[p.source]}`;
      }}
    />
  );
  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke={dark ? '#334155' : '#e2e8f0'} />
      <XAxis dataKey="label" tick={tick} interval="preserveStartEnd" minTickGap={8} />
      <YAxis tickFormatter={(v: number) => num(v)} tick={tick} width={70} />
      {hasFact && <Legend wrapperStyle={{ fontSize: 12, color: dark ? '#cbd5e1' : '#475569' }} />}
    </>
  );

  return (
    <ResponsiveContainer width="100%" height={400}>
      {g === 'hour' ? (
        <LineChart data={rows} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
          {axes}
          {tooltip}
          <Line type="monotone" dataKey="value" name="Прогноз" stroke={colors.model} strokeWidth={2.5} dot={rows.length <= 48} isAnimationActive={false} />
          {hasFact && <Line type="monotone" dataKey="fact" name="Факт" stroke={fact} strokeWidth={2.5} dot={rows.length <= 48} isAnimationActive={false} />}
        </LineChart>
      ) : (
        <BarChart data={rows} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
          {axes}
          {tooltip}
          <Bar dataKey="value" name="Прогноз" fill={colors.model} radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.t} fill={solid && r.source !== 'none' ? colors.model : colors[r.source]} />
            ))}
          </Bar>
          {hasFact && <Bar dataKey="fact" name="Факт" fill={fact} radius={[4, 4, 0, 0]} isAnimationActive={false} />}
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}
