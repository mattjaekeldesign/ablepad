set shell := ["bash", "-euo", "pipefail", "-c"]

# Start the web tooling. The Vite server hosts both the architecture viewer and
# the Launchpad Config Lab at http://localhost:5178.
run:
    @echo "Ablepad trees: http://localhost:5178/"
    @echo "Config Lab:    http://localhost:5178/lab/"
    npm run dev

# Stop Vite instances using this repo's configured port or its immediate fallback ports.
kill:
    #!/usr/bin/env bash
    stopped=0
    for port in 5178 5179 5180; do
        for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true); do
            echo "Stopping dev server $pid on port $port"
            kill "$pid" 2>/dev/null || true
            stopped=1
        done
    done
    if [ "$stopped" -eq 0 ]; then
        echo "No Ablepad dev servers found on ports 5178-5180."
    fi

# Show progress from the Mermaid status classes and ROADMAP.md checkboxes.
stats:
    python3 tools/repo-stats.py

# Stage the current work and create a named commit. With no argument, prompt
# interactively so `just commit` is still enough to make a named commit.
commit *message:
    #!/usr/bin/env bash
    if [ "$#" -eq 0 ]; then
        read -r -p "Commit name: " commit_message
    else
        commit_message="$*"
    fi
    if [ -z "${commit_message//[[:space:]]/}" ]; then
        echo "Commit name cannot be empty." >&2
        exit 1
    fi
    git add -A
    git commit -m "$commit_message"
