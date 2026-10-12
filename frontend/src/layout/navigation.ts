import DashboardOutlined from '@mui/icons-material/DashboardOutlined';
import LabelOutlined from '@mui/icons-material/LabelOutlined';
import NotificationsOutlined from '@mui/icons-material/NotificationsOutlined';
import TuneOutlined from '@mui/icons-material/TuneOutlined';
import AccountTreeOutlined from '@mui/icons-material/AccountTreeOutlined';
import PlaceOutlined from '@mui/icons-material/PlaceOutlined';
import CableOutlined from '@mui/icons-material/CableOutlined';
import DevicesOtherOutlined from '@mui/icons-material/DevicesOtherOutlined';
import SettingsOutlined from '@mui/icons-material/SettingsOutlined';
import PeopleOutline from '@mui/icons-material/PeopleOutline';
import HistoryOutlined from '@mui/icons-material/HistoryOutlined';
import BackupOutlined from '@mui/icons-material/BackupOutlined';
import SystemUpdateAltOutlined from '@mui/icons-material/SystemUpdateAltOutlined';

// Shell destinations only. Feature data and permissions still come from the API.
export const navigationGroups = [
  { label: 'Overview', items: [
    { label: 'Dashboard', path: '/dashboard', icon: DashboardOutlined },
  ] },
  { label: 'Monitoring', items: [
    { label: 'Tags', path: '/tags', icon: LabelOutlined },
    { label: 'History', path: '/history', icon: HistoryOutlined },
    { label: 'Alarms', path: '/alarms', icon: NotificationsOutlined },
  ] },
  { label: 'Control', items: [
    { label: 'Commands', path: '/commands', icon: TuneOutlined },
    { label: 'Automation', path: '/automation', icon: AccountTreeOutlined },
  ] },
  { label: 'Configuration', items: [
    { label: 'Locations', path: '/locations', icon: PlaceOutlined },
    { label: 'Connections', path: '/connections', icon: CableOutlined },
    { label: 'Devices', path: '/devices', icon: DevicesOtherOutlined },
  ] },
  { label: 'System', items: [
    { label: 'System', path: '/settings', icon: SettingsOutlined },
    { label: 'Users', path: '/users', icon: PeopleOutline, permission: 'users' },
    { label: 'Audit', path: '/audit', icon: HistoryOutlined, permission: 'audit' },
    { label: 'Backup & Restore', path: '/settings/backups', icon: BackupOutlined, permission: 'users' },
    { label: 'Updates', path: '/settings/updates', icon: SystemUpdateAltOutlined, permission: 'users' },
  ] },
];

export function isNavigationActive(pathname: string, path: string) {
  const normalized = pathname.replace(/\/$/, '') || '/';
  return normalized === path || (path === '/tags' && /^\/tags\/[^/]+$/.test(normalized));
}

export function pageTitle(pathname: string) {
  const normalized = pathname.replace(/\/$/, '') || '/';
  if (/^\/tags\/[^/]+$/.test(normalized)) return 'Tag details';
  return navigationGroups.flatMap(group => group.items).find(item => item.path === normalized)?.label
    ?? (normalized === '/' ? 'Dashboard' : 'Page not found');
}
