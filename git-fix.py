#!/usr/bin/env python3
"""
Git Index Fix Tool
Fixes stale git index issues in continued sessions by forcing re-staging of modified files.
"""

import subprocess
import sys
from pathlib import Path

def run_command(cmd, capture=True):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=capture,
            text=True,
            check=False
        )
        return result.stdout.strip() if capture else ""
    except Exception as e:
        print(f"Error running command: {e}")
        return ""

def get_file_hash(file_path):
    """Get git hash of a file."""
    return run_command(f"git hash-object {file_path}")

def get_staged_hash(file_path):
    """Get the hash of the staged version of a file."""
    output = run_command(f"git ls-files -s {file_path}")
    if output:
        parts = output.split()
        if len(parts) >= 2:
            return parts[1]
    return ""

def main():
    print("🔍 Checking for git index issues...\n")

    # Check if we're in a git repo
    if run_command("git rev-parse --git-dir"):
        print("✅ Git repository detected")
    else:
        print("❌ Not a git repository")
        sys.exit(1)

    # Get list of tracked files
    tracked_files = run_command("git ls-files").split('\n')
    tracked_files = [f for f in tracked_files if f and Path(f).exists()]

    print(f"📁 Found {len(tracked_files)} tracked files\n")

    # Find files with mismatched hashes (modified but git doesn't see them)
    stale_files = []
    for file_path in tracked_files:
        working_hash = get_file_hash(file_path)
        staged_hash = get_staged_hash(file_path)

        if working_hash and staged_hash and working_hash != staged_hash:
            stale_files.append(file_path)

    if not stale_files:
        print("✅ No stale files found. Git index is up to date!")
        print("\n📊 Current status:")
        run_command("git status --short", capture=False)
        return

    print(f"⚠️  Found {len(stale_files)} files with stale index:")
    for f in stale_files:
        print(f"   - {f}")

    print("\n🔧 Fixing stale index entries...")

    for file_path in stale_files:
        print(f"   Refreshing: {file_path}")
        # Remove from cache and re-add to force git to see changes
        run_command(f"git rm --cached {file_path}")
        run_command(f"git add {file_path}")

    print("\n✅ Git index fixed!")
    print("\n📊 Updated status:")
    run_command("git status --short", capture=False)

if __name__ == "__main__":
    main()
