from __future__ import annotations

import re


class SQLGuard:
    FORBIDDEN_SCHEMAS = {
        "audit",
        "config",
        "information_schema",
        "mart",
        "pg_catalog",
        "public",
        "raw",
        "staging",
    }

    RELATION_PATTERN = re.compile(
        r"\b(?:from|join)\s+("
        r"(?:\"[^\"]+\"|[a-zA-Z_][a-zA-Z0-9_]*)"
        r"(?:\s*\.\s*(?:\"[^\"]+\"|[a-zA-Z_][a-zA-Z0-9_]*))?"
        r")",
        flags=re.IGNORECASE,
    )
    FROM_CLAUSE_PATTERN = re.compile(
        r"\bfrom\b\s+(.*?)(?="
        r"\bwhere\b|\bgroup\s+by\b|\border\s+by\b|\blimit\b|\boffset\b|"
        r"\bunion\b|\bexcept\b|\bintersect\b|\bhaving\b|$"
        r")",
        flags=re.IGNORECASE,
    )
    COMMA_RELATION_PATTERN = re.compile(
        r",\s*("
        r"(?:\"[^\"]+\"|[a-zA-Z_][a-zA-Z0-9_]*)"
        r"(?:\s*\.\s*(?:\"[^\"]+\"|[a-zA-Z_][a-zA-Z0-9_]*))?"
        r")",
        flags=re.IGNORECASE,
    )
    QUALIFIED_SCHEMA_PATTERN = re.compile(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\.",
        flags=re.IGNORECASE,
    )

    def __init__(self, allowed_schemas: set[str] | list[str] | tuple[str, ...] | None = None) -> None:
        schemas = allowed_schemas or {"curated"}
        self.allowed_schemas = {schema.lower().strip() for schema in schemas if schema.strip()}

    def validate(self, sql: str) -> None:
        stripped = self._normalize(sql)
        if not stripped.startswith("select"):
            raise ValueError("Only SELECT statements are allowed")
        if ";" in stripped.rstrip(";"):
            raise ValueError("Only one SQL statement is allowed")

        forbidden_patterns = [
            r"\binsert\b",
            r"\bupdate\b",
            r"\bdelete\b",
            r"\bdrop\b",
            r"\balter\b",
            r"\btruncate\b",
            r"\bcreate\b",
            r"\bgrant\b",
            r"\brevoke\b",
        ]
        for pattern in forbidden_patterns:
            if re.search(pattern, stripped):
                raise ValueError("Forbidden SQL keyword")

        sql_without_literals = self._strip_string_literals(stripped)
        schema_refs = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\.", sql_without_literals))
        blocked_schemas = schema_refs.intersection(self.FORBIDDEN_SCHEMAS)
        if blocked_schemas:
            raise ValueError(f"Schema not allowed: {sorted(blocked_schemas)[0]}")

        for schema in self.QUALIFIED_SCHEMA_PATTERN.findall(sql_without_literals):
            if schema.lower() not in self.allowed_schemas:
                raise ValueError(f"Schema not allowed: {schema.lower()}")

        matched_relations = self._relation_references(sql_without_literals)
        if not matched_relations:
            raise ValueError("SQL must reference at least one allowed relation")

        for relation in matched_relations:
            relation_clean = self._clean_identifier(relation)
            parts = [part for part in relation_clean.split(".") if part]
            if len(parts) != 2:
                raise ValueError(f"Relation must be schema-qualified: {relation_clean}")
            schema = parts[0]
            if schema not in self.allowed_schemas:
                raise ValueError(f"Schema not allowed: {schema}")

    def enforce_limit(self, sql: str, max_rows: int) -> str:
        self.validate(sql)
        stripped = self._compact_original(sql).rstrip(";")
        if re.search(r"\blimit\s+\d+\b", stripped, flags=re.IGNORECASE):
            return stripped
        return f"{stripped} LIMIT {max_rows}"

    @staticmethod
    def _normalize(sql: str) -> str:
        return SQLGuard._compact_original(sql).lower()

    @staticmethod
    def _compact_original(sql: str) -> str:
        without_block_comments = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
        without_line_comments = re.sub(r"--.*?$", " ", without_block_comments, flags=re.MULTILINE)
        return re.sub(r"\s+", " ", without_line_comments).strip()

    @classmethod
    def _relation_references(cls, sql: str) -> list[str]:
        relations = [match.group(1) for match in cls.RELATION_PATTERN.finditer(sql)]
        for clause_match in cls.FROM_CLAUSE_PATTERN.finditer(sql):
            relations.extend(match.group(1) for match in cls.COMMA_RELATION_PATTERN.finditer(clause_match.group(1)))
        return relations

    @staticmethod
    def _clean_identifier(identifier: str) -> str:
        return re.sub(r'\s+', "", identifier.strip().rstrip(";")).replace('"', "").lower()

    @staticmethod
    def _strip_string_literals(sql: str) -> str:
        return re.sub(r"'(?:''|[^'])*'", "''", sql)
