"""
Verification script for database setup.
Run this after Sprint 2 Phase 2 to ensure everything is configured correctly.
"""

import sys

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from config.settings import get_settings
from db.crud import DocumentCRUD
from db.database import engine, session_scope
from db.schema import DocumentStatus


def verify_connection():
    """Test database connection."""
    print("1. Testing database connection...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"   ✓ Connected to PostgreSQL: {version[:50]}...")
        return True
    except OperationalError as e:
        print(f"   ✗ Connection failed: {e}")
        return False


def verify_pgvector():
    """Check pgvector extension."""
    print("\n2. Checking pgvector extension...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
            if result.fetchone():
                print("   ✓ pgvector extension is installed")
                return True
            else:
                print("   ✗ pgvector extension not found")
                return False
    except Exception as e:
        print(f"   ✗ Error checking pgvector: {e}")
        return False


def verify_tables():
    """Check that all required tables exist."""
    print("\n3. Verifying database tables...")
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    required_tables = ["documents", "chunks"]
    all_exist = True

    for table in required_tables:
        if table in tables:
            print(f"   ✓ Table '{table}' exists")
        else:
            print(f"   ✗ Table '{table}' missing")
            all_exist = False

    return all_exist


def verify_document_schema():
    """Check Document table has all required columns."""
    print("\n4. Verifying Document table schema...")
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("documents")}

    required_columns = {
        "id",
        "title",
        "file_path",
        "markdown",
        "doc_metadata",
        "tags",
        "status",
        "status_details",
        "chunks",
        "description",
        "created_at",
        "updated_at",
    }

    missing = required_columns - columns
    if missing:
        print(f"   ✗ Missing columns: {', '.join(missing)}")
        return False
    else:
        print("   ✓ All required columns present")
        return True


def verify_chunk_schema():
    """Check Chunk table has all required columns."""
    print("\n5. Verifying Chunk table schema...")
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("chunks")}

    required_columns = {
        "id",
        "uuid",
        "document_id",
        "chunk_text",
        "chunk_index",
        "chunk_metadata",
        "created_at",
    }

    missing = required_columns - columns
    if missing:
        print(f"   ✗ Missing columns: {', '.join(missing)}")
        return False
    else:
        print("   ✓ All required columns present")
        return True


def verify_crud_operations():
    """Test basic CRUD operations."""
    print("\n6. Testing CRUD operations...")
    try:
        with session_scope() as session:
            crud = DocumentCRUD(session)

            # Create test document
            doc = crud.create_document(
                title="Test Document",
                file_path="https://example.com/test.pdf",
                tags=["test"],
                doc_metadata={"test": True},
            )
            print(f"   ✓ Created document (ID: {doc.id})")

            # Update status
            crud.update_status(
                document_id=doc.id,
                status=DocumentStatus.PARSING,
                status_details="Test status update",
            )
            print("   ✓ Updated document status")

            # Get by status
            docs = crud.get_documents_by_status(DocumentStatus.PARSING)
            print(f"   ✓ Retrieved {len(docs)} documents by status")

            # Delete test document
            session.delete(doc)
            session.commit()
            print("   ✓ Deleted test document")

        return True
    except Exception as e:
        print(f"   ✗ CRUD operations failed: {e}")
        return False


def verify_settings():
    """Check configuration settings."""
    print("\n7. Verifying configuration settings...")
    settings = get_settings()

    checks = {
        "Database URL": bool(settings.database.url),
        "Voyage API Key": bool(settings.embedding.voyage_api_key),
        "LlamaParse API Key": bool(settings.parsing.llamaparse_api_key),
    }

    all_ok = True
    for name, status in checks.items():
        if status:
            print(f"   ✓ {name} configured")
        else:
            print(f"   ⚠ {name} not set (may be optional)")
            # Don't fail on optional settings

    # Check if using Supabase
    if settings.database.is_supabase:
        print("   ✓ Using Supabase database")
    else:
        print("   ℹ Using local PostgreSQL database")

    return all_ok


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("Database Setup Verification - Sprint 2 Phase 2")
    print("=" * 60)

    checks = [
        verify_connection(),
        verify_pgvector(),
        verify_tables(),
        verify_document_schema(),
        verify_chunk_schema(),
        verify_crud_operations(),
        verify_settings(),
    ]

    print("\n" + "=" * 60)
    if all(checks):
        print("✓ ALL CHECKS PASSED - Database setup complete!")
        print("=" * 60)
        return 0
    else:
        print("✗ SOME CHECKS FAILED - Review errors above")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
