FROM node:24.14.1-alpine AS build

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web ./apps/web
RUN pnpm --filter @swim-coach/web build

FROM nginxinc/nginx-unprivileged:1.29.4-alpine AS runtime
USER root
RUN apk upgrade --no-cache
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
USER 101
EXPOSE 8080
