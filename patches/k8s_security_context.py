#!/usr/bin/env python3
"""
Patch R2E-Gym's docker.py to add securityContext: runAsUser: 0 to sandbox
pod container specs.

R2E-Gym's add_commands copies tool scripts into /usr/local/bin/ inside the
sandbox pod via `tar xmf - -C /usr/local/bin`. Without explicit runAsUser: 0,
clusters with PodSecurityAdmission enforcement can block root execution,
producing a Permission denied / exit code 126 error.
"""
import re
import sys
from pathlib import Path

DOCKER_PY = Path("/app/r2e-gym/src/r2egym/agenthub/runtime/docker.py")

content = DOCKER_PY.read_text()

# Match the "env": env_spec line followed by the "resources" key, capturing
# the indentation so we can align the injected line correctly.
pattern = re.compile(
    r'(?P<env_line>[ \t]+"env":\s*env_spec,\n)'
    r'(?P<indent>[ \t]+)"resources":'
)

match = pattern.search(content)
if not match:
    sys.exit(
        f"ERROR: expected pattern not found in {DOCKER_PY}\n"
        "Upstream docker.py may have changed — review the patch."
    )

indent = match.group("indent")
injection = f'{indent}"securityContext": {{"runAsUser": 0}},\n'

patched = pattern.sub(
    lambda m: m.group("env_line") + injection + m.group("indent") + '"resources":',
    content,
    count=1,
)

DOCKER_PY.write_text(patched)
print(f"Patched {DOCKER_PY}: added securityContext runAsUser=0 to sandbox container spec")
