import { useId, useState } from 'react';
import { Button, Menu, MenuItem } from '@mui/material';
import MoreHoriz from '@mui/icons-material/MoreHoriz';
import { shellLayout } from '../../layout/tokens';

export interface RowAction { label: string; run: () => void; destructive?: boolean; disabled?: boolean }

export default function RowActions({ name, actions }: { name: string; actions: RowAction[] }) {
  const id = useId();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  if (!actions.length) return null;
  return <>
    <Button aria-label={`Actions for ${name}`} aria-haspopup="menu" aria-expanded={!!anchor} aria-controls={anchor ? id : undefined}
      endIcon={<MoreHoriz />} onClick={event => setAnchor(event.currentTarget)} sx={{ minHeight: shellLayout.touchTarget }}>Actions</Button>
    <Menu id={id} anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)} slotProps={{ list: { 'aria-label': `Actions for ${name}` } }}>
      {actions.map(action => <MenuItem key={action.label} disabled={action.disabled} sx={{ minHeight: { xs: shellLayout.touchTarget, sm: shellLayout.touchTarget }, color: action.destructive ? 'error.main' : undefined }}
        onClick={() => { setAnchor(null); action.run(); }}>{action.label}</MenuItem>)}
    </Menu>
  </>;
}
