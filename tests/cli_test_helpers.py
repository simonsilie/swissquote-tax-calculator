import os
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def run_cli(
    csv_content: str,
    arguments: list[str],
    environment: dict[str, str] | None = None,
    withholding_tax_rules: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the tax evaluation CLI with temporary Swissquote CSV content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as file:
        file.write(csv_content)
        csv_file_path = file.name

    tax_rules_path: str | None = None
    if withholding_tax_rules:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as file:
            file.write(withholding_tax_rules)
            tax_rules_path = file.name

    try:
        environment_variables = os.environ.copy()
        if environment:
            environment_variables.update(environment)
        command_arguments = ["uv", "run", "steuer-auswertung", csv_file_path, *arguments]
        if tax_rules_path:
            command_arguments.extend(["--withholding-tax-rules", tax_rules_path])
        return subprocess.run(
            command_arguments,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            env=environment_variables,
        )
    finally:
        os.unlink(csv_file_path)
        if tax_rules_path:
            os.unlink(tax_rules_path)
