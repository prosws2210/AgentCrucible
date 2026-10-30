# Frontend: build the static Next.js export, serve it with nginx, proxy /api to the backend.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# "Report a bug" mails reports when this is set (BUG_REPORT_KEY in .env); empty: it opens a GitHub issue
ARG NEXT_PUBLIC_BUG_REPORT_KEY=""
ENV NEXT_PUBLIC_BUG_REPORT_KEY=$NEXT_PUBLIC_BUG_REPORT_KEY
# Served at the domain root behind nginx; the API is same-origin (/api).
ENV NEXT_PUBLIC_BASE_PATH="" NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/out /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
