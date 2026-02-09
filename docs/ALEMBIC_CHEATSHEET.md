# Alembic Cheat Sheet

## Daily Commands

```bash
# Check current migration version
poetry run alembic current

# View migration history
poetry run alembic history --verbose

# Create a new migration (auto-generate from models)
poetry run alembic revision --autogenerate -m "Description of change"

# Create an empty migration (for manual changes)
poetry run alembic revision -m "Description"

# Apply all pending migrations
poetry run alembic upgrade head

# Apply one migration forward
poetry run alembic upgrade +1

# Rollback one migration
poetry run alembic downgrade -1

# Go to a specific migration
poetry run alembic upgrade <revision_id>

# Rollback to beginning
poetry run alembic downgrade base

# Show SQL without executing (dry run)
poetry run alembic upgrade head --sql
```

## Workflow

### Making a Schema Change

1. **Modify your SQLAlchemy model** in `db/schema.py`
2. **Generate migration**: `poetry run alembic revision --autogenerate -m "description"`
3. **Review the generated file** in `alembic/versions/`
4. **Test the migration**: `poetry run alembic upgrade head`
5. **Test the rollback**: `poetry run alembic downgrade -1`
6. **Re-apply**: `poetry run alembic upgrade head`
7. **Commit to git**: Both the model changes and migration file

### Common Operations in Migrations

```python
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add column
    op.add_column('table_name', sa.Column('column_name', sa.Text()))

    # Drop column
    op.drop_column('table_name', 'column_name')

    # Rename column
    op.alter_column('table_name', 'old_name', new_column_name='new_name')

    # Change column type
    op.alter_column('table_name', 'column_name', type_=sa.Integer())

    # Add index
    op.create_index('ix_table_column', 'table_name', ['column_name'])

    # Drop index
    op.drop_index('ix_table_column')

    # Add foreign key
    op.create_foreign_key('fk_name', 'source_table', 'target_table',
                          ['source_col'], ['target_col'])

    # Drop foreign key
    op.drop_constraint('fk_name', 'table_name', type_='foreignkey')

    # Execute raw SQL
    op.execute("UPDATE table_name SET column = 'value' WHERE condition")

    # Create table
    op.create_table('new_table',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False)
    )

    # Drop table
    op.drop_table('table_name')
```

## Best Practices

### ✅ DO
- Always review auto-generated migrations
- Use descriptive migration messages
- Test migrations before deploying
- Commit migrations to version control
- Back up database before production migrations
- Test that downgrades work

### ❌ DON'T
- Don't edit applied migrations (create new ones instead)
- Don't skip reviewing auto-generated code
- Don't manually modify the database
- Don't forget to handle data migrations when changing columns
- Don't deploy untested migrations to production

## Troubleshooting

### Migration Failed Halfway
```bash
# Check where you are
poetry run alembic current

# If needed, manually tell Alembic the version
poetry run alembic stamp <revision_id>
```

### False Change Detection
Sometimes Alembic detects changes that aren't real:
- Review the generated migration
- Adjust server defaults or types in your models
- Or discard the migration if it's a false positive

### Rollback Fails
- Check the downgrade() function in the migration
- May need to manually fix database state
- Use `alembic stamp` to update the version tracking

## Migration File Structure

```python
"""Short description

Revision ID: abc123def456       ← Unique ID
Revises: previous_rev_id        ← Parent migration
Create Date: 2026-01-21 10:00:00
"""

revision = 'abc123def456'       # This migration's ID
down_revision = 'previous_id'   # Parent (or None if first)
branch_labels = None            # For branching (advanced)
depends_on = None               # Dependencies (advanced)

def upgrade() -> None:
    """Apply changes - move forward."""
    # Your schema changes here
    pass

def downgrade() -> None:
    """Revert changes - move backward."""
    # Opposite of upgrade, in reverse order
    pass
```

## Advanced: Manual Migrations

When auto-generate doesn't work (complex changes, data migrations):

```bash
# Create empty migration
poetry run alembic revision -m "Complex data migration"
```

Then manually write the upgrade() and downgrade() functions.

## Key Concepts

- **Revision**: A single migration file/step
- **Head**: The latest migration in your chain
- **Base**: No migrations applied (empty database)
- **Upgrade**: Move forward through migrations
- **Downgrade**: Roll back migrations
- **Stamp**: Tell Alembic which version the database is at (without running migrations)

## Environment Files

- `alembic.ini`: Main configuration
- `alembic/env.py`: Environment setup (how to connect, what models to use)
- `alembic/versions/`: Migration files
- `.env`: Database credentials (used by our custom env.py)

## Integration with Your Project

This project uses:
- Pydantic Settings for configuration
- Direct schema.py import (bypassing db/__init__.py)
- Explicit .env loading for reliability
- URL-encoded passwords for special characters

See `alembic/env.py` for the custom setup.
