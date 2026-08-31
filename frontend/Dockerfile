# ---- Build stage: compile the production bundle ----
FROM node:20-alpine AS build

WORKDIR /app

# Lockfile-first copy for reproducible, cache-friendly installs.
# package-lock.json is committed, so npm ci gives bit-exact deps on any host.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines VITE_* vars at build time. Default makes the browser call the
# same origin (/api), which the nginx stage proxies to the backend — no
# hostnames baked into the image, so the bundle is environment-agnostic.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ---- Runtime stage: nginx serves the bundle and reverse-proxies the API ----
FROM nginx:1.27-alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
