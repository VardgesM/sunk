import type { ReactNode } from 'react';
import { Box, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, useMediaQuery, useTheme } from '@mui/material';
import { shellLayout } from '../../layout/tokens';

export interface Column<T> { label: string; render: (row: T) => ReactNode; minWidth?: number }

export default function ResponsiveDataView<T extends { id: number }>({ label, rows, columns, card }: {
  label: string; rows: T[]; columns: Column<T>[]; card: (row: T) => ReactNode;
}) {
  const table = useMediaQuery(useTheme().breakpoints.up(shellLayout.dataViewBreakpoint), { defaultMatches: true });
  // Render one presentation only: runtime hooks and live subscriptions are not duplicated.
  return table ? <TableContainer component={Paper} variant="outlined" tabIndex={0} aria-label={`${label} table scroll area`}>
    <Table size="small" aria-label={label}>
      <TableHead><TableRow>{columns.map(column => <TableCell key={column.label} sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{column.label}</TableCell>)}</TableRow></TableHead>
      <TableBody>{rows.map(row => <TableRow key={row.id}>
        {columns.map((column, index) => <TableCell key={column.label} sx={{ verticalAlign: 'top', overflowWrap: 'anywhere', minWidth: column.minWidth ?? (index === 0 ? 180 : 120), maxWidth: 320, py: 1.5 }}>{column.render(row)}</TableCell>)}
      </TableRow>)}</TableBody>
    </Table>
  </TableContainer> : <Stack component="ul" aria-label={label} spacing={2} sx={{ listStyle: 'none', p: 0, m: 0, minWidth: 0 }}>
    {rows.map(row => <Box component="li" key={row.id} sx={{ minWidth: 0 }}>{card(row)}</Box>)}
  </Stack>;
}
