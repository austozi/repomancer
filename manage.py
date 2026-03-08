
import argparse
from app import create_app
from app.tasks import check_all_apps, check_app_by_id

app = create_app()


def main():
    parser = argparse.ArgumentParser(description="Repomancer management")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("runserver", help="Run Flask dev server")
    run.add_argument("--host", default=None)
    run.add_argument("--port", default=None)

    cu = sub.add_parser("check-updates", help="Check updates")
    grp = cu.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="Check all apps")
    grp.add_argument("--app", type=int, help="Check a specific app by ID")

    args = parser.parse_args()

    if args.command == "runserver":
        host = args.host or app.config.get('HOST', '0.0.0.0')
        port = int(args.port or app.config.get('PORT', 8000))
        app.run(host=host, port=port)
    elif args.command == "check-updates":
        with app.app_context():
            if args.all:
                check_all_apps()
            else:
                check_app_by_id(args.app)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
