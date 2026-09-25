import { Checkbox, FormControlLabel, TextField } from '@mui/material';
import type { ReactNode } from 'react';

export function TextInput({ label, value, onChange, required = false, helperText, multiline = false }: {
  label: string; value: string | null; onChange: (value: string) => void;
  required?: boolean; helperText?: string; multiline?: boolean;
}) {
  return <TextField fullWidth label={label} value={value ?? ''} onChange={(event) => onChange(event.target.value)} required={required} helperText={helperText} multiline={multiline} minRows={multiline ? 2 : undefined} />;
}

export function NumberInput({ label, value, onChange, required = false, min, max, step = 1, helperText }: {
  label: string; value: number | null; onChange: (value: number | null) => void;
  required?: boolean; min?: number; max?: number; step?: number | 'any'; helperText?: string;
}) {
  return <TextField fullWidth label={label} type="number" value={value ?? ''} required={required}
    onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))}
    slotProps={{ htmlInput: { min, max, step } }} helperText={helperText} />;
}

export function SelectInput({ label, value, onChange, children, required = false, disabled = false }: {
  label: string; value: string | number; onChange: (value: string) => void; children: ReactNode; required?: boolean; disabled?: boolean;
}) {
  return <TextField select fullWidth label={label} value={value} required={required} disabled={disabled} onChange={(event) => onChange(event.target.value)}>{children}</TextField>;
}

export function Toggle({ label, value, onChange, disabled = false }: {
  label: string; value: boolean; onChange: (value: boolean) => void; disabled?: boolean;
}) {
  return <FormControlLabel label={label} control={<Checkbox checked={value} disabled={disabled} onChange={(_, checked) => onChange(checked)} />} />;
}
