import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import App from './App';
import AuthProvider from './auth/AuthProvider';
import AuthGate from './auth/AuthGate';

const theme = createTheme({
  palette: { primary: { main: '#176b80' }, background: { default: '#f3f6f9' } },
  typography: { fontFamily: 'Inter, system-ui, -apple-system, sans-serif' },
  shape: { borderRadius: 10 },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter><AuthProvider><AuthGate><App /></AuthGate></AuthProvider></BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
);
