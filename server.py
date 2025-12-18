from flask import Flask, request, jsonify, send_from_directory
from pms import core

app = Flask(__name__)

# serving the simple html frontend from /frontend folder
@app.route("/")
def root():
    return send_from_directory("frontend", "index.html")


# any other static file like css/js/images goes here
@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory("frontend", filename)


# basic login endpoint, reads json or form post
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() if request.is_json else request.form
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    try:
        result = core.api_login(username, password)
        return jsonify(result), 200
    except core.Unauthorized as e:
        return jsonify({"error": str(e)}), 401


# superuser area, still not wired to real user list yet
@app.route("/api/users", methods=["GET"])
def list_users():
    # hardcoded user for now, until proper auth token added
    current_user = {"role": "SUPERUSER"}

    try:
        # placeholder, later will call core api when it exists
        return jsonify({"message": "Not implemented yet"}), 501
    except Exception as e:
        # generic catch so flask dont crash
        return jsonify({"error": str(e)}), 500


# show booking grid, staff/superuser can see
@app.route("/api/grid", methods=["GET"])
def grid():
    # fake staff session for now
    current_user = {"role": "STAFF"}

    try:
        return jsonify(core.api_grid(current_user)), 200
    except core.Forbidden as e:
        return jsonify({"error": str(e)}), 403


# create new reservation, takes form fields from frontend
@app.route("/api/guest-reservations", methods=["POST"])
def create_reservation():
    # later this should come from login/session
    current_user = {"role": "STAFF"}
    data = request.form

    try:
        result = core.api_guest_reservations(
            current_user,
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            email=data.get("email"),
            phone=data.get("phone"),
            stay_date_str=data.get("stay_date_str"),
        )
        return jsonify(result), 201

    except core.BadRequest as e:
        # like no rooms, bad date, etc
        return jsonify({"error": str(e)}), 400
    except core.Forbidden as e:
        return jsonify({"error": str(e)}), 403


# cancel reservation by id
@app.route("/api/cancel", methods=["POST"])
def cancel_reservation():
    # fake staff again, real auth later
    current_user = {"role": "STAFF"}
    data = request.get_json() if request.is_json else request.form
    res_id = int(data.get("reservation_id"))

    try:
        return jsonify(core.api_cancel(current_user, res_id)), 200
    except core.BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except core.NotFound as e:
        return jsonify({"error": str(e)}), 404


# local dev run only
if __name__ == "__main__":
    app.run(debug=True)
