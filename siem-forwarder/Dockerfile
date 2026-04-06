FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY siem_forwarder.py .

ENV KC_BASE_URL=https://keycloak.iam-lab.local:8443
ENV KC_REALM=enterprise
ENV SIEM_URL=http://siem-receiver:5000
ENV POLL_INTERVAL=30
ENV STATE_FILE=/state/.siem_state.json

HEALTHCHECK --interval=60s --timeout=5s \
  CMD python3 -c "import requests; requests.get('${SIEM_URL}/health', timeout=3)" || exit 0

CMD ["python3", "siem_forwarder.py"]
