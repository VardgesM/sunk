import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AppBar, Box, Drawer, IconButton, Link, Toolbar, Typography, useMediaQuery, useTheme } from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import { useLocation } from 'react-router-dom';
import AccountMenu from '../auth/AccountMenu';
import { SourceMode } from '../components/RuntimeStatus';
import AppNavigation from './AppNavigation';
import { pageTitle } from './navigation';
import { shellLayout } from './tokens';

export default function AppShell({ children }: { children: ReactNode }) {
  const desktop = useMediaQuery(useTheme().breakpoints.up(shellLayout.desktopBreakpoint));
  const location = useLocation();
  const context = `${location.key}:${desktop}`;
  const [drawer, setDrawer] = useState({ context, open: false, restoreFocus: true });
  // Discard transient drawer state on navigation/breakpoint changes, without an effect render.
  if (drawer.context !== context) setDrawer({ context, open: false, restoreFocus: false });
  const open = drawer.context === context && drawer.open;
  const close = () => setDrawer({ context, open: false, restoreFocus: true });
  const main = useRef<HTMLElement>(null);
  const previousLocation = useRef(location.key);
  const title = pageTitle(location.pathname);
  useEffect(() => {
    if (previousLocation.current !== location.key) {
      main.current?.focus({ preventScroll: true });
      window.scrollTo(0, 0);
    }
    previousLocation.current = location.key;
  }, [location.key, desktop]);
  useEffect(() => { document.title = `${title} | Modbus Monitor`; }, [title]);

  return <Box sx={{ display: 'flex', minHeight: '100dvh' }}>
    <Link href="#main-content" onClick={() => main.current?.focus()} sx={{ position: 'fixed', top: 8, left: 8, zIndex: 'tooltip', p: 1.5, bgcolor: 'background.paper', borderRadius: 1, transform: 'translateY(-200%)', '&:focus': { transform: 'none' } }}>Skip to content</Link>
    <Drawer variant={desktop ? 'permanent' : 'temporary'} open={desktop || open} onClose={close}
      // Route navigation focuses the content; dismissing the drawer restores its trigger.
      ModalProps={{ disableRestoreFocus: !drawer.restoreFocus }}
      slotProps={{ transition: { onExited: () => { if (!drawer.restoreFocus) main.current?.focus({ preventScroll: true }); } } }}
      sx={{ width: desktop ? shellLayout.sidebarWidth : 0, flexShrink: 0,
        '& .MuiDrawer-paper': { width: shellLayout.sidebarWidth, maxWidth: 'calc(100vw - 32px)', boxSizing: 'border-box' } }}>
      <AppNavigation onNavigate={() => setDrawer({ context, open: false, restoreFocus: false })} onClose={desktop ? undefined : close} />
    </Drawer>
    <Box sx={{ flex: 1, minWidth: 0 }}>
      <AppBar component="header" position="sticky" elevation={0} sx={{ bgcolor: '#132b40' }}>
        <Toolbar sx={{ gap: 1, minHeight: { xs: 64 }, px: shellLayout.pagePadding }}>
          {!desktop && <IconButton color="inherit" aria-label="Open navigation" aria-controls={open ? 'main-navigation' : undefined} aria-expanded={open} onClick={() => setDrawer({ context, open: true, restoreFocus: true })} edge="start" sx={{ width: shellLayout.touchTarget, height: shellLayout.touchTarget, flexShrink: 0 }}><MenuIcon /></IconButton>}
          <Typography component="p" sx={{ flex: 1, minWidth: 0, fontWeight: 600, fontSize: { xs: '1rem', sm: '1.125rem' }, lineHeight: 1.3, overflowWrap: 'anywhere', py: 1 }}>{title}</Typography>
          <AccountMenu />
        </Toolbar>
      </AppBar>
      <Box component="main" id="main-content" ref={main} tabIndex={-1} aria-label={title}
        sx={{ width: '100%', minWidth: 0, maxWidth: shellLayout.contentMaxWidth, mx: 'auto', p: shellLayout.pagePadding,
          overflowWrap: 'break-word', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
          '& > *': { minWidth: 0 }, '& h1.MuiTypography-h4': { fontSize: { xs: '1.5rem', sm: '1.875rem', lg: '2.125rem' } } }}>
        <SourceMode />
        {children}
      </Box>
    </Box>
  </Box>;
}
