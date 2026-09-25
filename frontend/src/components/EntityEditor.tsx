import { useState, type ReactNode } from 'react';
import { Alert, Box, Button, DialogActions, DialogContent, Stack } from '@mui/material';

export type Change<T> = <K extends keyof T>(key: K, value: T[K]) => void;

export default function EntityEditor<T>({ initial, onSave, onCancel, children }: {
  initial: T; onSave: (value: T) => Promise<void>; onCancel: () => void;
  children: (value: T, change: Change<T>) => ReactNode;
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const change: Change<T> = (key, next) => setValue((current) => ({ ...current, [key]: next }));
  return (
    <Box component="form" onSubmit={(event) => {
      event.preventDefault();
      setBusy(true); setError('');
      void onSave(value).catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : 'Save failed');
      }).finally(() => setBusy(false));
    }}>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2, whiteSpace: 'pre-line' }}>{error}</Alert>}
        <Box component="fieldset" disabled={busy} sx={{ border: 0, m: 0, p: 0, minWidth: 0 }}>
          <Stack spacing={2} sx={{ pt: 1 }}>{children(value, change)}</Stack>
        </Box>
      </DialogContent>
      <DialogActions><Button onClick={onCancel} disabled={busy}>Cancel</Button><Button type="submit" variant="contained" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button></DialogActions>
    </Box>
  );
}
