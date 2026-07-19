"""
One-off creation of the first admin user.
Run inside the container: docker compose exec app python -m app.create_admin
"""
import getpass

from app.auth import hash_password
from app.db import SessionLocal
from app.models import User
from app.services.demo_seed import seed_demo_data
from app.services.setup import needs_setup


def main():
    username = input("Admin username: ").strip()
    password = getpass.getpass("Password: ")
    db = SessionLocal()
    try:
        if db.query(User).filter_by(username=username).first():
            print("A user with this username already exists.")
            return
        is_first_user = needs_setup(db)
        user = User(username=username, password_hash=hash_password(password), role="admin")
        db.add(user)
        db.commit()
        print(f"Created user {username} with role admin.")

        if is_first_user:
            seed_demo_data(db, actor=user)
            print("Seeded demo platform/variant/item (DEMO 4U AI Server / DEMO-0001).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
