import subprocess
import os
from west.commands import WestCommand
from west import log

class OwlInstallCanopenTools(WestCommand):

    def __init__(self):
        super().__init__(
            'owl-install-canopen-tools',
            'Install all CANopen tools (OZE viewer, EDS generator, EDS editor)',
            'Runs the setup scripts in modules/tool/canopen-tools.'
        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(self.name, help=self.help)
        parser.add_argument(
            "--only-canopen-gen",
            action="store_true",
            help="Run only the setup-canopen-eds-generator.sh script"
        )
        return parser

    def do_run(self, args, unknown_args):
        ws_root = self.topdir
        repo_root = os.path.join(ws_root, "modules", "tools", "canopen-tools")

        if not os.path.isdir(repo_root):
            log.err(f"Expected repo path not found: {repo_root}")
            raise SystemExit(1)

        # Decide scripts depending on flag
        if args.only_canopen_gen:
            scripts = ["setup-canopen-eds-generator.sh"]
        else:
            scripts = [
                "setup-oze-canopen-viewer.sh",
                "setup-canopen-eds-generator.sh",
                "setup-canopen-eds-editor.sh"
            ]

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

        log.inf("✅ CANopen tools installation finished.")
