"""Root conftest.py.

Its only job is to exist here: pytest's default "prepend" import mode inserts the
directory of the first conftest.py it collects into sys.path, which is what lets
test files do `from juniper...` without installing the package.
"""
