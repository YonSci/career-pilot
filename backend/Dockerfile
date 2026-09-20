FROM node:22-bookworm-slim AS dashboard
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate \
    && pnpm config set fetch-timeout 600000 && pnpm config set fetch-retries 5 \
    && pnpm config set network-concurrency 4 \
    && pnpm install --frozen-lockfile
COPY . .
RUN pnpm exec vite build --config vite.client.config.ts

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/career ./career
COPY --from=dashboard /src/dist/dashboard ./dashboard
RUN useradd --uid 10001 --create-home career && mkdir -p /app/data && chown -R career:career /app/data
USER career
ENV PYTHONUNBUFFERED=1 DASHBOARD_DIR=/app/dashboard
EXPOSE 8000
CMD ["uvicorn","career.main:app","--host","0.0.0.0","--port","8000"]
