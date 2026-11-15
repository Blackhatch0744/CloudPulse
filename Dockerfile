FROM python:3.12-slim
WORKDIR /app
COPY dist/cloudpulse-1.0.0-py3-none-any.whl /tmp/
RUN pip install --no-cache-dir /tmp/cloudpulse-1.0.0-py3-none-any.whl && rm /tmp/*.whl
ENV PORT=5000
EXPOSE 5000
CMD ["cloudpulse"]
