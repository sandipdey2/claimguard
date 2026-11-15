# ClaimGuard container: Streamlit app (default) or, with CMD override, the FastAPI service / HTTP MCP server.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 CG_RUNTIME_DIR=/tmp/claimguard-runtime
WORKDIR /app
COPY requirements.txt requirements-api.txt requirements-azure.txt ./
RUN pip install -r requirements-azure.txt
COPY . .
ARG GIT_SHA=unknown
ENV CG_GIT_SHA=${GIT_SHA}
RUN useradd -m cg && chown -R cg /app
USER cg
EXPOSE 8501 8000 8765
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
