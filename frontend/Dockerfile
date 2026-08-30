# Transaction Twin — Frontend Dockerfile
# Multi-stage build: build Next.js, then run in minimal production image

# ── Stage 1: Dependencies ──────────────────────────────────────────
FROM node:20-alpine AS deps

WORKDIR /app

# Copy package files first for Docker layer caching
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# ── Stage 2: Build ─────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Copy node_modules from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy source code
COPY . .

# Accept build-time env var for API URL
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Build with standalone output
RUN npm run build

# ── Stage 3: Production ────────────────────────────────────────────
FROM node:20-alpine AS production

# Security: non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

# Copy standalone output
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

# Ensure writable directories for the non-root user
RUN chown -R appuser:appgroup /app

USER appuser

# Application port
EXPOSE 3000

# Environment
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME="0.0.0.0"

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:3000/ || exit 1

# Production command
CMD ["node", "server.js"]
