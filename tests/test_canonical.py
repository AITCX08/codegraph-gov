from cg_gov.canonical import is_canonical, is_test_path, to_canonical_abs
from cg_gov.config import WORKSPACE_ROOT


def test_canonical_top_level_source():
    assert is_canonical("service-a/src/main.py") is True
    assert is_canonical("service-b/pkg/util.go") is True


def test_worktrees_dropped():
    assert is_canonical(".worktrees/service-a-feature/src/x.ts") is False


def test_ai_mirror_dirs_dropped():
    assert is_canonical(".claude/skills/x/gen.py") is False
    assert is_canonical("service-a/.cursor/copy/App.tsx") is False
    assert is_canonical("service-a/.codex/x.py") is False


def test_vendored_segments_dropped():
    assert is_canonical("service-a/node_modules/lib/index.js") is False
    assert is_canonical("service-a/vendor/dep.go") is False
    assert is_canonical("service-a/dist/bundle.js") is False


def test_tests_dropped():
    assert is_canonical("service-a/tests/test_x.py") is False
    assert is_canonical("service-a/pkg/foo_test.go") is False
    assert is_canonical("service-a/src/x.test.ts") is False


def test_is_test_path():
    assert is_test_path("service-a/tests/helper.py") is True
    assert is_test_path("service-a/__tests__/a.test.ts") is True
    assert is_test_path("service-a/test_x.py") is True
    assert is_test_path("service-a/src/main.py") is False


def test_empty_not_canonical():
    assert is_canonical("") is False


def test_to_canonical_abs_joins_root():
    abs_path = to_canonical_abs("service-a/src/main.py")
    assert abs_path == str(WORKSPACE_ROOT / "service-a/src/main.py")
    assert abs_path.endswith("service-a/src/main.py")
