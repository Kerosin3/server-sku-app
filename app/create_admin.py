"""
One-off creation of the first admin user.
Run inside the container: docker compose exec app python -m app.create_admin
"""
import getpass

from app.auth import hash_password
from app.db import SessionLocal
from app.models import User


def main():
    username = input("Admin username: ").strip()
    password = getpass.getpass("Password: ")
    db = SessionLocal()
    try:
        if db.query(User).filter_by(username=username).first():
            print("A user with this username already exists.")
            return
        user = User(username=username, password_hash=hash_password(password), role="admin")
        db.add(user)
        db.commit()
        print(f"Created user {username} with role admin.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
