FROM python:3.12-slim

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# guardrails-ai ships anonymous hub telemetry that exports OTEL spans to its own
# endpoint. It is unrelated to our Langfuse tracing and only adds connection
# errors in containers, so turn it off.
RUN printf 'enable_metrics=false\n' > /root/.guardrailsrc

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
