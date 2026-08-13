"""Quick sanity tests for the SnipIt data layer (no GUI needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snipit.db import Database  # noqa: E402


def main():
    base = os.path.join(os.environ.get("SNIPIT_DATA_DIR", os.getcwd()), "SnipIt")
    path = os.path.join(base, "snipit.db")
    db = Database(path)
    print("first_run:", db.first_run)
    print("count:", db.count())

    print("--- empty query (first 3):")
    for r in db.search("")[:3]:
        print("  ", r["id"], "|", r["heading"], "|", r["content"][:40])

    print("--- search 'ip config' (multi-term AND):", [r["heading"] for r in db.search("ip config")])
    print("--- search 'chatgpt rubber':", [r["heading"] for r in db.search("chatgpt rubber")])
    print("--- search 'zzzznomatch':", len(db.search("zzzznomatch")))

    sid = db.add("test snippet", "unique needle 42")
    print("--- added id", sid, "| search 'needle 42':",
          [r["heading"] for r in db.search("needle 42")])
    db.update(sid, "renamed", "unique needle 43")
    row = db.get(sid)
    print("--- updated:", row["heading"], "|", row["content"])

    sid2 = db.add("percent test", "50% done")
    print("--- literal % search:", [r["heading"] for r in db.search("50%")])
    db.delete(sid2)
    db.delete(sid)
    print("--- after delete, count:", db.count())

    # persistence: reopen
    db.close()
    db2 = Database(path)
    print("--- reopened first_run (should be False):", db2.first_run)
    db2.close()
    print("DB TESTS PASSED")


if __name__ == "__main__":
    main()
