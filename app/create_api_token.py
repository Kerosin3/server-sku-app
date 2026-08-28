"""
Issue and inspect API tokens from the command line.

The same thing /api-tokens does in the web interface, for when there is
no browser to hand — first-time setup, a server session, or an admin
who has locked themselves out.

    docker compose exec app python -m app.create_api_token \
        --name "LangChain agent" --user api --role engineer

    docker compose exec app python -m app.create_api_token --list

The token is printed once and cannot be retrieved afterwards; only its
hash is stored. Lost one is revoked and replaced, at /api-tokens.
"""
import argparse
import sys

from app.auth import ROLES_ORDER
from app.db import SessionLocal
from app.models import User
from app.services import api_tokens as tokens_service


def _print_list(db) -> None:
    rows = tokens_service.list_tokens(db)
    if not rows:
        print("No tokens issued yet.")
        return
    print(f"{'name':<28} {'prefix':<14} {'role':<10} {'acts as':<16} status")
    for token in rows:
        status = "revoked" if token.revoked_at else "active"
        print(
            f"{token.name:<28} {token.token_prefix + '…':<14} {token.role:<10} "
            f"{token.user.username:<16} {status}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue an API token.")
    parser.add_argument("--name", help="What this token is for, e.g. 'LangChain agent'")
    parser.add_argument("--user", help="Existing username the token acts as (see /users)")
    parser.add_argument("--role", choices=ROLES_ORDER, help="Rights of the token")
    parser.add_argument("--list", action="store_true", help="List tokens and exit")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            _print_list(db)
            return 0

        name = args.name or input("Token name (e.g. 'LangChain agent'): ").strip()
        username = args.user or input("Acts as which user: ").strip()
        role = args.role or input(f"Role {ROLES_ORDER}: ").strip()

        user = db.query(User).filter_by(username=username).first()
        if user is None:
            print(f"No user named '{username}'. Create one at /users first.", file=sys.stderr)
            return 1

        try:
            token, raw_token = tokens_service.create_token(
                db, actor=None, name=name, user=user, role=role
            )
        except tokens_service.NameRequiredError:
            print("A name is required.", file=sys.stderr)
            return 1
        except tokens_service.InvalidRoleError:
            print(f"Role must be one of {ROLES_ORDER}.", file=sys.stderr)
            return 1
        except tokens_service.InactiveUserError:
            print(f"User '{username}' is deactivated; reactivate it at /users first.", file=sys.stderr)
            return 1
        except tokens_service.RoleExceedsUserError:
            print(
                f"Cannot give a token the '{role}' role: user '{username}' is only "
                f"'{user.role}', and a token never exceeds its user.",
                file=sys.stderr,
            )
            return 1
        except tokens_service.NameTakenError:
            print(f"A live token named '{name}' already exists; revoke it first.", file=sys.stderr)
            return 1

        print(f"\nToken '{token.name}' created — role {token.role}, acting as {user.username}.")
        print("Copy it now; it is not stored and cannot be shown again:\n")
        print(f"    {raw_token}\n")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
