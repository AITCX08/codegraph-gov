import argparse
import json
import os
import sys
from .index import build_index, DATA_DIR
from .search import semantic_search
from .fts import fts_search
from .embed import LocalFastembed
from .reuse import reuse_candidates
from .scan import scan_duplicates, scan_orphans
from .docgen import generate


def _fmt(h):
    loc = f'{h["abs_path"]}:{h["start_line"]}'
    return f'  [{h.get("score", 0):<8.3f}] {h["kind"]:<10} {h["name"]:<32} {loc}'


def _print_index_banner():
    """Make index coverage visible: warn loudly if reasoning over a partial index."""
    info_path = DATA_DIR / "index_info.json"
    if not info_path.exists():
        print("# (no index_info.json - run `python -m cg_gov.cli index` first)")
        return
    info = json.loads(info_path.read_text())
    count, limit = info.get("count"), info.get("limit")
    if limit is not None:
        print(f"# WARNING PARTIAL INDEX: {count} symbols (built with --limit {limit}). "
              f"Rebuild full (python -m cg_gov.cli index) before drawing gate conclusions.")
    else:
        print(f"# index: {count} symbols (full)")


def cmd_index(args):
    build_index(limit=args.limit)


def cmd_search(args):
    _print_index_banner()
    print(f"# semantic (local) for: {args.intent}")
    for h in semantic_search(args.intent, LocalFastembed(), k=args.k):
        print(_fmt(h))


def cmd_gate(args):
    """Three-way compare (FTS vs semantic) on one probe intent."""
    _print_index_banner()
    print(f"## probe intent: {args.intent}")
    print("### FTS baseline")
    fts = fts_search(args.intent, limit=args.k)
    print("  (empty)" if not fts else "")
    for h in fts:
        print(f'  {h["kind"]:<10} {h["name"]:<32} {h["file_path"]}')
    print("### semantic (local)")
    for h in semantic_search(args.intent, LocalFastembed(), k=args.k):
        print(_fmt(h))


def cmd_reuse(args):
    _print_index_banner()
    res = reuse_candidates(args.intent, k=args.k)
    print(f"## reuse candidates for: {args.intent}")
    for c in res["candidates"]:
        src = "+".join(c["sources"])
        loc = f'{c["abs_path"]}:{c["start_line"]}'
        print(f'  [rrf {c["rrf"]:<8.5f}][{src:<13}][callers {c["callers"]:>3}] '
              f'{c["kind"]:<10} {c["name"]:<28} {loc}')
    print(f"## service distribution: {res['service_distribution']}")


def cmd_scan(args):
    """Sweep the canonical index for duplicate clusters and/or orphans."""
    _print_index_banner()
    # default to --dups if neither flag is given
    do_dups = args.dups or not args.orphans
    do_orphans = args.orphans
    if do_dups:
        clusters = scan_duplicates(threshold=args.threshold,
                                   reimpl_only=args.reimpl_only)
        shown = clusters[:args.limit]
        reimpl = sum(1 for c in clusters if c["category"] == "reimplementation")
        print(f"## duplicate clusters (threshold {args.threshold}): "
              f"{len(clusters)} found ({reimpl} reimplementation, "
              f"{len(clusters) - reimpl} name-collision), showing {len(shown)}")
        for c in shown:
            sim = "n/a" if c["avg_sim"] is None else f'{c["avg_sim"]:.3f}'
            print(f'  [{c["category"]:<15}][size {c["size"]}]'
                  f'[avg_sim {sim}][names {c["distinct_names"]}]')
            for m in c["members"]:
                loc = f'{m["abs_path"]}:{m["start_line"]}'
                print(f'      {m["kind"]:<10} {m["name"]:<28} {loc}')
    if do_orphans:
        orphans = scan_orphans(limit=args.limit)
        print("## orphans: HEURISTIC + NOISY -- 0 internal callers != dead code.")
        print("## may be HTTP routes, reflection/dynamic-dispatch targets, "
              "cross-service exported API, or entrypoints. Human review required.")
        print(f"## {len(orphans)} candidate(s) (capped):")
        for o in orphans:
            loc = f'{o["abs_path"]}:{o["start_line"]}'
            print(f'  [callers {o["callers"]}] {o["kind"]:<10} {o["name"]:<28} {loc}')


def cmd_gen_docs(args):
    """Generate JSON源 + rendered markdown interface catalog from codegraph."""
    _print_index_banner()
    res = generate()
    print(f"## wrote JSON源:   {res['source_path']}")
    print(f"## wrote markdown: {res['markdown_path']} "
          f"({res['markdown_bytes'] / 1024:.1f} KB)")
    print(f"## total {res['total']} symbols across {res['services']} services")
    ordered = sorted(res["per_service"].items(),
                     key=lambda kv: -kv[1]["total"])
    for svc, c in ordered:
        print(f'  {svc:<22} {c["total"]:>6} total / {c["public"]:>6} public '
              f'/ {c["exported"]:>6} exported')


def cmd_perception_scan(args):
    """Poll Gitea for new DB schema fields. Live run needs GITEA_TOKEN.

    Without a token this friendly-errors (exit 2) instead of crashing. With a
    token it polls the configured repos, prints detected schema-change events,
    and appends them to the JSONL change stream.
    """
    from .perception import (GiteaClient, load_state, save_state,
                             poll_all, emit_changes, WATCHED_REPOS,
                             GITEA_HOST, CHANGES_PATH)
    token = os.environ.get("GITEA_TOKEN")
    if not token:
        print(
            "perception-scan: GITEA_TOKEN not set.\n"
            "  Set GITEA_TOKEN (read-only, scope read:repository) to enable\n"
            "  live perception. The parser / state / orchestration are tested\n"
            "  offline with fixtures; only the network poll needs a token.\n"
            f"  Would poll {GITEA_HOST}: "
            f"{', '.join(r['repo'] for r in WATCHED_REPOS)}.",
            file=sys.stderr)
        return 2

    client = GiteaClient(GITEA_HOST, token)
    state = load_state()
    events = poll_all(WATCHED_REPOS, client, state)
    save_state(state)
    emit_changes(events)
    print(f"## perception-scan: {len(events)} schema-change event(s) "
          f"across {len(WATCHED_REPOS)} repo(s)")
    for ev in events:
        field = f".{ev['field']}" if ev.get("field") else ""
        typ = f" {ev['type']}" if ev.get("type") else ""
        print(f'  [{ev["change_type"]:<7}] {ev["object"]:<6} '
              f'{ev["table"]}{field}{typ}  '
              f'({ev["repo"]}:{ev["file"]}@{ev["commit_sha"][:8]})')
    if events:
        print(f"## appended to {CHANGES_PATH}")
    return 0


def main():
    p = argparse.ArgumentParser(prog="cg_gov")
    sub = p.add_subparsers(required=True)
    pi = sub.add_parser("index"); pi.add_argument("--limit", type=int, default=None); pi.set_defaults(fn=cmd_index)
    ps = sub.add_parser("search"); ps.add_argument("intent"); ps.add_argument("--k", type=int, default=10); ps.set_defaults(fn=cmd_search)
    pg = sub.add_parser("gate"); pg.add_argument("intent"); pg.add_argument("--k", type=int, default=10); pg.set_defaults(fn=cmd_gate)
    pr = sub.add_parser("reuse"); pr.add_argument("intent"); pr.add_argument("--k", type=int, default=10); pr.set_defaults(fn=cmd_reuse)
    psc = sub.add_parser("scan")
    psc.add_argument("--dups", action="store_true", help="scan duplicate clusters (default if neither flag)")
    psc.add_argument("--orphans", action="store_true", help="scan orphan functions/methods (0 callers, heuristic)")
    psc.add_argument("--reimpl-only", action="store_true", help="show only reimplementation clusters (drop name-collision noise)")
    psc.add_argument("--threshold", type=float, default=0.86)
    psc.add_argument("--limit", type=int, default=30)
    psc.set_defaults(fn=cmd_scan)
    pd = sub.add_parser("gen-docs", help="generate JSON源 + markdown interface catalog")
    pd.set_defaults(fn=cmd_gen_docs)
    pp = sub.add_parser("perception-scan",
                        help="poll Gitea for new DB schema fields (needs GITEA_TOKEN)")
    pp.set_defaults(fn=cmd_perception_scan)
    args = p.parse_args()
    rc = args.fn(args)
    if isinstance(rc, int) and rc != 0:
        sys.exit(rc)


if __name__ == "__main__":
    main()
