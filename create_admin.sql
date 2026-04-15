-- Create or update admin user: admin@tender.ai / admin123
-- Run on server: docker compose exec postgres psql -U jarvis -d jarvis_db -f /tmp/create_admin.sql

DO $$
DECLARE
    v_company_id UUID;
    v_user_id    UUID;
BEGIN
    -- Ensure admin company exists
    SELECT id INTO v_company_id FROM companies WHERE name = 'JARVIS Admin' LIMIT 1;
    IF v_company_id IS NULL THEN
        INSERT INTO companies (id, name, created_at, updated_at)
        VALUES (gen_random_uuid(), 'JARVIS Admin', NOW(), NOW())
        RETURNING id INTO v_company_id;
    END IF;

    -- Upsert user
    SELECT id INTO v_user_id FROM users WHERE email = 'admin@tender.ai' LIMIT 1;
    IF v_user_id IS NULL THEN
        INSERT INTO users (id, email, hashed_password, role, is_active, company_id, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'admin@tender.ai',
            '$2b$12$Gva705h1fk5gvB0ZP29M8eV9L2WCyK0hUYEeN1Kbiydqywwtieq2C',
            'admin',
            TRUE,
            v_company_id,
            NOW(),
            NOW()
        );
        RAISE NOTICE 'Admin user CREATED: admin@tender.ai';
    ELSE
        UPDATE users SET
            hashed_password = '$2b$12$Gva705h1fk5gvB0ZP29M8eV9L2WCyK0hUYEeN1Kbiydqywwtieq2C',
            role = 'admin',
            is_active = TRUE,
            updated_at = NOW()
        WHERE id = v_user_id;
        RAISE NOTICE 'Admin user UPDATED: admin@tender.ai';
    END IF;
END;
$$;

-- Verify
SELECT id, email, role, is_active, LEFT(hashed_password, 30) AS hash_prefix FROM users WHERE email = 'admin@tender.ai';
