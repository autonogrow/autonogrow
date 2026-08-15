import ast
import re
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "alembic" / "versions"
MIGRATION_FILES = tuple(
    sorted(
        path
        for path in VERSIONS.glob("*.py")
        if path.name.startswith(("20260806_11", "20260806_12", "20260806_13"))
        or any(path.name.startswith(f"20260814_{revision}") for revision in range(14, 20))
    )
)
EXPLICIT_IDENTIFIER = re.compile(r"(?:pk|fk|uq|ck|ix)_[A-Za-z0-9_]+\Z")
POSTGRESQL_IDENTIFIER_LIMIT = 63
SOURCE_PROPOSAL_FK = "fk_instagram_contents_source_proposal"
LEGACY_TOO_LONG_FK = "fk_instagram_contents_source_proposal_id_social_content_proposals"


def explicit_identifiers(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    joined_constants = {
        id(part)
        for joined in ast.walk(tree)
        if isinstance(joined, ast.JoinedStr)
        for part in joined.values
        if isinstance(part, ast.Constant)
    }
    identifiers = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in joined_constants
        and EXPLICIT_IDENTIFIER.fullmatch(node.value)
    ]
    identifiers.extend(dynamic_identifiers(tree))
    return sorted(identifiers)


def _render_f_string(node: ast.JoinedStr, variable: str, value: str) -> str | None:
    rendered: list[str] = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            rendered.append(part.value)
        elif (
            isinstance(part, ast.FormattedValue)
            and isinstance(part.value, ast.Name)
            and part.value.id == variable
        ):
            rendered.append(value)
        else:
            return None
    return "".join(rendered)


def dynamic_identifiers(tree: ast.AST) -> list[tuple[int, str]]:
    identifiers: list[tuple[int, str]] = []
    for loop in (node for node in ast.walk(tree) if isinstance(node, ast.For)):
        if not isinstance(loop.target, ast.Name) or not isinstance(
            loop.iter, (ast.List, ast.Set, ast.Tuple)
        ):
            continue
        values = [
            item.value
            for item in loop.iter.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        if len(values) != len(loop.iter.elts):
            continue
        for joined in (node for node in ast.walk(loop) if isinstance(node, ast.JoinedStr)):
            for value in values:
                rendered = _render_f_string(joined, loop.target.id, value)
                if rendered and EXPLICIT_IDENTIFIER.fullmatch(rendered):
                    identifiers.append((joined.lineno, rendered))
    return identifiers


def unresolved_identifier_f_strings(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    resolved_lines = {line for line, _identifier in dynamic_identifiers(tree)}
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        and node.lineno not in resolved_lines
        and "".join(
            str(part.value)
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ).startswith(("pk_", "fk_", "uq_", "ck_", "ix_"))
    )


def test_all_explicit_migration_identifiers_11_to_19_fit_postgresql() -> None:
    assert len(MIGRATION_FILES) == 9
    violations = [
        (path.name, line, identifier, len(identifier))
        for path in MIGRATION_FILES
        for line, identifier in explicit_identifiers(path)
        if len(identifier) > POSTGRESQL_IDENTIFIER_LIMIT
    ]

    assert violations == []
    assert {
        path.name: unresolved_identifier_f_strings(path)
        for path in MIGRATION_FILES
        if unresolved_identifier_f_strings(path)
    } == {}


def test_migration_19_upgrade_and_downgrade_use_the_same_short_fk_name() -> None:
    migration = next(path for path in MIGRATION_FILES if path.name.startswith("20260814_19"))
    source = migration.read_text(encoding="utf-8")
    upgrade_source, downgrade_source = source.split("def downgrade() -> None:", maxsplit=1)

    assert upgrade_source.count(f'"{SOURCE_PROPOSAL_FK}"') == 1
    assert downgrade_source.count(f'"{SOURCE_PROPOSAL_FK}"') == 1
    assert LEGACY_TOO_LONG_FK not in source


def test_migration_19_fk_name_compiles_with_postgresql_dialect() -> None:
    metadata = sa.MetaData()
    sa.Table(
        "social_content_proposals",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    contents = sa.Table(
        "instagram_contents",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_proposal_id", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"],
            ["social_content_proposals.id"],
            name=SOURCE_PROPOSAL_FK,
            ondelete="SET NULL",
        ),
    )

    ddl = str(CreateTable(contents).compile(dialect=postgresql.dialect()))

    assert f"CONSTRAINT {SOURCE_PROPOSAL_FK}" in ddl
