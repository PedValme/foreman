"""Screenshots of every preview scenario, light and dark, with headless Chrome or Edge (nothing else is installed).

    python examples/panel-preview/build.py
    python examples/panel-preview/screenshots.py [--out <folder>] [--browser <chrome.exe>]

Each shot loads index.html with a URL hash that fixes the scenario, step, theme, width and motion, and stops the
autoplay. Standard library only.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# (file name, hash options, window width, window height[, virtual time budget in ms])
SHOTS = [
    ("01-empty-light", "s=1&theme=light&w=400", 1000, 700),
    ("01-empty-dark", "s=1&theme=dark&w=400", 1000, 700),
    ("02-blocked-gate-light", "s=2&theme=light&w=400", 1000, 700),
    ("02-blocked-gate-dark", "s=2&theme=dark&w=400", 1000, 700),
    ("03-story-0-gate-light", "s=3&step=0&theme=light&w=400", 1000, 700),
    ("03-story-1-review-light", "s=3&step=1&theme=light&w=400", 1000, 700),
    ("03-story-2-bounced-light", "s=3&step=2&theme=light&w=400", 1000, 700),
    ("03-story-2-bounced-dark", "s=3&step=2&theme=dark&w=400", 1000, 700),
    ("03-story-3-fixed-review-light", "s=3&step=3&theme=light&w=400", 1000, 700),
    ("03-story-4-waiting-owner-light", "s=3&step=4&theme=light&w=400", 1000, 700),
    ("03-story-4-waiting-owner-dark", "s=3&step=4&theme=dark&w=400", 1000, 700),
    ("03-story-5-merged-light", "s=3&step=5&theme=light&w=400", 1000, 700),
    ("04-several-light", "s=4&theme=light&w=400", 1000, 1150),
    ("04-several-dark", "s=4&theme=dark&w=400&open=1", 1000, 1350),
    ("04-several-360-dark", "s=4&theme=dark&w=360", 900, 1150),
    ("04-several-full-light", "s=4&theme=light&w=full&open=1", 1400, 1000),
    ("05-long-text-360-light", "s=5&step=0&theme=light&w=360", 900, 800),
    ("05-long-text-reduced-dark", "s=5&step=0&theme=dark&w=400&motion=reduce", 1000, 800),
    ("05-corrupt-file-light", "s=5&step=1&theme=light&w=400", 1000, 700),
    ("05-backend-off-dark", "s=5&step=2&theme=dark&w=400", 1000, 700),
    # Mid-animation: the snapshot changes at 1.5 s and the shot is taken about 0.3 s later.
    ("06-motion-bounce-midway-light", "s=3&step=1&go=2&delay=1500&theme=light&w=400", 1000, 700, 1850),
    ("06-motion-to-owner-midway-dark", "s=3&step=3&go=4&delay=1500&theme=dark&w=400", 1000, 700, 1800),
    ("06-motion-merged-midway-light", "s=3&step=4&go=5&delay=1500&theme=light&w=400", 1000, 700, 1800),
    ("06-motion-bounce-reduced-light", "s=3&step=1&go=2&delay=1500&theme=light&w=400&motion=reduce", 1000, 700, 1850),
]


def find_browser(explicit):
    candidates = [explicit] if explicit else []
    candidates += [shutil.which(n) for n in ("google-chrome", "chromium", "chrome", "msedge")]
    candidates += [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                   r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("No Chrome or Edge found; pass --browser.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "trabajo" / "panel-screenshots"))
    parser.add_argument("--browser")
    parser.add_argument("--only", help="substring of the shot names to take")
    args = parser.parse_args(argv)
    if not (HERE / "out" / "plugin.classic.js").is_file():
        raise SystemExit("Run build.py first.")
    browser = find_browser(args.browser)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    page = (HERE / "index.html").resolve().as_uri()
    for name, opts, width, height, *budget in SHOTS:
        if args.only and args.only not in name:
            continue
        target = out / (name + ".png")
        with tempfile.TemporaryDirectory(prefix="foreman-shot-") as profile:
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--user-data-dir=" + profile, "--force-device-scale-factor=1",
                            "--window-size=%d,%d" % (width, height), "--virtual-time-budget=%d" % (budget[0] if budget else 4000),
                            "--screenshot=" + str(target), "%s#%s&still=1&shot=1" % (page, opts)],
                           check=True, capture_output=True, timeout=120)
        print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
