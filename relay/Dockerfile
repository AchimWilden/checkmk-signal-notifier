FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY app.py /app/app.py
RUN useradd --system --uid 10001 --no-create-home relay
USER 10001:10001

EXPOSE 8080
CMD ["python", "/app/app.py"]
