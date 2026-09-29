# SvelteKit dashboard (adapter-node) — Fuel Supply Intelligence & Resilience Platform
FROM node:20 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20 AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# PUBLIC_API_BASE is baked at build time (vite $env/static/public)
ARG PUBLIC_API_BASE=http://localhost:8080
ENV PUBLIC_API_BASE=${PUBLIC_API_BASE}
RUN npm run build

FROM node:20 AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3000 ORIGIN=http://localhost:3000
COPY --from=builder /app/build ./build
COPY --from=builder /app/node_modules ./node_modules
EXPOSE 3000
CMD ["node", "build/index.js"]
