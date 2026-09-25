import { Alert, Typography } from '@mui/material';
import { NumberInput, SelectInput, Toggle } from './ConfigurationFields';
import { choices } from './choices';
import type { HistoryMode, TagInput } from '../types/configuration';

export default function HistorySettings({ value, change }: {
  value: TagInput; change: <K extends keyof TagInput>(field: K, value: TagInput[K]) => void;
}) {
  return <>
    <Typography component="h3" variant="h6">History</Typography>
    <Toggle label="History enabled" value={value.history_enabled} onChange={(next) => change('history_enabled', next)} />
    <SelectInput label="History mode" value={value.history_mode} onChange={(next) => change('history_mode', next as HistoryMode)}>
      {choices(['every_sample', 'fixed_interval', 'on_change'])}
    </SelectInput>
    {value.history_mode === 'fixed_interval' && <NumberInput label="History interval (ms)" value={value.history_interval_ms}
      min={value.poll_interval_ms} required onChange={(next) => change('history_interval_ms', next)}
      helperText="How often a value is saved. Must be at least the poll interval; live readings continue at the poll interval." />}
    {value.history_mode === 'on_change' && (value.data_type === 'bool'
      ? <Typography>Stores each boolean state change.</Typography>
      : <NumberInput label="Change threshold" value={value.history_change_threshold} min={0} step="any" required
          onChange={(next) => change('history_change_threshold', next)} helperText="Absolute engineering-value change from the last stored value, inclusive. Zero stores any nonzero change." />)}
    <NumberInput label="Retention days" value={value.history_retention_days} min={1} max={365000}
      onChange={(next) => change('history_retention_days', next)} helperText="Blank keeps history indefinitely. Expired records are removed periodically, even when history is disabled." />
    <Alert severity="info">Every sample at one-second polling creates 86,400 rows per tag per day. Consider fixed interval or on change for frequent readings. Disabling history stops new records; existing history remains.</Alert>
  </>;
}
