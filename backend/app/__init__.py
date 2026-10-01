"""Application factory: wires configuration, database, routes and error handling."""
from __future__ import annotations

import logging

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from .api.routes import bp as api_bp
from .config import Settings, get_settings
from .db import Database
from .errors import ApiError
from .services.notifier import AlertNotifier, build_notifier

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, notifier: AlertNotifier | None = None) -> Flask:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = Flask(__name__)
    app.json.sort_keys = False
    app.extensions["db"] = Database(settings.database_url)
    app.extensions["notifier"] = notifier or build_notifier(settings.alert_notifier, settings.alert_webhook_url)
    app.register_blueprint(api_bp)

    allowed_origins = set(settings.cors_origin_list)

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        if origin and (origin in allowed_origins or "*" in allowed_origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Idempotency-Key"
            response.headers["Access-Control-Expose-Headers"] = "Idempotent-Replayed, Location"
        return response

    @app.teardown_appcontext
    def close_connection(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return jsonify(err.to_dict()), err.status

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 400: "BAD_REQUEST"}.get(err.code or 500, "HTTP_ERROR")
        return jsonify({"error": {"code": code, "message": err.description}}), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.path)
        return jsonify({"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong on the server."}}), 500

    return app
