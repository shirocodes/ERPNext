"""Run inside an initialized development bench console with IPython %run."""
import argparse
import sys
import unittest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", nargs="?", default="all", choices=["all", "01", "02", "03", "04", "05", "06"])
    args = parser.parse_args()
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    import frappe
    if not getattr(frappe.local, "site", None):
        raise RuntimeError("Start bench --site YOUR_DEV_SITE console, then use %run")
    pattern = "test_*.py" if args.stage == "all" else f"test_{args.stage}_*.py"
    suite = unittest.defaultTestLoader.discover(root, pattern=pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"Ran {result.testsRun}; failures={len(result.failures)}; errors={len(result.errors)}; skipped={len(result.skipped)}")
    return result


if __name__ == "__main__":
    result = main()
