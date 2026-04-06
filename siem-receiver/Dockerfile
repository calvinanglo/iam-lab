FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV SIEM_PORT=5000
ENV SIEM_AUDIT_FILE=/var/log/siem/keycloak-events.jsonl

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s \
  CMD wget -qO- http://localhost:5000/health || exit 1

CMD ["python3", "app.py"]
