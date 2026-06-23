"""Perception core: SQL schema-change parser (pure, no network).

The testable heart of perception. Given the previous and new content of one
`.sql` file, return the *added* schema objects (new tables, new columns).
Regex-based on purpose: a full SQL grammar parser is overkill and brittle for
messy, multi-dialect migration files. We only need to recognise three shapes:

  1. a `CREATE TABLE <name>` that did not exist before          -> table added
  2. an `ALTER TABLE <t> ADD [COLUMN] <col> <type>` that is new  -> column added
  3. a column line inside a CREATE TABLE body that the old def
     for that same table did not have                           -> column added

Tolerances (intentional, see tests):
  - case-insensitive keywords (`create table` == `CREATE TABLE`)
  - backtick / double-quote / bracket-quoted identifiers (`tbl`, "tbl", [tbl])
  - multi-line CREATE bodies, trailing commas, inline COMMENTs
  - statement splitting, comment stripping, comma splitting and body extraction
    are ALL string-literal-aware: a `;`, `,`, `--` or `(`/`)` INSIDE a quoted
    `COMMENT '...'` / `DEFAULT '...'` does NOT fracture the statement or column.
    (e.g. a `;` inside `COMMENT 'a; b'` must not drop the columns after it.)
  - inside parens (`DECIMAL(10,2)`, `ENUM('a','b')`) commas do NOT split.
  - a trailing `) ENGINE=.. PARTITION BY RANGE (...)` after the column list is
    NOT swallowed into the body (balanced-paren scan stops at the column-list
    close), so partitions never mint phantom columns.
  - a single ALTER with MULTIPLE actions (`ADD a INT, ADD b INT, DROP c`) is
    split on top-level commas; every ADD column is detected, not just the first.

KNOWN LIMITATIONS (first version detects ADDED only):
  - DROP TABLE / DROP COLUMN are detected best-effort as change_type "removed",
    but MODIFY / CHANGE / RENAME / type-changes are NOT emitted (no "modified").
    A multi-DROP single ALTER (`DROP a, DROP b`) flags only the first DROP.
  - column-type extraction is a coarse first token after the name; complex
    types (e.g. `DECIMAL(10,2)`) keep their parenthesised part, but constraint
    noise (NOT NULL, DEFAULT ...) is stripped.
  - string-literal awareness assumes NO backslash-escaped quote inside a literal:
    a `'it\\'s'` style escape would mis-close.
  - Postgres-style `ADD COLUMN IF NOT EXISTS <c>` is NOT understood (`IF` would
    be read as the column name); MySQL-centric for the first increment.
  - this module is content-only; baseline/test FILE filtering is the
    orchestrator's job (it never sees file names).

Event shape (list of dicts):
  {"change_type": "added"|"removed", "object": "table"|"column",
   "table": <table>, ["field": <col>, "type": <type>]}
The orchestrator later tags each event with {repo, file, commit_sha}.
"""
import re

# --- identifier helpers ------------------------------------------------------
# An identifier may be bare, `backtick`, "double", or [bracket] quoted.
_IDENT = r'(?:`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][\w$]*)'


def _unquote(ident: str) -> str:
    """Strip one layer of backtick / double-quote / bracket quoting."""
    s = ident.strip()
    if len(s) >= 2 and s[0] in "`\"" and s[-1] == s[0]:
        return s[1:-1]
    if len(s) >= 2 and s[0] == "[" and s[-1] == "]":
        return s[1:-1]
    return s


# --- statement-level regexes -------------------------------------------------
# CREATE TABLE [IF NOT EXISTS] <name> ( <body> )  -- body captured non-greedily
# up to the matching close paren at the same nesting is hard with pure regex, so
# we capture to the LAST ')' before a ';' or end (good enough for one statement
# per match because we split on ';' first).
_CREATE_TABLE_NAME = re.compile(
    r'\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(' + _IDENT + r')',
    re.IGNORECASE)

# ALTER TABLE <t> <rest> -- the rest may hold MULTIPLE comma-separated actions
# (ADD a INT, ADD b INT, DROP c). We grab <t> + the whole tail, then split the
# tail on TOP-LEVEL commas (string/paren-aware) and scan each segment for ADD.
_ALTER_TABLE_HEAD = re.compile(
    r'\bALTER\s+TABLE\s+(' + _IDENT + r')\s+(.+)',
    re.IGNORECASE | re.DOTALL)

# One ADD action: ADD [COLUMN] <ident> <type...> (type runs to the segment end,
# since the segment was already split off at the top-level comma).
_ADD_ACTION = re.compile(
    r'^\s*ADD\s+(?:COLUMN\s+)?(' + _IDENT + r')\s+(.+)',
    re.IGNORECASE | re.DOTALL)

_ALTER_DROP_COL = re.compile(
    r'\bALTER\s+TABLE\s+(' + _IDENT + r')\s+DROP\s+(?:COLUMN\s+)?'
    r'(' + _IDENT + r')',
    re.IGNORECASE)

_DROP_TABLE = re.compile(
    r'\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(' + _IDENT + r')',
    re.IGNORECASE)

# A column definition line inside a CREATE body: <ident> <type...>. We reject
# lines that start with a table-level constraint keyword (PRIMARY/KEY/UNIQUE/...)
# so we don't mistake an index clause for a column.
_CONSTRAINT_LEADERS = re.compile(
    r'^\s*(PRIMARY\s+KEY|UNIQUE|KEY|INDEX|CONSTRAINT|FOREIGN\s+KEY|CHECK|FULLTEXT|SPATIAL)\b',
    re.IGNORECASE)

# SQL string-literal quote chars. A '"' is dialect-ambiguous (identifier quote
# in standard/Postgres, string in some MySQL modes) but treating it as a literal
# for the SCAN only affects where we stop tracking parens/commas/;/-- -- an
# identifier never legitimately contains an unescaped '(' or top-level ',' anyway.
_QUOTES = "'\""


def _strip_comments(sql: str) -> str:
    """Strip `-- line` and `/* block */` comments -- but NOT a `--` or `/*` that
    lives inside a string literal (e.g. `COMMENT 'see -- note'`). A regex pass
    would wrongly eat those, truncating the column; this single string-aware
    scan only treats comment markers as comments when outside a quoted literal.
    """
    out, i, n, quote = [], 0, len(sql), ""
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in _QUOTES:
            quote = ch
            out.append(ch)
            i += 1
        elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)            # skip to end of line
            i = n if j == -1 else j
        elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)        # skip to end of block
            out.append(" ")
            i = n if j == -1 else j + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_statements(sql: str):
    """Split on ';' that terminate a statement -- string-literal-aware so a ';'
    inside a literal (e.g. `COMMENT 'a; b'`) does NOT fracture the CREATE TABLE
    mid-body and silently drop every column after it. Real-world schema commonly
    embeds ';' in COMMENT/DEFAULT literals, so a naive split() loses columns.
    """
    stmts, cur, quote = [], [], ""
    for ch in sql:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in _QUOTES:
            quote = ch
            cur.append(ch)
        elif ch == ";":
            stmts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        stmts.append("".join(cur))
    return [s for s in stmts if s.strip()]


def _extract_create_body(stmt: str):
    """Return (table_name, body_text) for a CREATE TABLE statement, else None.

    body_text is the column-list parenthesised group -- found by BALANCED-paren
    scanning from the first '(' to its MATCHING ')', skipping parens that live
    inside string literals (e.g. a '(' inside a COMMENT '...'). This deliberately
    stops at the column-list close paren so a trailing `ENGINE=.. PARTITION BY
    RANGE (...)` clause is NOT swallowed into the body (which would mint phantom
    PARTITION/p2026xx 'columns'). rfind(')') -- the old approach -- grabbed the
    last partition's ')' and was the root cause.
    """
    m = _CREATE_TABLE_NAME.search(stmt)
    if not m:
        return None
    open_i = stmt.find("(", m.end())
    if open_i == -1:
        return _unquote(m.group(1)), ""  # CREATE TABLE ... AS / no body
    depth, quote = 0, ""
    for i in range(open_i, len(stmt)):
        ch = stmt[i]
        if quote:
            if ch == quote:
                quote = ""        # close the literal (POC: no backslash-escape)
            continue
        if ch in _QUOTES:
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:        # matching close of the column-list group
                return _unquote(m.group(1)), stmt[open_i + 1:i]
    # unbalanced (truncated DDL): fall back to from-open-to-end
    return _unquote(m.group(1)), stmt[open_i + 1:]


def _split_top_level_commas(text: str):
    """Split on commas that are NOT inside parentheses AND NOT inside a string
    literal. Keeps `DECIMAL(10,2)`, `ENUM('a','b')`, and a quoted
    `COMMENT 'sub-scores, raw, weights'` intact (commas inside parens/quotes do
    not split). Returns stripped non-empty segments.

    Shared by the CREATE-body column splitter and the multi-action ALTER tail
    splitter so both get identical string/paren awareness.
    """
    segs, depth, quote, cur = [], 0, "", []
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in _QUOTES:
            quote = ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            segs.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def _split_body_columns(body: str):
    """Split a CREATE body into top-level column/constraint clauses."""
    return _split_top_level_commas(body)


def _column_from_clause(clause: str):
    """Parse one CREATE-body clause into (col_name, type) or None if it is a
    table-level constraint (PRIMARY KEY / INDEX / ...) rather than a column."""
    if _CONSTRAINT_LEADERS.match(clause):
        return None
    m = re.match(r'\s*(' + _IDENT + r')\s+(.+)', clause, re.DOTALL)
    if not m:
        return None
    name = _unquote(m.group(1))
    col_type = _normalize_type(m.group(2))
    if not col_type:
        return None
    return name, col_type


def _normalize_type(raw: str) -> str:
    """Coarse type extraction: the leading type token (+ its (...) size spec).

    Strips trailing constraint noise (NOT NULL, DEFAULT ..., COMMENT ...). Keeps
    `VARCHAR(255)` / `DECIMAL(10,2)` intact. POC-grade, not a full type parser.
    """
    raw = raw.strip()
    # type is the first token, optionally followed by a balanced (...) spec
    m = re.match(r'([A-Za-z_]\w*)\s*(\([^)]*\))?', raw)
    if not m:
        return raw.split()[0] if raw.split() else ""
    base = m.group(1)
    spec = m.group(2) or ""
    return (base + spec).strip()


def _tables(sql: str) -> dict:
    """Map of table_name(lower) -> set(column_name(lower)) from CREATE bodies.

    Used to diff old vs new CREATE definitions. Original-case names are kept in
    a parallel return so we can emit human-readable names.
    """
    cols_by_table, case_by_table = {}, {}
    for stmt in _split_statements(_strip_comments(sql)):
        parsed = _extract_create_body(stmt)
        if not parsed:
            continue
        tname, body = parsed
        key = tname.lower()
        case_by_table[key] = tname
        cols = {}
        for clause in _split_body_columns(body):
            col = _column_from_clause(clause)
            if col:
                cols[col[0].lower()] = (col[0], col[1])
        cols_by_table[key] = cols
    return cols_by_table, case_by_table


def parse_schema_changes(old_sql: str, new_sql: str) -> list[dict]:
    """Return ADDED (and best-effort REMOVED) schema events from old->new SQL.

    Detects, comparing the two file contents:
      - a new CREATE TABLE (table absent in old)              -> table added
      - a new column inside an existing-or-new CREATE body    -> column added
      - a new `ALTER TABLE .. ADD [COLUMN] <c> <type>`        -> column added
    Best-effort removed (known-limitation, see module docstring):
      - DROP TABLE present only in new                        -> table removed
      - DROP COLUMN / ALTER DROP present only in new          -> column removed

    Pure function, deterministic, no I/O. old_sql may be "" (cold/new file).
    Events are de-duplicated; order is stable (tables before their columns,
    then alters in source order).
    """
    old_sql = old_sql or ""
    new_sql = new_sql or ""
    events: list[dict] = []
    seen: set = set()

    def _add(ev: dict):
        sig = (ev["change_type"], ev["object"], ev["table"].lower(),
               ev.get("field", "").lower())
        if sig not in seen:
            seen.add(sig)
            events.append(ev)

    old_tables, _ = _tables(old_sql)
    new_tables, new_case = _tables(new_sql)

    # 1 + 2: new tables and new columns inside CREATE bodies
    for tkey, new_cols in new_tables.items():
        disp_table = new_case[tkey]
        if tkey not in old_tables:
            _add({"change_type": "added", "object": "table", "table": disp_table})
            for _ck, (cname, ctype) in new_cols.items():
                _add({"change_type": "added", "object": "column",
                      "table": disp_table, "field": cname, "type": ctype})
        else:
            old_cols = old_tables[tkey]
            for ck, (cname, ctype) in new_cols.items():
                if ck not in old_cols:
                    _add({"change_type": "added", "object": "column",
                          "table": disp_table, "field": cname, "type": ctype})

    # 3: ALTER TABLE ... ADD [COLUMN], counting only those new to `new_sql`.
    # A single ALTER may carry MULTIPLE comma-separated actions
    # (`ADD a INT, ADD b INT, DROP c`), so split the tail on top-level commas and
    # scan each segment for an ADD. Constraint ADDs (`ADD CONSTRAINT/INDEX/
    # UNIQUE KEY/PRIMARY KEY/..`) are rejected -- the keyword would otherwise be
    # read as the column name.
    old_clean = _strip_comments(old_sql)
    new_clean = _strip_comments(new_sql)

    def _alter_added_columns(clean: str):
        for stmt in _split_statements(clean):
            head = _ALTER_TABLE_HEAD.search(stmt)
            if not head:
                continue
            table, tail = head.group(1), head.group(2)
            for seg in _split_top_level_commas(tail):
                m = _ADD_ACTION.match(seg)
                if not m:
                    continue                 # DROP/MODIFY/CHANGE segment, skip
                col, coltype = m.group(1), m.group(2)
                # constraint keyword as the "column" -> not a column add
                if _CONSTRAINT_LEADERS.match(f"{col} {coltype}"):
                    continue
                yield table, col, coltype

    old_alter_adds = {
        (_unquote(t).lower(), _unquote(c).lower())
        for t, c, _ty in _alter_added_columns(old_clean)
    }
    for t, c, ty in _alter_added_columns(new_clean):
        tkey, ckey = _unquote(t).lower(), _unquote(c).lower()
        if (tkey, ckey) in old_alter_adds:
            continue
        _add({"change_type": "added", "object": "column",
              "table": _unquote(t), "field": _unquote(c),
              "type": _normalize_type(ty)})

    # best-effort removed: DROP TABLE / DROP COLUMN new to new_sql
    old_drop_tables = {_unquote(t).lower() for t in _DROP_TABLE.findall(old_clean)}
    for t in _DROP_TABLE.findall(new_clean):
        if _unquote(t).lower() in old_drop_tables:
            continue
        _add({"change_type": "removed", "object": "table", "table": _unquote(t)})

    old_drop_cols = {
        (_unquote(t).lower(), _unquote(c).lower())
        for t, c in _ALTER_DROP_COL.findall(old_clean)
    }
    for t, c in _ALTER_DROP_COL.findall(new_clean):
        if (_unquote(t).lower(), _unquote(c).lower()) in old_drop_cols:
            continue
        _add({"change_type": "removed", "object": "column",
              "table": _unquote(t), "field": _unquote(c)})

    return events
