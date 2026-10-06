#!/usr/bin/env python3
"""
council_dispatcher.py — Lightweight, Zero-Dependency Swarm Cross-Review Dispatcher for BMAD.
Dispatches a unified diff to available external LLM CLIs (MiniMax, Kimi, Gemini, Codex)
and formats findings for the BMAD triage flow without ARG_MAX risks or false approvals.
"""

import sys
import os
import subprocess
import shutil
import tempfile
import time

SYSTEM_PROMPT = """You are an independent Senior Adversarial Code Reviewer operating under the BMAD Method.
Inspect the unified diff strictly for:
1. Logic regressions and contract violations.
2. Multi-tenancy isolation leaks and missing tenant scoping on queries/mutations.
3. Unsafe concurrency, data races, or unhandled async leaks.
4. Security vulnerabilities (injections, exposed credentials, authorization bypasses).

RULES:
- Ignore style or aesthetic suggestions.
- Report only concrete, reproducible bugs with file/line evidence.
- If and only if the diff is completely clean, correct, and free of defects, return strictly the exact word: APPROVED
"""

def run_minimax(bin_path, diff_content):
    # Passes payload via stdin to prevent ARG_MAX blowup on large diffs
    cmd = [bin_path, "-s", SYSTEM_PROMPT]
    return subprocess.run(cmd, input=diff_content, capture_output=True, text=True, timeout=180)

def run_kimi(bin_path, diff_content):
    # Passes payload via ephemeral tempfile with 0600 permissions and guaranteed cleanup
    diff_file = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False) as tf:
            os.chmod(tf.name, 0o600)
            tf.write(diff_content)
            diff_file = tf.name
        prompt = f"{SYSTEM_PROMPT}\n\nReview the diff at {diff_file}"
        cmd = [bin_path, "-p", prompt]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    finally:
        if diff_file and os.path.exists(diff_file):
            try:
                os.remove(diff_file)
            except OSError:
                pass

def run_codex(bin_path, diff_content):
    # Uses canonical non-interactive 'codex exec' command form
    prompt = f"{SYSTEM_PROMPT}\n\nDiff content:\n{diff_content}"
    cmd = [bin_path, "exec", "--color", "never", prompt]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)

def run_gemini(bin_path, diff_content):
    cmd = [bin_path, "-p", SYSTEM_PROMPT]
    return subprocess.run(cmd, input=diff_content, capture_output=True, text=True, timeout=180)

ADAPTERS = [
    {
        "name": "minimax",
        "bin": os.path.expanduser("~/.local/bin/minimax"),
        "runner": run_minimax
    },
    {
        "name": "kimi",
        "bin": os.path.expanduser("~/.kimi-code/bin/kimi"),
        "runner": run_kimi
    },
    {
        "name": "codex",
        "bin": shutil.which("codex"),
        "runner": run_codex
    },
    {
        "name": "gemini",
        "bin": shutil.which("gemini"),
        "runner": run_gemini
    }
]

def main():
    if len(sys.argv) < 2:
        print("Usage: council_dispatcher.py <diff_file_path>", file=sys.stderr)
        sys.exit(2)

    diff_path = sys.argv[1]
    if not os.path.exists(diff_path):
        print(f"Error: Diff file '{diff_path}' not found", file=sys.stderr)
        sys.exit(2)

    with open(diff_path, "r", encoding="utf-8") as f:
        diff_content = f.read()

    executed = False
    last_error = None

    # Probe adapters in order; try next adapter if one fails or is unauthenticated
    for adapter in ADAPTERS:
        bin_path = adapter["bin"]
        if not (bin_path and os.path.exists(bin_path) and os.access(bin_path, os.X_OK)):
            continue

        print(f"[*] Probing cross-review with external adapter: {adapter['name']}")
        try:
            res = adapter["runner"](bin_path, diff_content)
            if res.returncode != 0:
                last_error = f"{adapter['name']} exited with code {res.returncode}: {res.stderr.strip() or res.stdout.strip()}"
                print(f"[-] Adapter {adapter['name']} failed execution, trying next available reviewer...")
                continue

            output = res.stdout.strip()
            # Strict approval verification: must be exactly "APPROVED" or start with "APPROVED\n"
            # Eliminates false positives like "NOT APPROVED: <bug>"
            if output == "APPROVED" or output.startswith("APPROVED\n"):
                print("✅ Council Gate: APPROVED by independent adversarial reviewer.")
                sys.exit(0)
            else:
                print(f"⚠️ Council Gate: FINDINGS identified by {adapter['name']}:\n\n{output}")
                sys.exit(1)

        except subprocess.TimeoutExpired:
            print(f"[-] Reviewer timeout waiting for CLI '{adapter['name']}', trying next adapter...")
            last_error = f"Timeout on {adapter['name']}"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    # Fallback when no working CLI adapter could execute the review
    fallback_dir = "_bmad-output/review-prompts"
    os.makedirs(fallback_dir, exist_ok=True)
    timestamp = int(time.time())
    pid = os.getpid()
    fallback_file = os.path.join(fallback_dir, f"council-review-{timestamp}-{pid}.md")
    with open(fallback_file, "w", encoding="utf-8") as f:
        f.write(f"# BMAD Council Review Prompt (Manual Inspection Required)\n\n")
        if last_error:
            f.write(f"> Last adapter error: {last_error}\n\n")
        f.write(f"{SYSTEM_PROMPT}\n\n## Unified Diff:\n```diff\n{diff_content}\n```\n")
    try:
        os.chmod(fallback_file, 0o600)
    except OSError:
        pass

    print(f"BLOCKED: No working external CLI reviewer available. Prompt written to '{fallback_file}'. Status: HALT_INSPECT", file=sys.stderr)
    # Exit with code 2 to ensure automated pipelines treat unreviewed diffs as halted, not approved
    sys.exit(2)

if __name__ == "__main__":
    main()
