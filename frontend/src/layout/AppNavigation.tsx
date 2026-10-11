import { Box, Divider, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Stack, Typography } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/context';
import AlarmIndicator from '../components/AlarmIndicator';
import HealthStatus from '../components/HealthStatus';
import { isNavigationActive, navigationGroups } from './navigation';
import { shellLayout } from './tokens';

export default function AppNavigation({ onNavigate, onClose }: { onNavigate: () => void; onClose?: () => void }) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  return <Box component="nav" id="main-navigation" aria-label="Main navigation" sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
    <Stack direction="row" alignItems="center" sx={{ px: 2, minHeight: 64, flexShrink: 0 }}>
      <Typography fontWeight={700} letterSpacing={0.5} sx={{ flex: 1 }}>Modbus Monitor</Typography>
      {onClose && <IconButton aria-label="Close navigation" onClick={onClose} sx={{ width: shellLayout.touchTarget, height: shellLayout.touchTarget }}><CloseIcon /></IconButton>}
    </Stack>
    <Divider />
    <Box sx={{ overflowY: 'auto', flex: 1, px: 1.5, py: 1 }}>
      {navigationGroups.map(group => {
        const items = group.items.filter(item => !('permission' in item) || user?.permissions.includes(item.permission!));
        if (!items.length) return null;
        return <Box key={group.label} component="section" aria-label={group.label} sx={{ mb: 1 }}>
          <Typography component="h2" variant="overline" sx={{ display: 'block', px: 1.5, color: 'text.secondary', fontWeight: 700, letterSpacing: 1 }}>{group.label}</Typography>
          <List disablePadding>
            {items.map(item => {
              const selected = isNavigationActive(pathname, item.path);
              const Icon = item.icon;
              return <ListItemButton key={item.path} component={Link} to={item.path} selected={selected}
                aria-current={selected ? 'page' : undefined} onClick={onNavigate}
                sx={{ minHeight: shellLayout.touchTarget, borderRadius: 1, mb: 0.25, px: 1.5,
                  borderInlineStart: '3px solid', borderColor: selected ? 'primary.main' : 'transparent',
                  '&.Mui-selected': { color: 'primary.dark' }, '&.Mui-focusVisible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 } }}>
                <ListItemIcon sx={{ minWidth: 36, color: 'inherit' }}><Icon fontSize="small" /></ListItemIcon>
                <ListItemText primary={item.label} slotProps={{ primary: { fontSize: 14, fontWeight: selected ? 700 : 500 } }} />
              </ListItemButton>;
            })}
          </List>
        </Box>;
      })}
    </Box>
      <Divider />
      <Stack spacing={1} alignItems="flex-start" sx={{ px: 2.5, py: 1.5, flexShrink: 0 }}>
        <Box onClick={onNavigate} sx={{ '& .MuiChip-root': { minHeight: shellLayout.touchTarget, maxWidth: '100%' }, '& .MuiChip-label': { whiteSpace: 'normal' } }}><AlarmIndicator /></Box>
        <HealthStatus />
      </Stack>
  </Box>;
}
