import { createTheme } from '@mui/material';
import { shellLayout } from './tokens';

// Presentation defaults shared by pages and portal-based dialogs/menus.
export const appTheme = createTheme({
  palette: { primary: { main: '#176b80' }, background: { default: '#f3f6f9' } },
  typography: { fontFamily: 'Inter, system-ui, -apple-system, sans-serif' },
  shape: { borderRadius: 10 },
  components: {
    MuiButton: { styleOverrides: { root: { minHeight: shellLayout.touchTarget, maxWidth: '100%', overflowWrap: 'anywhere' } } },
    MuiIconButton: { styleOverrides: { root: { minHeight: shellLayout.touchTarget, minWidth: shellLayout.touchTarget } } },
    MuiTypography: { styleOverrides: { root: { overflowWrap: 'anywhere' },
      h4: ({ theme }) => ({ [theme.breakpoints.down('sm')]: { fontSize: '1.5rem' } }) } },
    MuiFormControl: { styleOverrides: { root: { minWidth: 0 } } },
    MuiInputBase: { styleOverrides: { root: { minHeight: shellLayout.touchTarget } } },
    MuiSelect: { styleOverrides: { select: { whiteSpace: 'normal', overflowWrap: 'anywhere' } } },
    MuiMenuItem: { styleOverrides: { root: ({ theme }) => ({
      whiteSpace: 'normal', overflowWrap: 'anywhere', minHeight: shellLayout.touchTarget,
      [theme.breakpoints.up('sm')]: { minHeight: shellLayout.touchTarget },
    }) } },
    MuiDialog: { styleOverrides: { paper: ({ theme }) => ({
      overflowWrap: 'anywhere',
      [theme.breakpoints.down('sm')]: { '&:not(.MuiDialog-paperFullScreen)': {
        margin: theme.spacing(2), maxWidth: 'calc(100% - 32px)',
        '&.MuiDialog-paperFullWidth': { width: 'calc(100% - 32px)' },
      } },
    }) } },
    MuiDialogContent: { styleOverrides: { root: ({ theme }) => ({
      minWidth: 0, [theme.breakpoints.down('sm')]: { paddingLeft: theme.spacing(2), paddingRight: theme.spacing(2) },
    }) } },
    MuiDialogActions: { defaultProps: { disableSpacing: true }, styleOverrides: { root: ({ theme }) => ({
      flexWrap: 'wrap', gap: theme.spacing(1), padding: theme.spacing(2),
    }) } },
    MuiAlert: { styleOverrides: { message: { minWidth: 0, overflowWrap: 'anywhere' } } },
    MuiChip: { styleOverrides: { root: ({ ownerState }) => ({ height: 'auto', minHeight: ownerState.size === 'small' ? 24 : 32 }),
      label: { whiteSpace: 'normal', overflowWrap: 'anywhere', paddingTop: 2, paddingBottom: 2 },
      clickable: { minHeight: shellLayout.touchTarget } } },
  },
});
