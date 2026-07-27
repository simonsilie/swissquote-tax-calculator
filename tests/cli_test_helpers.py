import os
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def run_cli(csv_content: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the tax evaluation CLI with temporary Swissquote CSV content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin1") as file:
        file.write(csv_content)
        csv_file_path = file.name

    try:
        return subprocess.run(
            ["uv", "run", "steuer-auswertung", csv_file_path, *arguments],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
    finally:
        os.unlink(csv_file_path)
