// Декоративная полоска над шапкой: на фоне города из «хрущёвок» по рельсам под контактным проводом едет трамвай.
// В тёмной теме город и трамвай темнее, в части окон горит свет. При «уменьшить движение» трамвай стоит.

const CITY_W = 2400;
const CITY_H = 68; // выше провода: башни заходят за контактную сеть

/** Детерминированный ГПСЧ (mulberry32): город одинаковый при каждой загрузке и не прыгает между рендерами. */
function rng(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Пятиэтажки как пути SVG: коробки домов, обычные окна и «горящие» — по одному path на слой вместо тысяч rect. */
const CITY = (() => {
  const rand = rng(1957); // год первой серии хрущёвок
  let houses = '';
  let windows = '';
  let lit = '';
  for (let x = rand() * 10; x < CITY_W; ) {
    // примерно каждый третий дом — узкая башня в 7–8 этажей, выше проводов; остальные — хрущёвки в 4–5 этажей
    const tower = rand() < 0.35;
    const w = tower ? 40 + Math.round(rand() * 20) : 60 + Math.round(rand() * 50);
    const floors = tower ? (rand() < 0.5 ? 7 : 8) : rand() < 0.3 ? 4 : 5;
    const h = floors * 8 + 4;
    const top = CITY_H - h;
    houses += `M${x} ${CITY_H}V${top}h${w}V${CITY_H}Z`;
    const cols = Math.floor((w - 6) / 9);
    const pad = (w - cols * 9 + 4) / 2;
    for (let f = 0; f < floors; f++) {
      for (let c = 0; c < cols; c++) {
        const win = `M${(x + pad + c * 9).toFixed(1)} ${top + 4 + f * 8}h5v4h-5Z`;
        if (rand() < 0.25) lit += win;
        else windows += win;
      }
    }
    x += w + 6 + Math.round(rand() * 14);
  }
  return { houses, windows, lit };
})();

function City() {
  return (
    <svg viewBox={`0 0 ${CITY_W} ${CITY_H}`} preserveAspectRatio="xMinYMax slice" className="absolute inset-x-0 bottom-3 h-[68px] w-full" aria-hidden="true">
      <path d={CITY.houses} className="fill-slate-300 dark:fill-slate-800" />
      <path d={CITY.windows} className="fill-slate-100 dark:fill-slate-700" />
      <path d={CITY.lit} className="fill-slate-100 dark:fill-amber-300" />
    </svg>
  );
}

const WINDOWS_1 = [0, 1, 2, 3, 4];
const WINDOWS_2 = [0, 1, 2, 3];

function Tram() {
  return (
    <svg viewBox="0 0 172 46" className="h-[46px] w-[172px]" aria-hidden="true">
      {/* пантограф до провода */}
      <path d="M78 13 86 5 94 13M80 5h12M86 5V0" fill="none" strokeWidth="1.5" strokeLinecap="round" className="stroke-slate-600 dark:stroke-slate-500" />
      {/* две секции и гармошка между ними */}
      <path d="M7 14h75v24H7a5 5 0 0 1-5-5V19a5 5 0 0 1 5-5Z" className="fill-blue-600 dark:fill-blue-800" />
      <path d="M88 14h66c8 0 13 6 15 14v6a4 4 0 0 1-4 4H88Z" className="fill-blue-600 dark:fill-blue-800" />
      <rect x="82" y="16" width="6" height="20" rx="1" className="fill-slate-700 dark:fill-slate-900" />
      {/* окна: днём стекло, ночью тёплый свет салона */}
      {WINDOWS_1.map((i) => (
        <rect key={i} x={8 + i * 14.5} y="18" width="10.5" height="9" rx="1.5" className="fill-sky-100 dark:fill-amber-200/80" />
      ))}
      {WINDOWS_2.map((i) => (
        <rect key={i} x={92 + i * 14.5} y="18" width="10.5" height="9" rx="1.5" className="fill-sky-100 dark:fill-amber-200/80" />
      ))}
      <path d="M152 18h4c4 0 8 4 9.5 9H152Z" className="fill-sky-100 dark:fill-slate-600" />
      {/* полоса по борту, фара, колёса */}
      <rect x="2" y="31" width="167" height="2" className="fill-white/80 dark:fill-slate-400/60" />
      <circle cx="166" cy="34.5" r="1.4" className="fill-amber-300" />
      {[16, 32, 66, 104, 140, 156].map((x) => (
        <circle key={x} cx={x} cy="40" r="3.6" className="fill-slate-800 dark:fill-slate-950" />
      ))}
    </svg>
  );
}

export default function TramStrip() {
  return (
    <div
      className="pointer-events-none relative h-20 overflow-hidden border-b border-slate-200 bg-linear-to-b from-sky-50 to-slate-50 dark:border-slate-800 dark:from-slate-950 dark:to-slate-900"
      aria-hidden="true"
    >
      <City />
      {/* контактный провод — на высоте пантографа */}
      <div className="absolute inset-x-0 top-6 h-px bg-slate-400/70 dark:bg-slate-600" />
      {/* шпалы и рельс */}
      <div className="absolute inset-x-0 bottom-1 h-1.5 bg-[repeating-linear-gradient(90deg,#94a3b8_0_3px,transparent_3px_14px)] dark:bg-[repeating-linear-gradient(90deg,#475569_0_3px,transparent_3px_14px)]" />
      <div className="absolute inset-x-0 bottom-2.5 h-0.5 bg-slate-500 dark:bg-slate-600" />
      <div className="absolute bottom-2.5 left-0 animate-[tram_24s_linear_infinite] motion-reduce:animate-none">
        <Tram />
      </div>
    </div>
  );
}
