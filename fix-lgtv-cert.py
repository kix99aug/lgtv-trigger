"""Re-apply the webOS "blacklisted certificate" workaround to lgtvremote-cli.

Recent LG firmware rejects the public `test-signing-cert` signature that
lgtvremote-cli ships in its registration manifest:

    Error: Registration failed: 403 Pairing rejected: blacklisted certificate detected

aiowebostv 0.9.2 fixed the same problem by dropping the whole "signatures"
block from the handshake payload; this script does that to the installed
lgtvremote_cli.py.

The patch is lost whenever the package is re-downloaded (`uv tool upgrade
lgtvremote-cli`, or a `uv cache clean` followed by a forced reinstall), so
re-run this afterwards. A same-version `uv tool install` without --force is a
no-op and leaves the patch alone.

Usage:
    python fix-lgtv-cert.py            # patch (idempotent)
    python fix-lgtv-cert.py --check    # report status only, never writes
    python fix-lgtv-cert.py --path X   # patch a specific lgtvremote_cli.py
"""

import argparse
import glob
import os
import subprocess
import sys

MODULE_NAME = "lgtvremote_cli.py"


def find_module_path():
    """Locate the installed lgtvremote_cli.py inside the uv tool environment."""
    roots = []
    try:
        out = subprocess.run(
            ["uv", "tool", "dir"], capture_output=True, text=True, timeout=30
        )
        if out.returncode == 0 and out.stdout.strip():
            roots.append(os.path.join(out.stdout.strip(), "lgtvremote-cli"))
    except (OSError, subprocess.SubprocessError):
        pass

    # Fallbacks for a uv install without `uv` on PATH, plus pipx layouts.
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(os.path.join(appdata, "uv", "tools", "lgtvremote-cli"))
        roots.append(os.path.join(appdata, "pipx", "venvs", "lgtvremote-cli"))
    home = os.path.expanduser("~")
    roots.append(os.path.join(home, ".local", "share", "uv", "tools", "lgtvremote-cli"))
    roots.append(os.path.join(home, ".local", "pipx", "venvs", "lgtvremote-cli"))

    for root in roots:
        for pattern in (
            os.path.join(root, "Lib", "site-packages", MODULE_NAME),
            os.path.join(root, "lib", "*", "site-packages", MODULE_NAME),
        ):
            hits = sorted(glob.glob(pattern))
            if hits:
                return hits[0]
    return None


def _find_matching_bracket(src, start):
    """Return the index of the ']' closing the '[' at src[start], skipping strings."""
    depth = 0
    i = start
    while i < len(src):
        ch = src[i]
        if ch == '"':
            i += 1
            while i < len(src) and src[i] != '"':
                i += 2 if src[i] == "\\" else 1
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced brackets around the signatures block")


def strip_signatures(src):
    """Remove the `"signatures": [...],` entry. Returns (new_src, removed)."""
    key = '"signatures"'
    key_at = src.find(key)
    if key_at == -1:
        return src, False

    open_at = src.find("[", key_at)
    if open_at == -1:
        raise ValueError('no list follows the "signatures" key')
    end = _find_matching_bracket(src, open_at) + 1

    # Swallow a trailing comma and the blank line the entry leaves behind.
    while end < len(src) and src[end] in " \t":
        end += 1
    if end < len(src) and src[end] == ",":
        end += 1
    line_start = src.rfind("\n", 0, key_at)
    if line_start == -1 or src[line_start + 1 : key_at].strip():
        line_start = key_at - 1  # key is not alone on its line; keep the line itself

    new_src = src[: line_start + 1] + src[end:].lstrip("\n")
    if "signatureVersion" in new_src:
        raise ValueError("a signature blob survived the edit; refusing to write")
    compile(new_src, "lgtvremote_cli.py", "exec")  # never leave a broken module
    return new_src, True


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report status, do not write")
    parser.add_argument("--path", help="path to lgtvremote_cli.py (default: auto-detect)")
    args = parser.parse_args()

    path = args.path or find_module_path()
    if not path or not os.path.isfile(path):
        print(
            "Could not find lgtvremote_cli.py. Is lgtvremote-cli installed "
            "(`uv tool install lgtvremote-cli`)? Pass --path to point at it.",
            file=sys.stderr,
        )
        return 1

    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    try:
        new_src, removed = strip_signatures(src)
    except ValueError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        print("The handshake payload changed shape; patch it by hand.", file=sys.stderr)
        return 1

    if not removed:
        print(f"{path}\n  Already patched (no signatures block).")
        return 0

    if args.check:
        print(f"{path}\n  NOT patched: the blacklisted signatures block is present.")
        return 1

    # Write through a temp file so uv's hardlinked cache copy stays pristine.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_src)
    os.replace(tmp, path)
    print(f"{path}\n  Patched: removed the blacklisted signatures block.")
    print("  Run `lgtv pair` if the TV still rejects the client key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
