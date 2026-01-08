from flask import Flask, request, jsonify, send_from_directory
from pms import core
from functools import wraps
from flask import session, redirect
import os



app = Flask(__name__)
app.secret_key = "your-secret-key"

@app.get("/api/health")
def health():
    # db mode: mysql if DB_HOST set, else sqlite
    db_mode = "mysql" if (os.getenv("DB_HOST") or "").strip() else "sqlite"
    return {"ok": True, "db_mode": db_mode, "git": "059c4eb"}, 200
# serve landing page from frontend folder
@app.route("/")
def root():
    # just index.html, no template engine here
    return send_from_directory("frontend", "index.html")


# serve css/js/images + other html files
@app.route("/<path:filename>")
def serve_static(filename):
    # simple static hosting, good enough for coursework
    return send_from_directory("frontend", filename)


# login endpoint, accepts json or form
@app.route("/api/login", methods=["POST"])
def login_api():
    # frontend might send form, postman might send json
    data = request.get_json() if request.is_json else request.form
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    try:
        # auth logic is inside core
        result = core.api_login(username, password)
        return jsonify(result), 200
    except core.Unauthorized as e:
        # wrong creds mostly
        return jsonify({"error": str(e)}), 401


# admin users endpoint (list + create)
@app.route("/api/users", methods=["GET", "POST"])
def users():
    # hardcoded now, later replace with real session/token
    current_user = {"role": "SUPERUSER"}

    try:
        if request.method == "GET":
            # list users for admin view
            return jsonify(core.api_users_list(current_user)), 200

        # create user (staff usually)
        data = request.get_json() if request.is_json else request.form
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        role = (data.get("role") or "STAFF").strip()

        # returns id + role etc
        return jsonify(core.api_users_create(current_user, username, password, role)), 201

    except core.BadRequest as e:
        # like username exists / missing fields
        return jsonify({"error": str(e)}), 400
    except core.Forbidden as e:
        # role check fail
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        # last resort, dont crash server
        return jsonify({"error": str(e)}), 500


# delete user by id (admin)
@app.route("/api/users/delete", methods=["POST"])
def users_delete():
    # still hardcoded, yeah i know
    current_user = {"role": "SUPERUSER"}

    try:
        data = request.get_json() if request.is_json else request.form
        user_id = int(data.get("id"))  # expects "id" field

        return jsonify(core.api_users_delete(current_user, user_id)), 200

    except core.NotFound as e:
        # id not found in db
        return jsonify({"error": str(e)}), 404
    except core.Forbidden as e:
        # not allowed role
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        # any random crash, return json
        return jsonify({"error": str(e)}), 500


# show room grid for next days
@app.route("/api/grid", methods=["GET"])
def grid():
    # fake staff login for now, later from auth
    current_user = {"role": "STAFF"}

    try:
        return jsonify(core.api_grid(current_user)), 200
    except core.Forbidden as e:
        # if role not right
        return jsonify({"error": str(e)}), 403

@app.route("/api/email-log", methods=["GET"])
def email_log():
    log_path = "/var/log/pms/emails.log"

    try:
        if not os.path.exists(log_path):
            return jsonify({"log": ""}), 200

        with open(log_path, "r") as f:
            return jsonify({"log": f.read()}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# list reservations for staff dashboard
@app.route("/api/reservations", methods=["GET"])
def reservations_list():
    # fake staff login for now, later from auth
    current_user = {"role": "STAFF"}
    limit = request.args.get("limit", 25)

    try:
        return jsonify(core.api_reservations_list(current_user, limit=limit)), 200
    except core.Forbidden as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# booking endpoint from form
@app.route("/api/guest-reservations", methods=["POST"])
def create_reservation():
    # pretending staff is logged in
    current_user = {"role": "STAFF"}
    data = request.form  # booking page submits formdata

    try:
        # core creates guest + reservation
        result = core.api_guest_reservations(
            current_user,
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            email=data.get("email"),
            phone=data.get("phone"),
            stay_date_str=(data.get("stay_date_str") or data.get("stay_date")),
        )

        # demo email outbox log (no real emails sent)
        try:
            with open("/var/log/pms/emails.log", "a") as f:
                f.write(
                    f'TO: {data.get("email","")} | SUBJECT: Reservation Confirmation | STATUS: QUEUED\n'
                )
        except Exception:
            # never block booking flow if logging fails
            pass

        return jsonify(result), 201

    except core.BadRequest as e:
        # no rooms, date not allowed, etc
        return jsonify({"error": str(e)}), 400
    except core.Forbidden as e:
        # role issue
        return jsonify({"error": str(e)}), 403





@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return jsonify({"message": "Logged out"}), 200


# decorator to protect routes
def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        parts = auth_header.split()

        if len(parts) != 2 or parts[0] != "Bearer" or parts[1] != "simulated_token":
            return jsonify({"error": "Unauthorized"}), 401

        # define current_user HERE
        request.current_user = {
            "username": "superuser",
            "role": "SUPERUSER"
        }

        return f(*args, **kwargs)
    return decorated




# cancel by reservation id
@app.route("/api/cancel", methods=["POST"])
@token_required
def cancel_reservation():
    current_user = request.current_user
    data = request.get_json()

    # Baby check for missing input
    if not data or "reservation_id" not in data:
        return jsonify({"error": "Missing reservation_id"}), 400

    res_id = int(data["reservation_id"])
    try:
        return jsonify(core.api_cancel(current_user, res_id)), 200
    except core.BadRequest as e:
        # like already checked out, etc
        return jsonify({"error": str(e)}), 400
    except core.NotFound as e:
        # reservation not found
        return jsonify({"error": str(e)}), 404


# JSON booking endpoint. Uses the same logic as /api/guest-reservations.

@app.route("/api/reserve", methods=["POST"])
@token_required
def reserve():
    return jsonify({
        "error": "Endpoint disabled. Use /api/guest-reservations instead."
    }), 410





# disable /api/reserve to avoid confusion (UI uses /api/guest-reservations) / us

#@app.route("/api/reserve", methods=["POST"])
#@token_required
#def reserve():
#    current_user = request.current_user
#    data = request.get_json(silent=True) or {}
#
#    try:
#        result = core.api_guest_reservations(
#            current_user,
#            first_name=data.get("first_name"),
#            last_name=data.get("last_name"),
#            email=data.get("email"),
#            phone=data.get("phone"),
#            stay_date_str=(data.get("stay_date_str") or data.get("stay_date")),
#        )
#
#        # demo email outbox log (no real emails sent)
#        try:
#            with open("/var/log/pms/emails.log", "a") as f:
#                f.write(
#                    f'TO: {data.get("email","")} | SUBJECT: Reservation Confirmation | STATUS: QUEUED\n'
#                )
#        except Exception:
#            pass
#
#        return jsonify(result), 201
#
#    except core.BadRequest as e:
#        return jsonify({"error": str(e)}), 400
#    except core.Forbidden as e:
#        return jsonify({"error": str(e)}), 403




# run locally only
if __name__ == "__main__":
    # debug on for dev, in prod use gunicorn
    app.run(debug=True)
