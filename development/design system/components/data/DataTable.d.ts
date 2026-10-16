import * as React from 'react';

export interface DataColumn {
  key: string;
  header: React.ReactNode;
  /** CSS width, e.g. "120px" or "20%". */
  width?: string;
  align?: 'left' | 'right' | 'center';
  /** Render this column in monospace (IDs, hashes, timestamps). */
  mono?: boolean;
  /** Custom cell renderer: (value, row) => node. */
  render?: (value: any, row: any) => React.ReactNode;
}

export interface DataTableProps {
  columns: DataColumn[];
  rows: any[];
  /** Field on each row used as its key & selection id. Default "id". */
  rowKey?: string;
  selectedId?: string | number;
  onRowClick?: (row: any) => void;
  style?: React.CSSProperties;
}

/**
 * Dense evidence data table.
 * @startingPoint section="Data" subtitle="Dense evidence table with mono columns" viewport="700x260"
 */
export function DataTable(props: DataTableProps): JSX.Element;
