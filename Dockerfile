# Written for a future container run. This image was not built or run on the workstation.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY web ./web
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 65532 membercare
USER membercare
ENV MEMBERCARE_VAR=/tmp/membercare
EXPOSE 8765
CMD ["python", "-m", "membercare", "--host", "0.0.0.0", "--port", "8765"]
