# Built from the repository root: the image carries the console too.
FROM node:24-alpine AS ui
WORKDIR /src/ui
RUN corepack enable
COPY ui/package.json ui/pnpm-lock.yaml ui/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY ui/ ./
RUN pnpm exec vite build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HANDOVER_UI=/app/ui
WORKDIR /app
COPY core/pyproject.toml core/
COPY core/handover core/handover
RUN pip install --no-cache-dir ./core && rm -rf core
COPY --from=ui /src/ui/dist /app/ui
VOLUME /data
EXPOSE 8080
CMD ["handover", "--config", "/etc/handover/fleet.toml"]
