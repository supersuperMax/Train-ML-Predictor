import { useState } from 'react';

function save(value: 'dark' | 'light') {
  try {
    localStorage.setItem('theme', value);
  } catch {
    // хранилище недоступно (приватный режим) — тема действует до перезагрузки
  }
}

/** Тема по классу dark на <html>; начальное значение уже выставил скрипт в index.html. */
export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle('dark', next);
    save(next ? 'dark' : 'light');
    setDark(next);
  };
  return { dark, toggle };
}
