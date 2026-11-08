import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_cli(
    csv_content: str,
    arguments: list[str],
    environment: dict[str, str] | None = None,
    withholding_tax_rules: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the installed CLI offline in a disposable working directory and home."""
    with tempfile.TemporaryDirectory() as directory:
        working_directory = Path(directory)
        home_directory = working_directory / "home"
        home_directory.mkdir()
        csv_file = working_directory / "transactions.csv"
        csv_file.write_text(csv_content, encoding="latin1")
        environment_variables = {
            key: value for key, value in os.environ.items() if not key.startswith("SWISSQUOTE_TAX_")
        }
        environment_variables.update(
            HOME=str(home_directory),
            XDG_CACHE_HOME=str(home_directory / ".cache"),
            XDG_CONFIG_HOME=str(home_directory / ".config"),
            SWISSQUOTE_TAX_OFFLINE="true",
        )
        if environment:
            environment_variables.update(environment)
        command_arguments = [sys.executable, "-m", "taxes.cli", str(csv_file), "--no-export-summary", *arguments]
        if withholding_tax_rules is not None:
            rules_file = working_directory / "withholding-tax-rules.toml"
            rules_file.write_text(withholding_tax_rules, encoding="utf-8")
            command_arguments.extend(["--withholding-tax-rules", str(rules_file)])
        return subprocess.run(
            command_arguments,
            capture_output=True,
            text=True,
            cwd=working_directory,
            env=environment_variables,
            timeout=60,
        )
