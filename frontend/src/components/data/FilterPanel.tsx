import { useId, useState, type ReactNode } from 'react';
import { Box, Button, Chip, Collapse, Stack, Typography, useMediaQuery, useTheme } from '@mui/material';
import FilterList from '@mui/icons-material/FilterList';
import { shellLayout } from '../../layout/tokens';

export default function FilterPanel({ active, onReset, children }: { active: string[]; onReset: () => void; children: ReactNode }) {
  const table = useMediaQuery(useTheme().breakpoints.up(shellLayout.dataViewBreakpoint), { defaultMatches: true });
  const [open, setOpen] = useState(false);
  const id = useId();
  return <Box component="section" aria-label="Filters" sx={{ mb: 2, minWidth: 0 }}>
    <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1} sx={{ mb: 1 }}>
      {table ? <Typography fontWeight={600}>Filters</Typography> : <Button startIcon={<FilterList />} aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)} sx={{ minHeight: shellLayout.touchTarget }}>Filters{active.length ? ` (${active.length})` : ''}</Button>}
      <Button onClick={onReset} sx={{ minHeight: shellLayout.touchTarget }}>Reset filters</Button>
    </Stack>
    {!!active.length && <Stack direction="row" useFlexGap flexWrap="wrap" gap={1} aria-label="Active filters" sx={{ mb: 2 }}>
      {active.map(label => <Chip key={label} size="small" label={label} sx={{ maxWidth: '100%', height: 'auto', '& .MuiChip-label': { whiteSpace: 'normal', overflowWrap: 'anywhere', py: 0.5 } }} />)}
    </Stack>}
    <Collapse in={table || open}><Box id={id} sx={{ pt: 1 }}>{children}</Box></Collapse>
  </Box>;
}
