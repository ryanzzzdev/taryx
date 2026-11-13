"""Read-only check: running images and imported modules match the checkout."""

import ast
import hashlib
import json
import subprocess
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    images = set()
    for service in ("api", "api-sg", "worker", "worker-sg"):
        container = run("docker", "compose", "ps", "-q", service)
        image = run("docker", "inspect", "--format", "{{.Image}}", container)
        images.add(image)
        print(service, image)
        for module in ("taryx.core.accounts.services", "taryx.core.market.services"):
            script = (
                "import os, django, importlib, inspect; "
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE','taryx.config.settings'); "
                f"django.setup(); print(inspect.getsource(importlib.import_module({module!r})))"
            )
            live = run("docker", "compose", "exec", "-T", service, "python", "-c", script)
            local = Path("src", *module.split(".")).with_suffix(".py").read_text()
            same = ast.dump(ast.parse(live)) == ast.dump(ast.parse(local))
            print(
                json.dumps(
                    {
                        "module": module,
                        "ast_matches": same,
                        "source_sha256": hashlib.sha256(live.encode()).hexdigest(),
                    }
                )
            )
            assert same, (service, module)
    assert len(images) == 1, images


if __name__ == "__main__":
    main()
