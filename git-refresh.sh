#!/bin/bash
# Git Index Refresh Helper
# Fixes stale git index issues in continued sessions

echo "🔄 Refreshing git index..."

# Force git to re-scan all files
git update-index --really-refresh > /dev/null 2>&1

# Check for modified files that git might not see
echo "📝 Checking for modified files..."
git ls-files -m

# Show current status
echo ""
echo "📊 Current git status:"
git status --short

echo ""
echo "✅ Git index refreshed!"
echo ""
echo "If you still see 'nothing to commit', run:"
echo "  git rm --cached <file> && git add <file>"
