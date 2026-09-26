import { useEffect, useState } from 'react';
import { useApi } from '../api';
import type { MapState, StopsResponse } from '../types';
import { dateRu, pad2, SOURCE_LABEL } from '../format';
import MapView from './MapView';
import { ErrorBox } from './Status';

interface Props {
  date: string;
  route: number | null;
  routeHasStops: boolean;
  selectedStop: number | null;
  available?: { from: string; to: string };
  onSelectStop: (stopId: number, routes: number[]) => void;
  onDateChange: (date: string) => void;
}

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
};

export default function MapPanel({ date, route, routeHasStops, selectedStop, available, onSelectStop, onDateChange }: Props) {
  const [hour, setHour] = useState<number>(8);
  const [playing, setPlaying] = useState(false);
  const [live, setLive] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const stops = useApi<StopsResponse>('/stops', { route: routeHasStops ? route : null });
  const state = useApi<MapState>('/map', { date, hour, route: routeHasStops ? route : null });

  // Анимация по часам суток.
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => setHour((h) => (h + 1) % 24), 900);
    return () => window.clearInterval(id);
  }, [playing]);

  // Режим «сейчас»: текущий час, обновляется каждую минуту.
  useEffect(() => {
    if (!live) return;
    const tick = () => setHour(new Date().getHours());
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => window.clearInterval(id);
  }, [live]);

  const goLive = () => {
    setPlaying(false);
    const t = today();
    if (available && t >= available.from && t <= available.to) {
      onDateChange(t);
      setNote(null);
    } else {
      setNote(`Сегодняшней даты нет в прогнозе (${available ? `${dateRu(available.from)} — ${dateRu(available.to)}` : '—'}): показан текущий час выбранного дня.`);
    }
    setLive(true);
  };

  return (
    <section className="card">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-[17px] font-bold">Загрузка остановок на карте</h2>
        <span className="text-muted">
          {dateRu(date)}, {pad2(hour)}:00
          {state.data && state.data.source !== 'model' ? ` · ${SOURCE_LABEL[state.data.source]}` : ''}
        </span>
      </div>
      {route !== null && !routeHasStops && (
        <div className="alert alert-info">Для маршрута № {route} в справочнике нет координат остановок — на карте показаны все маршруты с остановками.</div>
      )}
      {stops.error && <ErrorBox error={stops.error} />}
      {state.error && <ErrorBox error={state.error} />}
      <MapView stops={stops.data} state={state.data} selectedStop={selectedStop} onSelectStop={onSelectStop} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          className="btn"
          onClick={() => {
            setLive(false);
            setPlaying((p) => !p);
          }}
          aria-label={playing ? 'Пауза' : 'Воспроизвести по часам'}
        >
          {playing ? '❚❚ Пауза' : '▶ Динамика за сутки'}
        </button>
        <input
          type="range"
          className="min-w-[140px] flex-1 accent-accent"
          min={0}
          max={23}
          value={hour}
          onChange={(e) => {
            setLive(false);
            setPlaying(false);
            setHour(Number(e.target.value));
          }}
          aria-label="Час суток"
        />
        <span className="min-w-12 font-bold tabular-nums">{pad2(hour)}:00</span>
        <button className={live ? 'btn btn-active' : 'btn'} onClick={() => (live ? setLive(false) : goLive())}>
          {live ? '● Сейчас' : 'Сейчас'}
        </button>
      </div>
      {note && live && <p className="mt-3 text-[13px] text-muted">{note}</p>}
      <p className="mt-3 text-[13px] text-muted">
        Остановочный прогноз — доля прогноза маршрута: посадки убывают к конечной, направления делят поток поровну. Координаты есть в справочнике только для части маршрутов. Нажмите на остановку, чтобы построить её график.
      </p>
    </section>
  );
}
