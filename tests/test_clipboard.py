"""Regression test for the bug that matters most in a snippet manager:
a copied snippet has to still be on the clipboard after SnipIt exits.

Tk only *lends* the clipboard — it claims ownership and renders the text on
demand, so quitting used to leave the user with nothing to paste. This spawns a
child that copies and dies, then checks the clipboard from here.
"""
import _sandbox  # noqa: F401  (must precede snipit imports)

import os
import subprocess
import sys

from snipit import clipboard  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = "SnipIt clipboard probe\r\nline two\tand a tab · ünïcode ✓"

CHILD = (
    "import sys; sys.path.insert(0, %r)\n"
    "from snipit import clipboard\n"
    "print(clipboard.copy(%r))\n" % (PROJECT_ROOT, PROBE)
)


def main():
    if not clipboard.IS_WINDOWS:
        print("not Windows — skipping"); return

    _sandbox.borrow_clipboard()   # hand the user's clipboard back afterwards

    out = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    print("child reported persisted:", out.stdout.strip())
    assert out.stdout.strip() == "True", "copy() should report an OS-owned clipboard"

    survived = clipboard.paste()
    print("clipboard after the child exited:", repr(survived[:40]))
    assert survived == PROBE, "a copied snippet must outlive the process that copied it"

    # line endings are normalised for Windows consumers
    clipboard.copy("a\nb\nc")
    print("newlines on the clipboard:", repr(clipboard.paste()))
    assert clipboard.paste() == "a\r\nb\r\nc"

    print("CLIPBOARD TEST PASSED")


if __name__ == "__main__":
    main()
