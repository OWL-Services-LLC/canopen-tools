import subprocess
import os
from west.commands import WestCommand
from west import log

class OwlInstallCanopenTools(WestCommand):

    def __init__(self):
        super().__init__(
            'owl-install-canopen-tools',
            'Install all CANopen tools (OZE viewer, EDS generator, EDS editor)',
            'Runs the three setup scripts in modules/tool/canopen-tools.'
        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(self.name, help=self.help)
        return parser

    def do_run(self, args, unknown_args):
        # Workspace root is always the current west workspace topdir
        # Module path is fixed relative to workspace root
        ws_root = self.topdir
        repo_root = os.path.join(ws_root, "modules", "tools", "canopen-tools")

        if not os.path.isdir(repo_root):
            log.err(f"Expected repo path not found: {repo_root}")
            raise SystemExit(1)

        # All scripts live at repo root
        scripts = [
            "setup-oze-canopen-viewer.sh",
            "setup-canopen-eds-generator.sh",
            "setup-canopen-eds-editor.sh"
        ]

        # Run scripts with cwd set to repo root
        for script in scripts:
            script_path = os.path.join(repo_root, script)
            if not os.path.isfile(script_path):
                log.err(f"Script not found: {script_path}")
                raise SystemExit(1)

            log.inf(f"Executing: {script} in {repo_root}")
            try:
                subprocess.run(
                    ["bash", script_path],
                    cwd=repo_root,
                    check=True
                )
            except subprocess.CalledProcessError as e:
                log.err(f"Script {script} failed with code {e.returncode}")
                raise
        log.inf("✅ All CANopen tools installed successfully.")
