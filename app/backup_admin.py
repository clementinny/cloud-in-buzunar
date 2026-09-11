from threading import Timer

from flask import Blueprint, jsonify, request

from app.backup import (
    BackupRestoreError,
    BackupRestoreInProgressError,
    BackupValidationError,
    get_backup_records,
    reload_gunicorn,
    restore_backup,
    verify_backup,
)
from app.system_status import require_status_admin


backup_admin_blueprint = Blueprint("backup_admin", __name__)


def schedule_gunicorn_reload():
    timer = Timer(1.5, reload_gunicorn)
    timer.daemon = True
    timer.start()


@backup_admin_blueprint.get("/api/admin/backups")
@require_status_admin
def admin_list_backups():
    backups = get_backup_records()

    return jsonify(
        {
            "count": len(backups),
            "backups": backups,
        }
    )


@backup_admin_blueprint.post(
    "/api/admin/backups/<string:backup_name>/verify"
)
@require_status_admin
def admin_verify_backup(backup_name):
    try:
        result = verify_backup(backup_name)
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 404
    except BackupValidationError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(
        {
            "status": "verified",
            "backup": result,
        }
    )


@backup_admin_blueprint.post(
    "/api/admin/backups/<string:backup_name>/restore"
)
@require_status_admin
def admin_restore_backup(backup_name):
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Expected JSON body"}), 400

    if payload.get("confirmation") != backup_name:
        return jsonify(
            {
                "error": (
                    "Confirmarea nu corespunde numelui backupului."
                )
            }
        ), 400

    try:
        result = restore_backup(backup_name)
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 404
    except BackupValidationError as error:
        return jsonify({"error": str(error)}), 400
    except BackupRestoreInProgressError as error:
        return jsonify({"error": str(error)}), 409
    except BackupRestoreError as error:
        return jsonify({"error": str(error)}), 500

    schedule_gunicorn_reload()

    return jsonify(
        {
            "status": "restored",
            "restart_scheduled": True,
            **result,
        }
    )
