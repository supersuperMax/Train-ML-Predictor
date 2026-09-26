import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const API = 'http://localhost:8000/api';

type Row = { route: string; date: string; hour: number; prediction: number };

export default function App() {
  const [routes, setRoutes] = useState<string[]>([]);
  const [route, setRoute] = useState('');
  const [rows, setRows] = useState<Row[]>([]);
  const [date, setDate] = useState('2025-11-01');

  useEffect(() => { fetch(`${API}/routes`).then(r => r.json()).then((x: string[]) => { setRoutes(x); if (x[0]) setRoute(x[0]); }); }, []);
  useEffect(() => {
    if (!route) return;
    fetch(`${API}/forecast?route=${encodeURIComponent(route)}&from=${date}&to=${date}`).then(r => r.json()).then(setRows);
  }, [route, date]);

  return <main>
    <header><h1>Прогноз пассажиропотока</h1><p>Трамвайные маршруты Москвы</p></header>
    <section className="filters">
      <label>Маршрут<select value={route} onChange={e => setRoute(e.target.value)}>{routes.map(r => <option key={r}>{r}</option>)}</select></label>
      <label>Дата<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
    </section>
    <section className="card chart"><h2>Почасовой прогноз</h2><ResponsiveContainer width="100%" height={360}><LineChart data={rows}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="hour"/><YAxis/><Tooltip/><Line type="monotone" dataKey="prediction" strokeWidth={3}/></LineChart></ResponsiveContainer></section>
    <section className="card"><h2>Данные</h2><p>Точек прогноза: {rows.length}</p><a href={`${API}/export/csv?route=${route}&from=${date}&to=${date}`}>Скачать CSV</a> · <a href={`${API}/export/xlsx?route=${route}&from=${date}&to=${date}`}>Скачать XLSX</a></section>
  </main>;
}
