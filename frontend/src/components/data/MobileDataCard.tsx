import { useId, type ReactNode } from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Box, Card, Stack, Typography } from '@mui/material';
import ExpandMore from '@mui/icons-material/ExpandMore';
import { shellLayout } from '../../layout/tokens';

export function DetailFields({ fields }: { fields: [string, ReactNode][] }) {
  return <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 0.25,
    '& dt': { color: 'text.secondary', fontSize: '0.75rem' }, '& dd': { m: 0, mb: 1, overflowWrap: 'anywhere' } }}>
    {fields.map(([label, value]) => <Box key={label} sx={{ minWidth: 0 }}><dt>{label}</dt><dd>{value}</dd></Box>)}
  </Box>;
}

export function DataDetails({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return <Accordion disableGutters elevation={0} sx={{ bgcolor: 'transparent', '&:before': { display: 'none' }, borderTop: 1, borderColor: 'divider' }}>
    <AccordionSummary id={`${id}-summary`} aria-controls={`${id}-content`} expandIcon={<ExpandMore />} sx={{ px: 0, minHeight: shellLayout.touchTarget }}>
      <Typography variant="body2" fontWeight={600}>{label}</Typography>
    </AccordionSummary>
    <AccordionDetails sx={{ px: 0, pb: 1 }}>{children}</AccordionDetails>
  </Accordion>;
}

export default function MobileDataCard({ name, primary, status, children, details, actions }: {
  name: string; primary?: ReactNode; status?: ReactNode; children: ReactNode; details?: ReactNode; actions?: ReactNode;
}) {
  const id = useId();
  return <Card component="article" aria-labelledby={id} variant="outlined" sx={{ p: 2, minWidth: 0, overflowWrap: 'anywhere',
    '& .MuiButton-root': { minHeight: shellLayout.touchTarget }, '& .MuiAlert-message': { minWidth: 0, overflowWrap: 'anywhere' } }}>
    <Stack spacing={1.5}>
      <Typography id={id} component="h2" variant="subtitle1" fontWeight={700} sx={{ lineHeight: 1.4 }}>{name}</Typography>
      {(primary || status) && <Stack spacing={1} alignItems="flex-start">{primary}{status}</Stack>}
      {children}
      {details && <DataDetails label="Details">{details}</DataDetails>}
      {actions && <Stack direction="row" useFlexGap flexWrap="wrap" gap={1}>{actions}</Stack>}
    </Stack>
  </Card>;
}
