#!/usr/bin/env bash
# Faz o script parar se houver algum erro
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate