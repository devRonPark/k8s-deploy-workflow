if [ "$SERVER" = "gunicorn" ]; then exec gunicorn main:app; else exec uvicorn main:app --host 0.0.0.0; fi
