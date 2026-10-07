FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# The dashboard is served by Firebase Hosting in the cloud; STATIC_DIR stays unset.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --ws-ping-interval 20
