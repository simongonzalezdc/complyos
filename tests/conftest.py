"""Suite-wide fixtures and environment neutralization.

CLI tests parse captured stdout as JSON. Rich/Typer honor FORCE_COLOR and
friends from the invoking shell, so an environment that forces color (some
CI runners, some agent shells) injects ANSI escapes into captured output and
breaks json.loads. Neutralize color env for the whole suite so results do
not depend on who runs it.
"""

from __future__ import annotations

import os

os.environ.pop("FORCE_COLOR", None)
os.environ.pop("CLICOLOR_FORCE", None)
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ["COLUMNS"] = "200"
