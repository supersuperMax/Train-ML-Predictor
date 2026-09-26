import { buildUrl, forecastParams } from '../api';
import type { Filters } from '../types';
import { btn } from '../ui';

export default function ExportLinks({ filters, source }: { filters: Filters; source: string }) {
  const params = forecastParams(filters, source);
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-300">
      <span>Выгрузить с текущими фильтрами:</span>
      <a className={btn} href={buildUrl('/export/csv', params)} download>
        CSV
      </a>
      <a className={btn} href={buildUrl('/export/xlsx', params)} download>
        XLSX
      </a>
    </div>
  );
}
