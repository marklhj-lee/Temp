# open_webui/retrieval/vector/dbs/pgvector.py
# Async rewrite with minimal surface change

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    Text,
    cast,
    column,
    select,
    text,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import declarative_base

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pgvector.sqlalchemy import Vector

from open_webui.retrieval.vector.main import VectorItem, SearchResult, GetResult
from open_webui.config import PGVECTOR_DB_URL, PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

VECTOR_LENGTH = PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH
Base = declarative_base()


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    id = Column(Text, primary_key=True)
    vector = Column(Vector(dim=VECTOR_LENGTH), nullable=True)
    collection_name = Column(Text, nullable=False)
    text = Column(Text, nullable=True)
    vmetadata = Column(MutableDict.as_mutable(JSONB), nullable=True)


def _to_asyncpg_url(url: str) -> str:
    # Normalize to async driver
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url  # assume caller provided a valid async URL


class PgvectorClient:
    """
    Async pgvector client with minimal change to the original sync API.
    - Construct synchronously (safe for your current factory).
    - Call `await init()` once during app startup (lifespan).
    """

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        engine: Optional[AsyncEngine] = None,
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine
        self._owns_engine = False

    async def init(self) -> None:
        """
        Initialize extension, tables, and indexes.
        Call this once on startup (e.g., in FastAPI lifespan).
        """
        # Resolve session factory / engine
        if not self._session_factory:
            if PGVECTOR_DB_URL:
                async_url = _to_asyncpg_url(PGVECTOR_DB_URL)
                self._engine = create_async_engine(async_url, pool_pre_ping=True)
                self._session_factory = async_sessionmaker(
                    bind=self._engine, expire_on_commit=False, class_=AsyncSession
                )
                self._owns_engine = True
            else:
                # Reuse app async DB
                # Adjust import path if your async_db module lives elsewhere
                from open_webui.internal.async_db import AsyncSessionLocal  # type: ignore

                self._session_factory = AsyncSessionLocal
                # Try to get an engine reference if available
                self._engine = getattr(self._session_factory, "bind", None)

        assert self._session_factory is not None, "Async session factory not configured"

        # Ensure pgvector extension
        async with self._session_factory() as session:
            try:
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("Failed to ensure pgvector extension.")
                raise

        # Create tables with a sync metadata call on the async engine
        engine: AsyncEngine = self._engine or self._session_factory.kw["bind"]  # type: ignore
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Validate vector length + create indexes
        async with self._session_factory() as session:
            try:
                await self._check_vector_length(session)
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_document_chunk_vector "
                        "ON document_chunk USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);"
                    )
                )
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_document_chunk_collection_name "
                        "ON document_chunk (collection_name);"
                    )
                )
                await session.commit()
                log.info("Pgvector async initialization complete.")
            except Exception:
                await session.rollback()
                log.exception("Error during pgvector async initialization.")
                raise

    async def _check_vector_length(self, session: AsyncSession) -> None:
        """
        Ensure the stored vector column dimension matches VECTOR_LENGTH.
        """
        metadata = MetaData()

        def _reflect(bind):
            metadata.reflect(bind, only=["document_chunk"])

        try:
            await session.run_sync(_reflect)
        except NoSuchTableError:
            return

        table: Optional[Table] = metadata.tables.get("document_chunk")
        if not table:
            return

        if "vector" not in table.c:
            raise Exception("The 'vector' column does not exist in 'document_chunk'.")

        vcol = table.c["vector"]
        vtype = vcol.type
        if not isinstance(vtype, Vector):
            raise Exception("The 'vector' column exists but is not type 'Vector'.")

        if vtype.dim != VECTOR_LENGTH:
            raise Exception(
                f"VECTOR_LENGTH {VECTOR_LENGTH} does not match existing vector column dimension {vtype.dim}. "
                "Cannot change vector size after initialization without migrating the data."
            )

    @staticmethod
    def _adjust_vector_length(vec: List[float]) -> List[float]:
        n = len(vec)
        if n < VECTOR_LENGTH:
            return vec + [0.0] * (VECTOR_LENGTH - n)
        if n > VECTOR_LENGTH:
            raise Exception(
                f"Vector length {n} not supported. Max length must be <= {VECTOR_LENGTH}"
            )
        return vec

    # ---------------- Public API (async) ----------------

    async def insert(self, collection_name: str, items: List[VectorItem]) -> None:
        async with self._session_factory() as session:
            try:
                objs = []
                for it in items:
                    objs.append(
                        DocumentChunk(
                            id=it["id"],
                            vector=self._adjust_vector_length(it["vector"]),
                            collection_name=collection_name,
                            text=it["text"],
                            vmetadata=it["metadata"],
                        )
                    )
                session.add_all(objs)
                await session.commit()
                log.info("Inserted %d items into '%s'.", len(objs), collection_name)
            except Exception:
                await session.rollback()
                log.exception("Error during insert")
                raise

    async def upsert(self, collection_name: str, items: List[VectorItem]) -> None:
        async with self._session_factory() as session:
            try:
                for it in items:
                    existing = await session.get(DocumentChunk, it["id"])
                    vec = self._adjust_vector_length(it["vector"])
                    if existing:
                        existing.vector = vec
                        existing.text = it["text"]
                        existing.vmetadata = it["metadata"]
                        existing.collection_name = collection_name
                    else:
                        session.add(
                            DocumentChunk(
                                id=it["id"],
                                vector=vec,
                                collection_name=collection_name,
                                text=it["text"],
                                vmetadata=it["metadata"],
                            )
                        )
                await session.commit()
                log.info("Upserted %d items into '%s'.", len(items), collection_name)
            except Exception:
                await session.rollback()
                log.exception("Error during upsert")
                raise

    async def search(
        self,
        collection_name: str,
        vectors: List[List[float]],
        limit: Optional[int] = None,
    ) -> Optional[SearchResult]:
        if not vectors:
            return None

        vectors = [self._adjust_vector_length(v) for v in vectors]
        n_q = len(vectors)

        def vex(v):
            return cast(array(v), Vector(VECTOR_LENGTH))

        qid_col = column("qid", Integer)
        qvec_col = column("q_vector", Vector(VECTOR_LENGTH))
        qvecs = values(qid_col, qvec_col).data(
            [(i, vex(v)) for i, v in enumerate(vectors)]
        ).alias("query_vectors")

        subq = (
            select(
                DocumentChunk.id,
                DocumentChunk.text,
                DocumentChunk.vmetadata,
                (DocumentChunk.vector.cosine_distance(qvecs.c.q_vector)).label(
                    "distance"
                ),
            )
            .where(DocumentChunk.collection_name == collection_name)
            .order_by(DocumentChunk.vector.cosine_distance(qvecs.c.q_vector))
        )
        if limit is not None:
            subq = subq.limit(limit)
        subq = subq.lateral("result")

        stmt = (
            select(
                qvecs.c.qid,
                subq.c.id,
                subq.c.text,
                subq.c.vmetadata,
                subq.c.distance,
            )
            .select_from(qvecs)
            .join(subq, text("TRUE"))
            .order_by(qvecs.c.qid, subq.c.distance)
        )

        async with self._session_factory() as session:
            try:
                res = await session.execute(stmt)
                rows = res.all()

                ids = [[] for _ in range(n_q)]
                distances = [[] for _ in range(n_q)]
                documents = [[] for _ in range(n_q)]
                metadatas = [[] for _ in range(n_q)]

                if not rows:
                    return SearchResult(
                        ids=ids, distances=distances, documents=documents, metadatas=metadatas
                    )

                for r in rows:
                    qid = int(r.qid)
                    ids[qid].append(r.id)
                    # convert cosine distance -> similarity score [0,1]
                    distances[qid].append((2.0 - r.distance) / 2.0)
                    documents[qid].append(r.text)
                    metadatas[qid].append(r.vmetadata)

                return SearchResult(
                    ids=ids, distances=distances, documents=documents, metadatas=metadatas
                )
            except Exception:
                log.exception("Error during search")
                return None

    async def query(
        self, collection_name: str, filter: Dict[str, Any], limit: Optional[int] = None
    ) -> Optional[GetResult]:
        async with self._session_factory() as session:
            try:
                q = select(DocumentChunk).where(
                    DocumentChunk.collection_name == collection_name
                )
                for k, v in filter.items():
                    q = q.where(DocumentChunk.vmetadata[k].astext == str(v))
                if limit is not None:
                    q = q.limit(limit)

                res = await session.execute(q)
                rows = [row[0] for row in res.fetchall()]
                if not rows:
                    return None

                ids = [[r.id for r in rows]]
                documents = [[r.text for r in rows]]
                metadatas = [[r.vmetadata for r in rows]]
                return GetResult(ids=ids, documents=documents, metadatas=metadatas)
            except Exception:
                log.exception("Error during query")
                return None

    async def get(
        self, collection_name: str, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        async with self._session_factory() as session:
            try:
                q = select(DocumentChunk).where(
                    DocumentChunk.collection_name == collection_name
                )
                if limit is not None:
                    q = q.limit(limit)

                res = await session.execute(q)
                rows = [row[0] for row in res.fetchall()]
                if not rows:
                    return None

                ids = [[r.id for r in rows]]
                documents = [[r.text for r in rows]]
                metadatas = [[r.vmetadata for r in rows]]
                return GetResult(ids=ids, documents=documents, metadatas=metadatas)
            except Exception:
                log.exception("Error during get")
                return None

    async def delete(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self._session_factory() as session:
            try:
                # Load IDs first (keeps logic close to original)
                q = select(DocumentChunk).where(
                    DocumentChunk.collection_name == collection_name
                )
                if ids:
                    q = q.where(DocumentChunk.id.in_(ids))
                if filter:
                    for k, v in filter.items():
                        q = q.where(DocumentChunk.vmetadata[k].astext == str(v))

                res = await session.execute(q)
                rows = [row[0] for row in res.fetchall()]
                for row in rows:
                    await session.delete(row)
                await session.commit()
                log.info("Deleted %d items from '%s'.", len(rows), collection_name)
            except Exception:
                await session.rollback()
                log.exception("Error during delete")
                raise

    async def reset(self) -> None:
        async with self._session_factory() as session:
            try:
                res = await session.execute(select(DocumentChunk))
                rows = [row[0] for row in res.fetchall()]
                for row in rows:
                    await session.delete(row)
                await session.commit()
                log.info("Reset complete. Deleted %d rows.", len(rows))
            except Exception:
                await session.rollback()
                log.exception("Error during reset")
                raise

    async def has_collection(self, collection_name: str) -> bool:
        async with self._session_factory() as session:
            try:
                res = await session.execute(
                    select(DocumentChunk.id)
                    .where(DocumentChunk.collection_name == collection_name)
                    .limit(1)
                )
                return res.first() is not None
            except Exception:
                log.exception("Error checking collection existence")
                return False

    async def delete_collection(self, collection_name: str) -> None:
        await self.delete(collection_name)
        log.info("Collection '%s' deleted.", collection_name)

    async def close(self) -> None:
        if self._owns_engine and self._engine is not None:
            await self._engine.dispose()
