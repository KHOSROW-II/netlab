# NetLab on Windows

This guide is for running NetLab on the school's Windows machine.

## Requirements

- Windows 10 or 11 (64-bit)
- Docker Desktop for Windows (with WSL2 backend)
- At least 4 GB of free RAM and 20 GB of free disk space
- Python 3.11 or 3.12 (only needed to **build** the .exe, not to run it)

## Running the prebuilt .exe

1. Double-click `NetLab.exe`.
2. If Docker Desktop is not installed, NetLab will offer to download it.
3. Follow the Docker installer prompts, then launch NetLab again.
4. The NetLab window will open.

## Building the .exe yourself

1. Install Python 3.11 or 3.12 from <https://python.org>.
2. Install Docker Desktop from <https://docs.docker.com/desktop/install/windows-install/>.
3. Open PowerShell and run:

   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force
   .\setup.ps1
   python scripts/build.py
   ```

4. The executable will be at `dist\NetLab.exe`.

## Docker auto-download

NetLab checks for Docker at startup. If Docker is missing, it prompts you
and offers to download the installer automatically. The installer is saved
to your Downloads folder and launched.

Because installing Docker Desktop requires administrator privileges and
sometimes a reboot, NetLab cannot install it silently. You will still need
to click through the Docker installer prompts.

## Cross-group routing

NetLab uses Docker networks with a router container between them. For
cross-group traffic to flow, `net.bridge.bridge-nf-call-iptables` must be 0.
Inside WSL2, run once:

```bash
wsl -d Ubuntu -e sudo sysctl -w net.bridge.bridge-nf-call-iptables=0
wsl -d Ubuntu -e sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0
```

Or click the yellow routing banner in NetLab.
```

---

## Tests

```bash
source .venv/bin/activate

# 1. Install with new structure
pip install -e '.[dev,web]'

# 2. Verify
python -c "import netlab.web.routes; print('ok')"
python -m pytest tests/ -q
# Expect: 135 passed

# 3. Test the Monitor fix: deploy, destroy via CLI, refresh Monitor
netlab cluster up -f examples/phase3-topology.yaml
# open http://127.0.0.1:8000 → Monitor → boxes appear
netlab cluster down -f examples/phase3-topology.yaml
# refresh Monitor → boxes should DISAPPEAR (previously they stayed)

# 4. Test bootstrap (Linux only shows a print, Windows shows a dialog)
python -c "from netlab.bootstrap import check_docker; check_docker(); print('Docker OK')"
```