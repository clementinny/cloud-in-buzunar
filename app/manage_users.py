import argparse
import getpass

from app.database import create_user, initialize_database


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
