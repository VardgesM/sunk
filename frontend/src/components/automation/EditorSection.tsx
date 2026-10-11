import type { ReactNode } from 'react';
import { Box, Stack, Typography } from '@mui/material';

export default function EditorSection({ title, children }: { title: string; children: ReactNode }) {
  return <Box component="fieldset" sx={{ m: 0, p: { xs: 1.5, sm: 2 }, minWidth: 0, border: 1, borderColor: 'divider', borderRadius: 1 }}>
    <Typography component="legend" variant="subtitle1" fontWeight={700} sx={{ px: 0.5 }}>{title}</Typography>
    <Stack spacing={2}>{children}</Stack>
  </Box>;
}
