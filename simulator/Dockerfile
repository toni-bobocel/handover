FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml .
COPY handover_sim handover_sim
RUN pip install --no-cache-dir .
EXPOSE 7070 9090
CMD ["python", "-m", "handover_sim", "--config", "/etc/handover/fleet.toml", "--core", "http://core:8080"]
