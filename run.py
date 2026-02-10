"""
Grand Brasil BI - Ponto de entrada.

Uso:
    python run.py

Inicia o dashboard Streamlit automaticamente.
"""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Launch the Streamlit dashboard."""
    app_path = Path(__file__).parent / "grand_brasil" / "dashboard" / "app.py"

    if not app_path.exists():
        print(f"Erro: arquivo do dashboard nao encontrado em {app_path}")
        sys.exit(1)

    print("Iniciando Grand Brasil - BI Estoque...")
    print(f"Dashboard: {app_path}")
    print()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.headless=true",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
