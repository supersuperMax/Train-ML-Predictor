import { buildUrl, forecastParams } from '../api';
import type { Filters } from '../types';

export default function ExportLinks({ filters }: { filters: Filters }) {
  const params = forecastParams(filters);
  return (
    <div className="export">
      <span>Выгрузить с текущими фильтрами:</span>
      <a className="button" href={buildUrl('/export/csv', params)} download>
        CSV
      </a>
      <a className="button" href={buildUrl('/export/xlsx', params)} download>
        XLSX
      </a>
    </div>
  );
}
