import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# If you have a schema, include it in the WHERE (n.nspname = :schema)
_TYPE_SQL = text("""
SELECT format_type(a.atttypid, a.atttypmod) AS col_type
FROM pg_attribute a
JOIN pg_class c       ON a.attrelid = c.oid
JOIN pg_namespace n   ON c.relnamespace = n.oid
WHERE c.relname = :table
  AND a.attname = :column
  AND a.attnum > 0
  AND NOT a.attisdropped
-- AND n.nspname = :schema
""")

async def _check_vector_length(self, session: AsyncSession) -> None:
    row = await session.execute(_TYPE_SQL, {"table": "document_chunk", "column": "vector"})
    type_str = row.scalar_one_or_none()

    if type_str is None:
        # table or column doesn't exist yet -> nothing to validate
        return

    # Expected formats: "vector(1536)" or "vector"
    if not type_str.startswith("vector"):
        raise Exception(f"Column 'vector' exists but is not pgvector: {type_str}")

    m = re.match(r"vector\((\d+)\)", type_str)
    if not m:
        # no typmod specified; if you require fixed dim, treat as mismatch
        raise Exception(f"Vector column has no fixed dimension: {type_str}")

    db_dim = int(m.group(1))
    if db_dim != VECTOR_LENGTH:
        raise Exception(
            f"VECTOR_LENGTH {VECTOR_LENGTH} != existing vector column dimension {db_dim}. "
            "Cannot change vector size without migrating data."
        )