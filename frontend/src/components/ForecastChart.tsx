import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ForecastResponse, Point } from '../types';
import { num, periodLabel, SOURCE_LABEL } from '../format';

const COLOR = { model: '#2563eb', baseline: '#94a3b8', mixed: '#60a5fa', none: '#e2e8f0' } as const;

interface Props {
  data: ForecastResponse;
}

export default function ForecastChart({ data }: Props) {
  const g = data.query.granularity;
  const multiDay = data.query.from !== data.query.to;
  const rows = data.points.map((p: Point) => ({
    ...p,
    label: g === 'hour' && multiDay ? `${p.t.slice(8, 10)}.${p.t.slice(5, 7)} ${p.t.slice(11, 13)}` : periodLabel(p.t, g, true),
    full: g === 'hour' ? `${p.t.slice(0, 10)} ${p.t.slice(11)}` : periodLabel(p.t, g),
  }));

  const tooltip = (
    <Tooltip
      formatter={(v) => [num(Number(v)), 'Посадки']}
      labelFormatter={(_, payload) => {
        const p = payload?.[0]?.payload as (Point & { full: string }) | undefined;
        return p ? `${p.full} · ${SOURCE_LABEL[p.source]}` : '';
      }}
    />
  );
  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
      <XAxis dataKey="label" tick={{ fontSize: 12 }} interval="preserveStartEnd" minTickGap={8} />
      <YAxis tickFormatter={(v: number) => num(v)} tick={{ fontSize: 12 }} width={70} />
    </>
  );

  return (
    <ResponsiveContainer width="100%" height={340}>
      {g === 'hour' ? (
        <LineChart data={rows} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
          {axes}
          {tooltip}
          <Line type="monotone" dataKey="value" stroke={COLOR.model} strokeWidth={2.5} dot={rows.length <= 48} isAnimationActive={false} />
        </LineChart>
      ) : (
        <BarChart data={rows} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
          {axes}
          {tooltip}
          <Bar dataKey="value" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.t} fill={COLOR[r.source]} />
            ))}
          </Bar>
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}
