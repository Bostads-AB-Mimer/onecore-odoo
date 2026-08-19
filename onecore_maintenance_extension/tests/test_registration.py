"""Guard against test files that silently never run.

Odoo discovers tests by looking at the TestCase classes reachable as attributes
of the addon's `tests` package, so a test file only runs if tests/__init__.py
imports it. Importing the containing package is not enough, which makes an
unregistered file fail open: it looks like a passing test suite because nothing
in it ever executes.

That is not hypothetical. test_dialog_indicator, test_master_key_change_indicator,
test_maintenance_activity_suppression and test_maintenance_staircase were all
dormant this way, and the first two had rotted into 17 failures by the time
anyone ran them.
"""
import io
import os
import re

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Matches how every test case in this addon is declared, e.g.
# "class TestFoo(FakerMixin, TransactionCase):".
TEST_CASE_RE = re.compile(
    r"^class\s+\w+\s*\([^)]*(?:TransactionCase|HttpCase|SavepointCase|TestCase)",
    re.MULTILINE,
)
IMPORT_RE = re.compile(r"^from \.([\w.]+) import (\w+)$", re.MULTILINE)


def _module_paths_with_test_cases():
    """Dotted paths, relative to tests/, of every file defining a TestCase."""
    found = set()
    for root, _dirs, files in os.walk(TESTS_DIR):
        for name in files:
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            source = io.open(path, encoding="utf-8").read()
            # Skips helper modules such as utils/test_utils.py, which are named
            # test_* but define no cases.
            if not TEST_CASE_RE.search(source):
                continue
            relative = os.path.relpath(path, TESTS_DIR)[: -len(".py")]
            found.add(relative.replace(os.sep, "."))
    return found


def _registered_module_paths():
    """Dotted paths imported by tests/__init__.py."""
    source = io.open(os.path.join(TESTS_DIR, "__init__.py"), encoding="utf-8").read()
    registered = {
        f"{package}.{module}" for package, module in IMPORT_RE.findall(source)
    }
    # Top-level "from . import test_x" has no package part.
    registered |= set(re.findall(r"^from \. import (\w+)$", source, re.MULTILINE))
    return registered


@tagged("onecore")
class TestTestRegistration(TransactionCase):
    def test_every_test_file_is_imported_in_tests_init(self):
        unregistered = _module_paths_with_test_cases() - _registered_module_paths()
        self.assertFalse(
            unregistered,
            "These test files define test cases but are not imported in "
            "onecore_maintenance_extension/tests/__init__.py, so Odoo will "
            "never run them:\n  "
            + "\n  ".join(sorted(unregistered))
            + "\nAdd an import for each to tests/__init__.py.",
        )
