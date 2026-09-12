import argparse
import hashlib
import ipaddress
import re
import socket
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

from flask import Blueprint, jsonify, render_template, request, session

from app.database import (
    create_web_watcher,
    delete_web_watcher,
    find_user_by_id,
    find_web_watcher,
    initialize_database,
    list_due_web_watchers,
    list_web_watchers,
    record_system_alert_event,
    save_web_watcher_result,
    set_web_watcher_enabled,
    update_web_watcher,
)


web_watchers_blueprint = Blueprint("web_watchers", __name__)
MODES = {"change", "contains", "missing"}
MAX_RESPONSE_BYTES = 1_000_000
FETCH_TIMEOUT_SECONDS = 12
FAILURES_BEFORE_ALERT = 3


class VisibleTextParser(HTMLParser):
    hidden_tags = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() in self.hidden_tags:
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag.casefold() in self.hidden_tags and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)


def normalize_page_content(text, content_type=""):
    visible_text = text

    if "html" in content_type.casefold() or "<html" in text[:1000].casefold():
        parser = VisibleTextParser()
        parser.feed(text)
        parser.close()
        visible_text = " ".join(parser.parts)

    return re.sub(r"\s+", " ", visible_text).strip()


def resolve_public_addresses(hostname, port):
    try:
        addresses = {
            entry[4][0]
            for entry in socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as error:
        raise ValueError("Adresa nu poate fi găsită.") from error

    if not addresses:
        raise ValueError("Adresa nu poate fi găsită.")

    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as error:
            raise ValueError("Adresa serverului este invalidă.") from error

        if not parsed.is_global:
            raise ValueError(
                "Sunt permise numai pagini publice; adresele locale sunt blocate."
            )

    return addresses


def validate_public_url(value):
    if not isinstance(value, str):
        raise ValueError("Adresa paginii este invalidă.")

    normalized = value.strip()

    if not 1 <= len(normalized) <= 2048:
        raise ValueError("Adresa paginii este invalidă.")

    parsed = urlsplit(normalized)

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Folosește o adresă completă HTTP sau HTTPS.")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Adresele care conțin autentificare nu sunt permise.")

    hostname = parsed.hostname.rstrip(".").casefold()

    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("Adresele locale nu sunt permise.")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise ValueError("Portul din adresă este invalid.") from error

    resolve_public_addresses(hostname, port)
    return normalized


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url):
    safe_url = validate_public_url(url)
    request_object = Request(
        safe_url,
        headers={
            "User-Agent": "CloudInBuzunar-Watcher/1.0",
            "Accept": "text/html,text/plain,application/json,application/xml;q=0.9",
            "Accept-Encoding": "identity",
        },
    )
    opener = build_opener(
        SafeRedirectHandler(),
        HTTPSHandler(context=ssl.create_default_context()),
    )

    try:
        with opener.open(request_object, timeout=FETCH_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type()
            declared_length = response.headers.get("Content-Length")

            if declared_length and int(declared_length) > MAX_RESPONSE_BYTES:
                raise ValueError("Pagina depășește limita de 1 MB.")

            if not (
                content_type.startswith("text/")
                or content_type
                in {
                    "application/json",
                    "application/xml",
                    "application/xhtml+xml",
                    "application/rss+xml",
                    "application/atom+xml",
                }
            ):
                raise ValueError("Pagina nu conține text care poate fi urmărit.")

            raw = response.read(MAX_RESPONSE_BYTES + 1)

            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Pagina depășește limita de 1 MB.")

            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            normalized = normalize_page_content(text, content_type)

            if not normalized:
                raise ValueError("Pagina nu conține text vizibil.")

            return normalized
    except HTTPError as error:
        raise ValueError(f"Pagina a răspuns cu HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError, ssl.SSLError) as error:
        raise ValueError("Pagina nu a putut fi contactată.") from error


def validate_watcher_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Datele urmăririi sunt invalide.")

    name = payload.get("name")
    url = payload.get("url")
    mode = payload.get("mode")
    needle = payload.get("needle")
    interval_minutes = payload.get("interval_minutes")
    enabled = payload.get("enabled", True)

    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 80:
        raise ValueError("Numele trebuie să aibă între 2 și 80 de caractere.")

    if mode not in MODES:
        raise ValueError("Tipul urmăririi este invalid.")

    if type(interval_minutes) is not int or not 15 <= interval_minutes <= 1440:
        raise ValueError("Intervalul trebuie să fie între 15 minute și 24 de ore.")

    if type(enabled) is not bool:
        raise ValueError("Starea urmăririi este invalidă.")

    if mode == "change":
        normalized_needle = None
    elif not isinstance(needle, str) or not 1 <= len(needle.strip()) <= 500:
        raise ValueError("Textul urmărit trebuie să aibă între 1 și 500 de caractere.")
    else:
        normalized_needle = needle.strip()

    return {
        "name": name.strip(),
        "url": validate_public_url(url),
        "mode": mode,
        "needle": normalized_needle,
        "interval_minutes": interval_minutes,
        "enabled": enabled,
    }


def serialize_watcher(watcher):
    return {
        "id": watcher["id"],
        "name": watcher["name"],
        "url": watcher["url"],
        "mode": watcher["mode"],
        "needle": watcher["needle"],
        "interval_minutes": watcher["interval_minutes"],
        "enabled": bool(watcher["enabled"]),
        "last_status": watcher["last_status"],
        "last_checked_at": watcher["last_checked_at"],
        "next_check_at": watcher["next_check_at"],
        "last_changed_at": watcher["last_changed_at"],
        "last_error": watcher["last_error"],
        "consecutive_failures": watcher["consecutive_failures"],
    }


def watcher_alert(watcher, event_type, title, message, severity="info"):
    condition = {
        "alert_key": f"watcher:{watcher['id']}",
        "category": "watcher",
        "severity": severity,
        "title": title,
        "message": message,
    }
    return record_system_alert_event(condition, event_type=event_type)


def check_web_watcher(watcher, fetcher=fetch_page, now=None):
    checked_at = now or datetime.now(timezone.utc)
    previous_failures = int(watcher["consecutive_failures"])

    try:
        content = fetcher(watcher["url"])
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        matched = (
            None
            if watcher["mode"] == "change"
            else watcher["needle"].casefold() in content.casefold()
        )
        changed = False
        status = "ok"

        if watcher["mode"] == "change":
            changed = (
                watcher["last_hash"] is not None
                and watcher["last_hash"] != content_hash
            )

            if changed:
                status = "changed"
                watcher_alert(
                    watcher,
                    "triggered",
                    f"Pagină modificată: {watcher['name']}",
                    "Conținutul paginii urmărite s-a schimbat.",
                )
        else:
            condition_active = (
                matched if watcher["mode"] == "contains" else not matched
            )
            previous_match = watcher["last_match"]
            previous_active = None

            if previous_match is not None:
                previous_active = (
                    bool(previous_match)
                    if watcher["mode"] == "contains"
                    else not bool(previous_match)
                )

            changed = previous_active is not None and previous_active != condition_active

            if condition_active:
                status = "alert"

                if previous_active is not True:
                    title = (
                        f"Text găsit: {watcher['name']}"
                        if watcher["mode"] == "contains"
                        else f"Text dispărut: {watcher['name']}"
                    )
                    watcher_alert(
                        watcher,
                        "triggered",
                        title,
                        f"Condiția urmărită este activă pe {watcher['name']}.",
                        "warning" if watcher["mode"] == "missing" else "info",
                    )
            elif previous_active is True:
                watcher_alert(
                    watcher,
                    "resolved",
                    f"Rezolvat: {watcher['name']}",
                    "Condiția urmărită nu mai este activă.",
                )

        if previous_failures >= FAILURES_BEFORE_ALERT:
            watcher_alert(
                watcher,
                "resolved",
                f"Verificare restabilită: {watcher['name']}",
                "Pagina urmărită poate fi contactată din nou.",
            )

        save_web_watcher_result(
            watcher["id"],
            content_hash=content_hash,
            matched=matched,
            status=status,
            error=None,
            failures=0,
            changed=changed,
            checked_at=checked_at,
        )
        return {"ok": True, "status": status, "changed": changed}
    except ValueError as error:
        failures = previous_failures + 1
        message = str(error)

        save_web_watcher_result(
            watcher["id"],
            content_hash=watcher["last_hash"],
            matched=(
                None
                if watcher["last_match"] is None
                else bool(watcher["last_match"])
            ),
            status="error",
            error=message,
            failures=failures,
            changed=False,
            checked_at=checked_at,
        )

        if failures == FAILURES_BEFORE_ALERT:
            watcher_alert(
                watcher,
                "triggered",
                f"Urmărire indisponibilă: {watcher['name']}",
                "Pagina nu a putut fi verificată de trei ori consecutiv.",
                "warning",
            )

        return {"ok": False, "status": "error", "error": message}


def run_due_web_watchers(limit=3):
    results = []

    for watcher in list_due_web_watchers(limit=limit):
        results.append({"id": watcher["id"], **check_web_watcher(watcher)})

    return results


def session_admin():
    user_id = session.get("user_id")
    user = find_user_by_id(user_id) if user_id is not None else None

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user if user["role"] == "admin" else False


def require_admin(view_function):
    def wrapped(*args, **kwargs):
        user = session_admin()

        if user is None:
            return jsonify({"error": "Authentication required"}), 401

        if user is False:
            return jsonify({"error": "Administrator access required"}), 403

        return view_function(*args, **kwargs)

    wrapped.__name__ = view_function.__name__
    return wrapped


@web_watchers_blueprint.get("/watchers")
def watchers_page():
    return render_template("watchers.html")


@web_watchers_blueprint.get("/api/watchers")
@require_admin
def watchers_list_api():
    return jsonify({
        "watchers": [serialize_watcher(item) for item in list_web_watchers()]
    })


@web_watchers_blueprint.post("/api/watchers")
@require_admin
def watchers_create_api():
    try:
        values = validate_watcher_payload(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    watcher_id = create_web_watcher(**values)
    return jsonify(serialize_watcher(find_web_watcher(watcher_id))), 201


@web_watchers_blueprint.put("/api/watchers/<int:watcher_id>")
@require_admin
def watchers_update_api(watcher_id):
    if find_web_watcher(watcher_id) is None:
        return jsonify({"error": "Urmărirea nu există."}), 404

    try:
        values = validate_watcher_payload(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    update_web_watcher(watcher_id, **values)
    return jsonify(serialize_watcher(find_web_watcher(watcher_id)))


@web_watchers_blueprint.patch("/api/watchers/<int:watcher_id>/enabled")
@require_admin
def watchers_enabled_api(watcher_id):
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict) or type(payload.get("enabled")) is not bool:
        return jsonify({"error": "Starea urmăririi este invalidă."}), 400

    if not set_web_watcher_enabled(watcher_id, payload["enabled"]):
        return jsonify({"error": "Urmărirea nu există."}), 404

    return jsonify(serialize_watcher(find_web_watcher(watcher_id)))


@web_watchers_blueprint.post("/api/watchers/<int:watcher_id>/check")
@require_admin
def watchers_check_api(watcher_id):
    watcher = find_web_watcher(watcher_id)

    if watcher is None:
        return jsonify({"error": "Urmărirea nu există."}), 404

    result = check_web_watcher(watcher)
    return jsonify({**result, "watcher": serialize_watcher(find_web_watcher(watcher_id))})


@web_watchers_blueprint.delete("/api/watchers/<int:watcher_id>")
@require_admin
def watchers_delete_api(watcher_id):
    if not delete_web_watcher(watcher_id):
        return jsonify({"error": "Urmărirea nu există."}), 404

    return jsonify({"deleted": True, "id": watcher_id})


def main():
    parser = argparse.ArgumentParser(description="Verify due web watchers")
    parser.add_argument("command", choices=("check-due",))
    parser.add_argument("--limit", type=int, default=3)
    arguments = parser.parse_args()
    initialize_database()
    results = run_due_web_watchers(limit=arguments.limit)
    failures = sum(not result["ok"] for result in results)
    print(f"Web watchers checked: {len(results)}, failed: {failures}")


if __name__ == "__main__":
    main()
