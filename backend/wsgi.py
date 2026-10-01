"""WSGI entry point for production servers:  gunicorn wsgi:app"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    from app.config import get_settings

    app.run(host="0.0.0.0", port=get_settings().api_port, debug=False, threaded=True)
