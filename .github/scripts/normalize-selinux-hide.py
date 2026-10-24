#!/usr/bin/env python3
"""Normalize KernelSU's selinux_hide.c so SUSFS4KSU's
10_enable_susfs_for_ksu.patch applies cleanly on this tree.

Why this exists
---------------
`build.yml` applies that patch as:

    patch -p1 --forward < 10_enable_susfs_for_ksu.patch || true

The `|| true` means a failed hunk leaves a .rej behind and the build keeps
going, so the only symptom is the `-Rejects` artifact. Hunk #1 of that patch
deletes `my_sel_open_handle_status()`, and it expects the *locked* read of
`fake_status`:

        void *data;
        mutex_lock(&selinux_state.status_lock);
        data = fake_status;
        mutex_unlock(&selinux_state.status_lock);

Some KernelSU revisions carry the *unlocked* one-liner:

        void *data = fake_status;

`patch --fuzz=N` cannot bridge that: fuzz only relaxes leading/trailing
context lines, never `-` deletion lines. Verified: fuzz=1/2/3 all reject.
The other 116 of 120 old-side lines match byte-for-byte, so restoring just
these four lines makes the hunk apply at fuzz=0 with zero rejects.

Safety
------
The restored lines are deleted by the patch in the same run, so they are
never compiled. This is pre-image normalization, not a semantic edit.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET_SUFFIX = "feature/selinux_hide.c"

UNLOCKED = """        void *data = fake_status;
        if (data) {"""

LOCKED = """        void *data;
        mutex_lock(&selinux_state.status_lock);
        data = fake_status;
        mutex_unlock(&selinux_state.status_lock);
        if (data) {"""

# Post-patch marker: if present, the patch already landed and there is
# nothing to normalize.
PATCHED_MARKER = "ksu_selinux_hide_handle_second_stage"


def candidates(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("selinux_hide.c") if str(p).endswith(TARGET_SUFFIX))


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    dry_run = "--check" in argv[1:]

    if len(args) != 1:
        print(__doc__)
        return 2

    root = Path(args[0])
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    hits = candidates(root)
    if not hits:
        print(f"error: no */{TARGET_SUFFIX} under {root}", file=sys.stderr)
        return 1

    rc = 0
    for path in hits:
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8")

        if PATCHED_MARKER in text:
            print(f"skip  {rel}: patch already applied")
            continue

        if LOCKED in text:
            print(f"skip  {rel}: already normalized")
            continue

        count = text.count(UNLOCKED)
        if count != 1:
            print(
                f"::error::{rel}: expected exactly 1 unlocked fake_status read, "
                f"found {count}; tree drifted, refusing to guess",
                file=sys.stderr,
            )
            rc = 1
            continue

        if dry_run:
            print(f"check {rel}: would normalize")
            continue

        path.write_text(text.replace(UNLOCKED, LOCKED), encoding="utf-8")
        print(f"ok    {rel}: restored status_lock around fake_status read")

    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
