# syntax=docker/dockerfile:1

# Build the React Workbench once, then serve it from FastAPI on the same
# origin. That avoids a public CORS surface and keeps relative /api calls
# working without changing client code.
FROM node:20-bookworm-slim AS workbench-build
WORKDIR /app
COPY package.json package-lock.json tsconfig.json ./
RUN npm ci
COPY workbench-ui ./workbench-ui
ARG VITE_PUBLIC_DEMO=true
ENV VITE_PUBLIC_DEMO=$VITE_PUBLIC_DEMO
RUN npm run build:workbench

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY migrations ./migrations
COPY scripts/start_public_demo.py ./scripts/start_public_demo.py
RUN pip install .

COPY --from=workbench-build /app/dist-workbench ./dist-workbench
RUN mkdir -p /app/var/public-demo /app/runs/secrets

ENV INVESTMENT_RESEARCH_STATIC_DIR=/app/dist-workbench \
    INVESTMENT_RESEARCH_DATABASE_PATH=/app/var/public-demo/investment_research.db
EXPOSE 10000
CMD ["python", "scripts/start_public_demo.py"]
