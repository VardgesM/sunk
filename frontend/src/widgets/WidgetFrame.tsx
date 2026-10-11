import { Box, Button, Stack, Typography } from '@mui/material';
import type { Tag } from '../types/configuration';
import type { Widget } from '../types/dashboards';
import { shellLayout } from '../layout/tokens';
import DashboardWidget from './DashboardWidget';

export default function WidgetFrame({ widget, tags, editing, locked, onEdit, onRemove, flowing }: {
  widget: Widget; tags: Map<number, Tag>; editing: boolean; locked: boolean;
  onEdit: () => void; onRemove: () => void; flowing: boolean;
}) {
  return <>
    <Stack className="widget-handle" spacing={0.5} sx={{ px: 2, pt: 1.5, pb: 1, minWidth: 0,
      bgcolor: editing ? 'action.hover' : undefined, cursor: editing ? 'move' : 'default', touchAction: editing ? 'none' : 'auto' }}>
      <Typography component="h2" variant="subtitle1" fontWeight={700} sx={{ lineHeight: 1.35, overflowWrap: 'anywhere' }}>{widget.title}</Typography>
      {editing && <Stack direction="row" flexWrap="wrap" gap={1}>
        <Button disabled={locked} onClick={onEdit} aria-label={`Edit ${widget.title}`} sx={{ minHeight: shellLayout.touchTarget }}>Edit</Button>
        <Button disabled={locked} color="error" onClick={onRemove} aria-label={`Remove ${widget.title}`} sx={{ minHeight: shellLayout.touchTarget }}>Remove</Button>
      </Stack>}
    </Stack>
    <Box sx={{ px: 2, pb: 2, pt: 0.5, minWidth: 0, minHeight: 0, flex: 1,
      overflow: flowing ? 'visible' : 'auto', overflowWrap: 'anywhere',
      '& .MuiAlert-message': { minWidth: 0 }, '& .MuiInputBase-root': { minWidth: 0 },
      '& .MuiButton-root': { minHeight: shellLayout.touchTarget } }}>
      <DashboardWidget widget={widget} tags={tags} editing={editing} />
    </Box>
  </>;
}
