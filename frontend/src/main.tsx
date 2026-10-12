import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { CssBaseline, ThemeProvider } from '@mui/material';
import App from './App';
import AuthProvider from './auth/AuthProvider';
import AuthGate from './auth/AuthGate';
import { appTheme } from './layout/theme';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider theme={appTheme}>
      <CssBaseline />
      <BrowserRouter><AuthProvider><AuthGate><App /></AuthGate></AuthProvider></BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
);
