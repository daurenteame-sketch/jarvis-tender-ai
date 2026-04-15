"""
Create or update admin user.
Run inside the backend container:
    docker compose exec backend python create_admin.py
"""
import asyncio
from sqlalchemy import select
from core.database import async_session_factory, create_tables
from core.security import hash_password
from models.user import User
from models.company import Company

ADMIN_EMAIL = "admin@tender.ai"
ADMIN_PASSWORD = "admin123"
ADMIN_ROLE = "admin"


async def main():
    print("[*] Ensuring tables exist...")
    await create_tables()

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        user = result.scalar_one_or_none()

        if user:
            user.email = ADMIN_EMAIL
            user.hashed_password = hash_password(ADMIN_PASSWORD)
            user.role = ADMIN_ROLE
            user.is_active = True
            await session.commit()
            print(f"[✓] Updated existing user → {ADMIN_EMAIL} (role={ADMIN_ROLE})")
        else:
            # Create a standalone company for the admin
            result2 = await session.execute(select(Company).where(Company.name == "JARVIS Admin"))
            company = result2.scalar_one_or_none()
            if not company:
                company = Company(name="JARVIS Admin")
                session.add(company)
                await session.flush()

            user = User(
                email=ADMIN_EMAIL,
                hashed_password=hash_password(ADMIN_PASSWORD),
                role=ADMIN_ROLE,
                is_active=True,
                company_id=company.id,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"[✓] Created new admin user → {ADMIN_EMAIL} (role={ADMIN_ROLE})")

        print(f"    ID: {user.id}")
        print(f"    Password hash stored: {user.hashed_password[:30]}...")
        print()
        print("[✓] Done. You can now log in at the frontend with:")
        print(f"    Email:    {ADMIN_EMAIL}")
        print(f"    Password: {ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
