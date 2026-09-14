FROM python:3.12-slim

WORKDIR /srv/app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

ENV FLASK_APP=app.main:create_app
EXPOSE 8100

# Gunicorn, not the Flask dev server, in the image that actually ships.
CMD ["gunicorn", "-b", "0.0.0.0:8100", "-w", "2", "--timeout", "120", "app.main:create_app()"]
