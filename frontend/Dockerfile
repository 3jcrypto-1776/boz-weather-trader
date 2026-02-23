# ── Stage 1: Build ──
FROM node:20-slim AS builder

WORKDIR /app

# Install all dependencies (including devDependencies for build)
COPY package*.json ./
RUN npm ci

# Copy application source
COPY . .

# Accept build args (baked into JS bundle by Next.js)
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_APP_VERSION=0.0.0
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_APP_VERSION=${NEXT_PUBLIC_APP_VERSION}

# Build optimized production bundle
RUN npm run build

# ── Stage 2: Production ──
FROM node:20-slim AS runner

WORKDIR /app

ENV NODE_ENV=production

# Copy only production dependencies + built output
COPY --from=builder /app/package*.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.js ./

EXPOSE 3000

CMD ["npm", "start"]
