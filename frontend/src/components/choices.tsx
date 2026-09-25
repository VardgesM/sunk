import { MenuItem } from '@mui/material';

// MUI Select needs MenuItem elements as direct children, not a wrapper component.
export function choices(values: readonly (string | number)[]) {
  return values.map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>);
}
