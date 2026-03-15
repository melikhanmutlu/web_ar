#!/bin/bash
# BDK Hook: Session Context Save
# Saves session summary and updates Memory Bank activeContext on Stop event

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')

# Memory directory
MEMORY_DIR="$CWD/.agent/.claude/memory"
mkdir -p "$MEMORY_DIR" 2>/dev/null

TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
DATE=$(date +%Y-%m-%d)

# Get git context if available
BRANCH=$(cd "$CWD" 2>/dev/null && git branch --show-current 2>/dev/null || echo "unknown")
RECENT_COMMITS=$(cd "$CWD" 2>/dev/null && git log --oneline -5 2>/dev/null || echo "no git history")
CHANGED_FILES=$(cd "$CWD" 2>/dev/null && git diff --name-only HEAD~1 2>/dev/null | head -10 || echo "unknown")

# Update activeContext (create if missing, append session entry)
ACTIVE_CTX="$MEMORY_DIR/MEMORY-activeContext.md"

if [ ! -f "$ACTIVE_CTX" ]; then
    cat > "$ACTIVE_CTX" << EOF
# Active Context
> Last updated: $DATE

## Current Work
- **Branch:** $BRANCH
- **Status:** in progress

## Recent Sessions
EOF
fi

# Append session entry
cat >> "$ACTIVE_CTX" << EOF

### Session $DATE ($TIMESTAMP)
- **Branch:** $BRANCH
- **Session ID:** $SESSION_ID
- **Recent commits:**
$(echo "$RECENT_COMMITS" | sed 's/^/  - /')
- **Files changed:**
$(echo "$CHANGED_FILES" | sed 's/^/  - /')
EOF

# Update last-updated timestamp
sed -i "s/> Last updated:.*/> Last updated: $DATE/" "$ACTIVE_CTX" 2>/dev/null

# Output confirmation
echo "Memory Bank updated: $ACTIVE_CTX"

exit 0
