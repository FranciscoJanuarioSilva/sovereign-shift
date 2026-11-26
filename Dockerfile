# terraform binary for the validate button
FROM docker.io/hashicorp/terraform:1.9.8 AS terraform

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY --from=terraform /bin/terraform /usr/local/bin/terraform

COPY pyproject.toml README.md LICENSE ./
COPY sovereign_shift ./sovereign_shift
COPY data ./data
COPY mappings ./mappings
COPY runbook ./runbook
COPY skills ./skills
COPY docs/schemas ./docs/schemas
COPY testdata ./testdata
COPY frontend/serve.py ./frontend/serve.py
COPY frontend/dist ./frontend/dist

# editable so the code finds data/ and mappings/ in /app
RUN pip install -e '.[azure]'

RUN useradd --system --uid 10001 --create-home app && chown -R app /app
USER app

EXPOSE 8000
CMD ["python", "frontend/serve.py", "--port", "8000", "--bind", "0.0.0.0"]
