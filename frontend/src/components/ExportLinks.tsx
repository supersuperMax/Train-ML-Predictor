import { buildUrl, forecastParams } from '../api';
import type { Filters } from '../types';

export default function ExportLinks({ filters }: { filters: Filters }) {
  const params = forecastParams(filters);
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2.5 border-t border-line pt-4">
      <span>Выгрузить с текущими фильтрами:</span>
      <a className="btn" href={buildUrl('/export/csv', params)} download>
        CSV
      </a>
      <a className="btn" href={buildUrl('/export/xlsx', params)} download>
        XLSX
      </a>
    </div>
  );
}
