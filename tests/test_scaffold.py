import importlib


def test_package_imports_and_has_version():
    pkg = importlib.import_module("jarvis")
    assert pkg.__version__ == "0.1.0"
