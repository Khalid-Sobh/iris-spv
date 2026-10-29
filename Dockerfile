FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Dependencies first: this layer is cached until the requirements change.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY iris_spv ./iris_spv
COPY fixtures ./fixtures
COPY portal_data ./portal_data
COPY tests ./tests
COPY pytest.ini ./

# Run as a non-root user.
RUN useradd --create-home app && chown -R app /app
USER app

CMD ["python", "-m", "iris_spv", "--help"]
