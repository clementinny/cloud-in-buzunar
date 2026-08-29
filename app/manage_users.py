import argparse
import getpass

from app.database import (
    create_user,
    initialize_database,
    list_users,
    set_user_password,
    set_user_role,
)


def handle_create(arguments):
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")

    if password != confirmation:
        print("Error: passwords do not match")
        return 1

    try:
        user_id = create_user(
            arguments.username,
            password,
            arguments.role,
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    print(
        f"Created user {arguments.username!r} "
        f"with role {arguments.role!r} and ID {user_id}"
    )

    return 0


def handle_list(_arguments):
    users = list_users()

    if not users:
        print("No users found")
        return 0

    print(
        f"{'ID':<4} "
        f"{'USERNAME':<32} "
        f"{'ROLE':<8} "
        f"{'ACTIVE':<8} "
        "CREATED"
    )

    for user in users:
        active = "yes" if user["is_active"] else "no"

        print(
            f"{user['id']:<4} "
            f"{user['username']:<32} "
            f"{user['role']:<8} "
            f"{active:<8} "
            f"{user['created_at']}"
        )

    return 0

def handle_set_password(arguments):
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")

    if password != confirmation:
        print("Error: passwords do not match")
        return 1

    try:
        set_user_password(
            arguments.username,
            password,
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    print(
        f"Updated password for {arguments.username!r}"
    )

    return 0

def handle_set_role(arguments):
    try:
        set_user_role(
            arguments.username,
            arguments.role,
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    print(
        f"Updated role for {arguments.username!r} "
        f"to {arguments.role!r}"
    )

    return 0

def handle_set_active(arguments):
    try:
        set_user_active(
            arguments.username,
            arguments.active,
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    status = "active" if arguments.active else "inactive"

    print(
        f"Updated user {arguments.username!r} "
        f"to {status!r}"
    )

    return 0

def build_parser():
    parser = argparse.ArgumentParser(
        description="Manage CloudInBuzunar users"
    )

    commands = parser.add_subparsers(dest="command")

    create_parser = commands.add_parser(
        "create",
        help="Create a new user",
    )
    create_parser.add_argument("username")
    create_parser.add_argument(
        "--role",
        choices=("admin", "user"),
        default="user",
    )
    create_parser.set_defaults(handler=handle_create)
    list_parser = commands.add_parser(
        "list",
        help="List all users",
    )
    list_parser.set_defaults(handler=handle_list)
    password_parser = commands.add_parser(
        "set-password",
        help="Set a new password for a user",
    )
    password_parser.add_argument("username")
    password_parser.set_defaults(
        handler=handle_set_password
    )
    role_parser = commands.add_parser(
        "set-role",
        help="Set the role of a user",
    )
    role_parser.add_argument("username")
    role_parser.add_argument(
        "role",
        choices=("admin", "user"),
    )
    role_parser.set_defaults(
        handler=handle_set_role
    )
    activate_parser = commands.add_parser(
        "activate",
        help="Activate a user",
    )
    activate_parser.add_argument("username")
    activate_parser.set_defaults(
        handler=handle_set_active,
        active=True,
    )

    deactivate_parser = commands.add_parser(
        "deactivate",
        help="Deactivate a user",
    )
    deactivate_parser.add_argument("username")
    deactivate_parser.set_defaults(
        handler=handle_set_active,
        active=False,
    )
    return parser


def main():
    initialize_database()

    parser = build_parser()
    arguments = parser.parse_args()

    if not hasattr(arguments, "handler"):
        parser.print_help()
        return 1

    return arguments.handler(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
