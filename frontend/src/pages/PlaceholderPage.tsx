import { Box, Paper, Typography } from '@mui/material';

export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <Box>
      <Typography variant="overline" color="text.secondary">Workspace</Typography>
      <Typography component="h1" variant="h4" fontWeight={650} sx={{ mb: 3 }}>{title}</Typography>
      <Paper variant="outlined" sx={{ p: { xs: 3, md: 5 }, maxWidth: 900 }}>
        <Typography component="h2" variant="h6" gutterBottom>{title} will be available here</Typography>
        <Typography color="text.secondary">
          This workspace is ready for future configuration. No items have been configured.
        </Typography>
      </Paper>
    </Box>
  );
}
