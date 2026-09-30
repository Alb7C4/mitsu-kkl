#!/usr/bin/env python3
"""Copy the firmware to a Raspberry Pi Pico 2 W running MicroPython. Needs mpremote:
pip install mpremote

  python pico/deploy.py              # finds the Pico by itself
  python pico/deploy.py --port COM7
  python pico/deploy.py --config     # also overwrite config.json on the Pico (Wi-Fi, pins)
  python pico/deploy.py --defs       # also overwrite the PID definitions on the Pico

Without --config / --defs those files are copied only when the Pico does not have them yet,
so the Wi-Fi password and PID names edited on the device survive an update.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PICO = Path(__file__).resolve().parent
ROOT = PICO.parent
FIRMWARE = ("main.py", "hub.py", "httpd.py", "kline.py")
PAGE = ("index.html", "app.js", "style.css")
BASIC = {0x07, 0x10, 0x11, 0x14, 0x15, 0x17, 0x21, 0x24, 0x40, 0x45}  # short list = fast updates


def stage(dest, config_overrides=None):
    """Build the Pico's file system image in `dest`: firmware, page, version, config, definitions."""
    sys.path.insert(0, str(ROOT))
    from kkl import __version__, piddefs

    dest = Path(dest)
    (dest / "web").mkdir(parents=True, exist_ok=True)
    for f in FIRMWARE:
        shutil.copy(PICO / f, dest / f)
    for f in PAGE:
        shutil.copy(ROOT / "web" / f, dest / "web" / f)
    (dest / "version.py").write_text(f'VERSION = "{__version__}"\n', encoding="utf-8")
    cfg = json.loads((PICO / "config.json").read_text(encoding="utf-8"))
    cfg.update(config_overrides or {})
    (dest / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    src = ROOT / "pid_definitions.csv"
    if not src.exists():
        src = ROOT / "pid_definicje.csv"
    defs, _problems, keep, _legacy = piddefs.load_defs(src)
    for pid, d in defs.items():
        d.active = pid in BASIC
    piddefs.save_defs(dest / "pid_definitions.csv", defs, keep)
    shutil.copy(ROOT / "dtc_definitions.csv", dest / "dtc_definitions.csv")
    return dest


def mpremote(port, *args, check=True):
    cmd = [sys.executable, "-m", "mpremote", "connect", port, *args]
    return subprocess.run(cmd, check=check, capture_output=not check, text=True)


def on_pico(port, name):
    return mpremote(port, "fs", "cat", ":" + name, check=False).returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="auto", help="COM port of the Pico (default: auto)")
    ap.add_argument("--config", action="store_true", help="overwrite config.json on the Pico")
    ap.add_argument("--defs", action="store_true", help="overwrite the PID definitions on the Pico")
    args = ap.parse_args()
    try:
        import mpremote  # noqa: F401
    except ImportError:
        sys.exit("mpremote is missing: pip install mpremote")

    img = stage(Path(tempfile.mkdtemp(prefix="mitsu-kkl-pico-")))
    files = [*FIRMWARE, "version.py", *(f"web/{f}" for f in PAGE)]
    for name, force in (("config.json", args.config), ("pid_definitions.csv", args.defs),
                        ("dtc_definitions.csv", False)):
        if force or not on_pico(args.port, name):
            files.append(name)
        else:
            print(f"keeping {name} on the Pico")
    mpremote(args.port, "fs", "mkdir", ":web", check=False)
    for name in files:
        print("copy", name)
        mpremote(args.port, "fs", "cp", str(img / name), ":" + name)
    mpremote(args.port, "reset")
    print("Done. The Pico restarts and opens the Wi-Fi network from config.json.")


if __name__ == "__main__":
    main()
