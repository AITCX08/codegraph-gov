from cg_gov.perception.parser import parse_schema_changes


def test_new_table_added():
    new = "CREATE TABLE foo (id INT, name VARCHAR(50));"
    events = parse_schema_changes("", new)
    seen = {(e["change_type"], e["object"], e.get("field")) for e in events}
    assert ("added", "table", None) in seen
    assert ("added", "column", "id") in seen
    assert ("added", "column", "name") in seen


def test_added_column_via_alter():
    old = "CREATE TABLE foo (id INT);"
    new = old + "\nALTER TABLE foo ADD COLUMN created_at DATETIME;"
    events = parse_schema_changes(old, new)
    cols = {e["field"] for e in events
            if e["object"] == "column" and e["change_type"] == "added"}
    assert "created_at" in cols


def test_added_column_in_create_body():
    old = "CREATE TABLE foo (id INT);"
    new = "CREATE TABLE foo (id INT, email VARCHAR(120));"
    events = parse_schema_changes(old, new)
    cols = {e["field"] for e in events if e["object"] == "column"}
    assert cols == {"email"}


def test_no_change_no_events():
    sql = "CREATE TABLE foo (id INT);"
    assert parse_schema_changes(sql, sql) == []


def test_semicolon_inside_comment_does_not_split():
    # a ';' inside a quoted COMMENT must not truncate the column list
    new = "CREATE TABLE foo (id INT COMMENT 'a; b', tail VARCHAR(10));"
    events = parse_schema_changes("", new)
    cols = {e["field"] for e in events if e["object"] == "column"}
    assert "tail" in cols  # the column after the comment survived


def test_drop_table_removed():
    events = parse_schema_changes("", "DROP TABLE foo;")
    assert any(e["change_type"] == "removed" and e["object"] == "table"
               for e in events)


def test_multi_action_alter():
    new = "ALTER TABLE foo ADD a INT, ADD b INT;"
    events = parse_schema_changes("", new)
    cols = {e["field"] for e in events if e["object"] == "column"}
    assert {"a", "b"} <= cols
