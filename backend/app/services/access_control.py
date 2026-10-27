from dataclasses import dataclass

from typing import Annotated

from fastapi import Depends

from app.schemas import AuthUser
from app.security.dependencies import CurrentUser, DatabaseConnection


@dataclass(frozen=True)
class DocumentAccess:
    unrestricted: bool = False
    doc_type_ids: frozenset[int] = frozenset()
    group_ids: frozenset[int] = frozenset()
    group_doc_type_pairs: frozenset[tuple[int, int]] = frozenset()

    @property
    def has_access(self) -> bool:
        return self.unrestricted or bool(self.doc_type_ids or self.group_ids)

    def allows(self, doc_type_id: int | None, group_id: int | None) -> bool:
        if self.unrestricted:
            return True
        return (
            doc_type_id is not None and doc_type_id in self.doc_type_ids
        ) or (
            group_id is not None and group_id in self.group_ids
        )

    def groups_for_doc_type(self, doc_type_id: int) -> frozenset[int]:
        return frozenset(
            group_id
            for group_id, parent_type_id in self.group_doc_type_pairs
            if parent_type_id == doc_type_id
        )


def load_document_access(
    current_user: AuthUser,
    connection,
) -> DocumentAccess:
    if current_user.role == "admin":
        return DocumentAccess(unrestricted=True)
    if current_user.permission_group_id is None:
        return DocumentAccess()

    rows = connection.execute(
        """
        SELECT
            groups.is_active,
            scopes.scope_type,
            scopes.doc_type_id,
            scopes.doc_group_id,
            document_groups.doc_type_id AS group_doc_type_id
        FROM rag_client.permission_groups AS groups
        LEFT JOIN rag_client.permission_group_scopes AS scopes
            ON scopes.permission_group_id = groups.id
        LEFT JOIN rag_metadata.document_groups AS document_groups
            ON document_groups.id = scopes.doc_group_id
        WHERE groups.id = %s
        """,
        (current_user.permission_group_id,),
    ).fetchall()

    if not rows or not rows[0]["is_active"]:
        return DocumentAccess()
    if any(row["scope_type"] == "all" for row in rows):
        return DocumentAccess(unrestricted=True)

    return DocumentAccess(
        doc_type_ids=frozenset(
            int(row["doc_type_id"])
            for row in rows
            if row["scope_type"] == "doc_type"
            and row["doc_type_id"] is not None
        ),
        group_ids=frozenset(
            int(row["doc_group_id"])
            for row in rows
            if row["scope_type"] == "doc_group"
            and row["doc_group_id"] is not None
        ),
        group_doc_type_pairs=frozenset(
            (int(row["doc_group_id"]), int(row["group_doc_type_id"]))
            for row in rows
            if row["scope_type"] == "doc_group"
            and row["doc_group_id"] is not None
            and row["group_doc_type_id"] is not None
        ),
    )


def get_document_access(
    current_user: CurrentUser,
    connection: DatabaseConnection,
) -> DocumentAccess:
    return load_document_access(current_user, connection)


DocumentAccessDependency = Annotated[
    DocumentAccess,
    Depends(get_document_access),
]
