import { lazy, Suspense, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AppBar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemText, Toolbar, Typography } from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import HealthStatus from './components/HealthStatus';
import { SourceMode } from './components/RuntimeStatus';
import PlaceholderPage from './pages/PlaceholderPage';

const CommandsPage = lazy(() => import('./pages/CommandsPage'));
const LocationsPage = lazy(() => import('./pages/LocationsPage'));
const ConnectionsPage = lazy(() => import('./pages/ConnectionsPage'));
const DevicesPage = lazy(() => import('./pages/DevicesPage'));
const TagsPage = lazy(() => import('./pages/TagsPage'));
const TagDetailsPage = lazy(() => import('./pages/TagDetailsPage'));

const drawerWidth = 240;
// Shell navigation only. Dashboard definitions and widgets will come from PostgreSQL.
const pages = ['Dashboard', 'Locations', 'Connections', 'Devices', 'Tags', 'Commands', 'Alarms', 'Users', 'Settings'];

export default function App() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigation = (
    <>
      <Toolbar><Typography fontWeight={700}>MODBUS MONITOR</Typography></Toolbar>
      <Divider />
      <List sx={{ px: 1 }}>
        {pages.map((page) => (
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
        <Toolbar sx={{ gap: 1 }}>
          <IconButton color="inherit" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)} edge="start" sx={{ display: { md: 'none' } }}><MenuIcon /></IconButton>
          <Typography sx={{ flexGrow: 1, fontSize: { xs: 14, sm: 18 } }}>Monitoring workspace</Typography>
          <HealthStatus />
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
        <Suspense fallback={<Typography role="status">Loading page…</Typography>}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/locations" element={<LocationsPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/commands" element={<CommandsPage />} />
          <Route path="/tags" element={<TagsPage />} />
          <Route path="/tags/:id" element={<TagDetailsPage key={location.pathname} />} />
          {['Dashboard', 'Alarms', 'Users', 'Settings'].map((page) => <Route key={page} path={`/${page.toLowerCase()}`} element={<PlaceholderPage title={page} />} />)}
          <Route path="*" element={<Typography component="h1">Page not found</Typography>} />
        </Routes>
        </Suspense>
      </Box>
    </Box>
  );
}
