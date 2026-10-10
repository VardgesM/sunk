FROM node:24-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build && chown -R node:node /app
USER node
EXPOSE 5173
# Local development server; Dockerfile.production serves the compiled SPA through nginx.
CMD ["npm", "run", "dev"]
