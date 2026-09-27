import Can from './auth/Can';
import { usePermission } from './auth/context';
import AccountMenu from './auth/AccountMenu';
import { lazy, Suspense, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AppBar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemText, Toolbar, Typography } from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import AlarmIndicator from './components/AlarmIndicator';
import HealthStatus from './components/HealthStatus';
import { SourceMode } from './components/RuntimeStatus';


const SystemPage = lazy(() => import('./pages/SystemPage'));
const UsersPage = lazy(() => import('./pages/UsersPage'));
const AuditPage = lazy(() => import('./pages/AuditPage'));
const DashboardsPage = lazy(() => import('./pages/DashboardsPage'));
const AlarmsPage = lazy(() => import('./pages/AlarmsPage'));
const AutomationPage = lazy(() => import('./pages/AutomationPage'));
const CommandsPage = lazy(() => import('./pages/CommandsPage'));
const LocationsPage = lazy(() => import('./pages/LocationsPage'));
const ConnectionsPage = lazy(() => import('./pages/ConnectionsPage'));
const DevicesPage = lazy(() => import('./pages/DevicesPage'));
const TagsPage = lazy(() => import('./pages/TagsPage'));
const TagDetailsPage = lazy(() => import('./pages/TagDetailsPage'));

const drawerWidth = 240;
// Shell navigation only. Dashboard definitions and widgets will come from PostgreSQL.
const pages = ['Dashboard', 'Locations', 'Connections', 'Devices', 'Tags', 'Commands', 'Automation', 'Alarms', 'Users', 'Audit', 'Settings'];

export default function App() {
  const admin = usePermission('users');
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigation = (
    <>
      <Toolbar><Typography fontWeight={700}>MODBUS MONITOR</Typography></Toolbar>
      <Divider />
      <List sx={{ px: 1 }}>
        {pages.filter(page => admin || !['Users','Audit'].includes(page)).map((page) => (
          <ListItemButton key={page} component={Link} to={`/${page.toLowerCase()}`}
            selected={location.pathname === `/${page.toLowerCase()}`}
            aria-current={location.pathname === `/${page.toLowerCase()}` ? 'page' : undefined}
            onClick={() => setOpen(false)} sx={{ borderRadius: 1, mb: 0.5 }}>
            <ListItemText primary={page} />
          </ListItemButton>
        ))}
      </List>
    </>
  );
  return (
    <Box sx={{ display: 'flex', minHeight: '100dvh' }}>
      <AppBar position="fixed" elevation={0} sx={{ bgcolor: '#132b40', width: { md: `calc(100% - ${drawerWidth}px)` }, ml: { md: `${drawerWidth}px` } }}>
        <Toolbar sx={{ gap: 1, flexWrap: 'wrap' }}>
          <IconButton color="inherit" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)} edge="start" sx={{ display: { md: 'none' } }}><MenuIcon /></IconButton>
          <Typography sx={{ flexGrow: 1, fontSize: { xs: 14, sm: 18 } }}>Monitoring workspace</Typography>
          <AlarmIndicator />
          <HealthStatus />
          <AccountMenu />
        </Toolbar>
      </AppBar>
      <Box component="nav" aria-label="Main navigation" sx={{ width: { md: drawerWidth }, flexShrink: 0 }}>
        <Drawer variant="temporary" open={open} onClose={() => setOpen(false)}
          sx={{ display: { xs: 'block', md: 'none' }, '& .MuiDrawer-paper': { width: drawerWidth } }}>{navigation}</Drawer>
        <Drawer variant="permanent" open sx={{ display: { xs: 'none', md: 'block' }, '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box' } }}>{navigation}</Drawer>
      </Box>
      <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, sm: 3, md: 5 } }}>
        <Toolbar />
        <SourceMode />
        <Suspense fallback={<Typography role="status">Loading pageâ€¦</Typography>}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/users" element={<Can permission="users"><UsersPage /></Can>} />
          <Route path="/audit" element={<Can permission="audit"><AuditPage /></Can>} />
          <Route path="/dashboard" element={<DashboardsPage />} />
          <Route path="/locations" element={<LocationsPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/alarms" element={<AlarmsPage />} />
          <Route path="/automation" element={<AutomationPage />} />
          <Route path="/commands" element={<CommandsPage />} />
          <Route path="/tags" element={<TagsPage />} />
          <Route path="/tags/:id" element={<TagDetailsPage key={location.pathname} />} />
          {['Settings'].map((page) => <Route key={page} path={`/${page.toLowerCase()}`} element={<SystemPage />} />)}
          <Route path="*" element={<Typography component="h1">Page not found</Typography>} />
        </Routes>
        </Suspense>
      </Box>
    </Box>
  );
}
