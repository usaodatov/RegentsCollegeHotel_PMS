from pms.core import (
    api_login,
    api_guest_reservations,
    api_grid,
    api_reservations,
    api_check_in,
    api_check_out,
    api_cancel,
    get_today_in_hotel_timezone,
    BadRequest,
    Unauthorized,
    Forbidden,
)


def print_header(title: str):
    # small helper to make console output readable
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    # try login using default superuser
    print_header("1) Login as superuser")
    try:
        login_result = api_login("superuser", "password")
        print("Login OK:", login_result)
    except Unauthorized as e:
        print("Login failed:", e)
        return

    # fake staff user for testing flows
    staff_user = {"id": 2, "username": "staff1", "role": "STAFF"}

    # create reservation for today date
    print_header("2) Create guest reservation for today")
    today_str = str(get_today_in_hotel_timezone())
    try:
        res = api_guest_reservations(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            phone="1234567890",
            stay_date_str=today_str,
        )
        print("Reservation created:", res)
        reservation_id = res["reservation_id"]
    except BadRequest as e:
        print("Failed to create reservation:", e)
        return

    # show grid view as staff
    print_header("3) Availability grid for next 5 days (STAFF)")
    try:
        grid_data = api_grid(staff_user)
        print("Rooms:", grid_data["rooms"])
        print("Dates:", grid_data["dates"])
        print("Grid (per room):")
        for row in grid_data["grid"]:
            print(row)
    except (Unauthorized, Forbidden) as e:
        print("Grid error:", e)

    # list reservations for today only
    print_header("4) Reservations for today (STAFF)")
    reservations = api_reservations(staff_user, today_str)
    print(reservations)

    # test state changes on same reservation
    print_header("5) Check-in / Check-out / Cancel flow")
    try:
        print("Check-in:", api_check_in(staff_user, reservation_id))
        print("Check-out:", api_check_out(staff_user, reservation_id))
        print("Cancel (expected to fail now):")
        print(api_cancel(staff_user, reservation_id))
    except BadRequest as e:
        print("Operation error:", e)


if __name__ == "__main__":
    # manual run entry point
    main()
