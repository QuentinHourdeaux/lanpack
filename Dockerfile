FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 lanpack \
    && useradd --uid 10001 --gid lanpack --no-create-home lanpack \
    && mkdir /app/data && chown lanpack:lanpack /app/data
COPY app.py ./
COPY templates ./templates
COPY static ./static
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2)"
CMD ["python", "app.py"]
