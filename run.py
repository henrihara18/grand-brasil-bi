"""
Grand Brasil BI - Ponto de entrada.

Uso:
    python run.py

Inicia o dashboard Streamlit, matando qualquer instância anterior na porta 8501.
"""

import subprocess
import sys
import time
from pathlib import Path


PORT = 8501


def kill_existing() -> None:
    """Encerra qualquer processo usando a porta 8501."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue "
             f"| Select-Object -ExpandProperty OwningProcess "
             f"| Sort-Object -Unique "
             f"| ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}"],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            time.sleep(1)
    except Exception:
        pass


def main() -> None:
    """Launch the Streamlit dashboard."""
    app_path = Path(__file__).parent / "grand_brasil" / "dashboard" / "app.py"

    if not app_path.exists():
        print(f"Erro: arquivo do dashboard nao encontrado em {app_path}")
        sys.exit(1)

    kill_existing()
    print(f"Iniciando Grand Brasil BI em http://localhost:{PORT} ...")

    subprocess.run(
        [
            sys.executable, "-m", "streamlit", "run", str(app_path),
            f"--server.port={PORT}",
            "--server.headless=true",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
