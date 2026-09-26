import { useEffect, useRef, useState } from 'react';
import { LngLatBounds, Map as MapLibre, NavigationControl, Popup, setWorkerUrl, type GeoJSONSource, type LngLatBoundsLike, type MapLayerMouseEvent, type StyleSpecification } from 'maplibre-gl';
// MapLibre 6 ищет worker рядом со своим модулем, а после сборки его там нет — без worker'а GeoJSON-слои
// (маршруты и остановки) не рисуются. Отдаём Vite собрать worker и передаём его адрес явно.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { FeatureCollection, Point } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { MapState, StopsResponse } from '../types';
import { num, pad2 } from '../format';

const ROUTE_COLORS = ['#1468e8', '#e5383b', '#2a9d8f', '#8d5cf6', '#f59e0b', '#0ea5e9', '#db2777', '#65a30d'];
const MOSCOW: [number, number] = [37.62, 55.75];
// Вся Москва вместе с Новой Москвой (с небольшим запасом): за эти пределы карту не увести.
const MOSCOW_BOUNDS: LngLatBoundsLike = [[36.75, 55.10], [38.02, 56.05]];

setWorkerUrl(workerUrl);

const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© участники OpenStreetMap',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

interface Props {
  stops: StopsResponse | null;
  state: MapState | null;
  selectedStop: number | null;
  dark: boolean;
  onSelectStop: (stopId: number, routes: number[]) => void;
}

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

const empty: FeatureCollection = { type: 'FeatureCollection', features: [] };

export default function MapView({ stops, state, selectedStop, dark, onSelectStop }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const [loaded, setLoaded] = useState(false);
  const onSelectRef = useRef(onSelectStop);
  onSelectRef.current = onSelectStop;

  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibre({ container: container.current, style: STYLE, center: MOSCOW, zoom: 10.2, maxBounds: MOSCOW_BOUNDS, minZoom: 8.5 });
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    mapRef.current = map;
    const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 10 });

    map.on('load', () => {
      map.addSource('lines', { type: 'geojson', data: empty });
      map.addSource('stops', { type: 'geojson', data: empty });
      map.addLayer({
        id: 'lines',
        type: 'line',
        source: 'lines',
        paint: { 'line-color': ['get', 'color'], 'line-width': 3, 'line-opacity': 0.55 },
      });
      map.addLayer({
        id: 'stops',
        type: 'circle',
        source: 'stops',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'norm'], 0, 3, 1, 15],
          'circle-color': ['interpolate', ['linear'], ['get', 'norm'], 0, '#2dc26b', 0.5, '#f5b700', 1, '#e5383b'],
          'circle-opacity': 0.85,
          'circle-stroke-color': ['case', ['get', 'selected'], ['get', 'selectedStroke'], ['get', 'stroke']],
          'circle-stroke-width': ['case', ['get', 'selected'], 3, 1],
        },
      });
      map.on('mouseenter', 'stops', () => (map.getCanvas().style.cursor = 'pointer'));
      map.on('mouseleave', 'stops', () => {
        map.getCanvas().style.cursor = '';
        popup.remove();
      });
      map.on('mousemove', 'stops', (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as { name: string; value: number; routes: string };
        popup
          .setLngLat((f.geometry as Point).coordinates as [number, number])
          .setHTML(
            `<div class="font-semibold">${escapeHtml(p.name)}</div>` +
              `<div class="text-slate-500 dark:text-slate-400">Маршруты: ${JSON.parse(p.routes).join(', ')}</div>` +
              `<div>Прогноз: <b>${num(p.value)}</b> посадок</div>`,
          )
          .addTo(map);
      });
      map.on('click', 'stops', (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as { stop_id: number; routes: string };
        onSelectRef.current(p.stop_id, JSON.parse(p.routes));
      });
      setLoaded(true);
    });
    return () => map.remove();
  }, []);

  // Линии маршрутов и подгонка масштаба под выбранные остановки.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || !stops) return;
    const routes = [...new Set(stops.lines.map((l) => l.route))].sort((a, b) => a - b);
    (map.getSource('lines') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: stops.lines.map((l) => ({
        type: 'Feature',
        properties: { route: l.route, color: ROUTE_COLORS[routes.indexOf(l.route) % ROUTE_COLORS.length] },
        geometry: { type: 'LineString', coordinates: l.coordinates },
      })),
    });
    if (stops.stops.length) {
      const b = new LngLatBounds();
      stops.stops.forEach((s) => b.extend([s.lon, s.lat]));
      map.fitBounds(b, { padding: 40, maxZoom: 14, duration: 600 });
    }
  }, [stops, loaded]);

  // Нагрузка на остановки: размер и цвет кружка.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || !stops) return;
    const values = new Map((state?.stops ?? []).map((s) => [s.stop_id, s.value]));
    const max = state?.max || 1;
    (map.getSource('stops') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: stops.stops.map((s) => {
        const value = values.get(s.stop_id) ?? 0;
        return {
          type: 'Feature',
          properties: {
            stop_id: s.stop_id,
            name: s.name,
            routes: JSON.stringify(s.routes),
            value,
            norm: Math.min(1, value / max),
            selected: s.stop_id === selectedStop,
            stroke: dark ? '#0f172a' : '#ffffff',
            selectedStroke: dark ? '#ffffff' : '#0f172a',
          },
          geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        };
      }),
    });
  }, [stops, state, selectedStop, dark, loaded]);

  // Тёмная подложка без внешних сервисов: инвертируем яркость тайлов OSM и возвращаем оттенки поворотом на 180°.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    const paint = dark
      ? { 'raster-brightness-min': 0.9, 'raster-brightness-max': 0.08, 'raster-hue-rotate': 180, 'raster-saturation': -0.4, 'raster-contrast': 0.1 }
      : { 'raster-brightness-min': 0, 'raster-brightness-max': 1, 'raster-hue-rotate': 0, 'raster-saturation': 0, 'raster-contrast': 0 };
    for (const [k, v] of Object.entries(paint)) map.setPaintProperty('osm', k as Parameters<MapLibre['setPaintProperty']>[1], v);
  }, [dark, loaded]);

  const routes = stops ? [...new Set(stops.lines.map((l) => l.route))].sort((a, b) => a - b) : [];
  return (
    <div className="relative">
      <div ref={container} className="h-[600px] overflow-hidden rounded-lg" />
      <div className="absolute bottom-2.5 left-2.5 flex max-w-[calc(100%-20px)] flex-col gap-1.5 rounded-md bg-white/90 px-2.5 py-2 text-xs text-slate-700 shadow-sm ring-1 ring-slate-900/5 dark:bg-slate-900/90 dark:text-slate-300 dark:ring-white/10">
        <div className="flex items-center gap-1.5">
          <span>0</span>
          <i className="h-2 w-24 rounded-full bg-linear-to-r from-green-500 via-yellow-400 to-red-500" />
          <span>{num(state?.max ?? 0)}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {routes.map((r, i) => (
            <span key={r}>
              <i className="mr-1 inline-block h-1 w-3 rounded-sm align-middle" style={{ background: ROUTE_COLORS[i % ROUTE_COLORS.length] }} />№ {r}
            </span>
          ))}
        </div>
        {state && <small>посадок на остановке {state.hour === null ? 'за день' : `в ${pad2(state.hour)}:00`}</small>}
      </div>
    </div>
  );
}
