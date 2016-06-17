#!/bin/bash
# This script is the main entrypoint for the Docker container. It gets executed on launch.
# It begins by checking to see if the PostreSQL server is ready. Once it is, it prepares the
# database and collects the static files to be served by nginx. Then it calls Gunicorn to serve
# the dynamic part of the app.

# Wait for PostgreSQL
if ! python ready.py ${POSTGRES_HOST} ${POSTGRES_PORT}
then
    exit 1  # If we got here, something is wrong.
fi

python manage.py migrate                       # Prepare the database
python manage.py collectstatic --noinput       # Collect the static files for serving

gunicorn attpcdaq.wsgi -b :8000                # Start the Django app