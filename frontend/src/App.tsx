import Can from './auth/Can';
import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Typography } from '@mui/material';
import AppShell from './layout/AppShell';

const SystemPage = lazy(() => import('./pages/SystemPage'));
const BackupRestorePage = lazy(() => import('./pages/BackupRestorePage'));
const UpdatesPage = lazy(() => import('./pages/UpdatesPage'));
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

export default function App() {
  const location = useLocation();
  return (
    <AppShell>
      <Suspense fallback={<Typography role="status">Loading page...</Typography>}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/users" element={<Can permission="users"><UsersPage /></Can>} />
          <Route path="/audit" element={<Can permission="audit"><AuditPage /></Can>} />
          <Route path="/settings/backups" element={<Can permission="users"><BackupRestorePage /></Can>} />
          <Route path="/settings/updates" element={<Can permission="users"><UpdatesPage /></Can>} />
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
    </AppShell>
  );
}
