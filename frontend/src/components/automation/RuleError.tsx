import { useId, useState } from 'react';
import { Alert, Button, Typography } from '@mui/material';
import { shellLayout } from '../../layout/tokens';

export default function RuleError({ error }: { error: string }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const long = error.length > 180 || error.includes('\n');
  return <Alert severity="warning" sx={{ '& .MuiAlert-message': { minWidth: 0, width: '100%' } }}>
    <Typography id={id} variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
      ...long && !expanded ? { display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' } : {} }}>{error}</Typography>
    {long && <Button aria-expanded={expanded} aria-controls={id} sx={{ minHeight: shellLayout.touchTarget }} onClick={() => setExpanded(value => !value)}>{expanded ? 'Collapse error' : 'Show full error'}</Button>}
  </Alert>;
}
