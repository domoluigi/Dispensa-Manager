FROM python:3.11-alpine

RUN apk add --no-cache py3-pip py3-virtualenv

WORKDIR /app
COPY . /app/

RUN python3 -m venv /app/venv && \
    /app/venv/bin/pip install --no-cache-dir -r requirements.txt

CMD ["/app/venv/bin/python", "app.py"]
