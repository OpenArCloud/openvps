# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
"""
Every generated dataclass answers `typing.get_type_hints()`.

idlc annotates a nested member with a fully-qualified *string* — e.g.
`cov_pos: 'spatialdds_idl.spatial.common.Mat3x3'` — while importing only
`from spatialdds_idl import spatial`. The root name in those annotations is therefore
unbound, and `get_type_hints` raises `NameError` on every generated dataclass that has a
nested member. CycloneDDS resolves annotations with its own machinery and never calls
`get_type_hints`, which is why the service ran correctly for a year with the defect in
place.

It still mattered. `get_type_hints` is how dataclass-based tooling reads a type, so schema
generators and validators could not introspect these bindings at all. Concretely: the 1.8
census could not be taken on this tree — `Announce`, `VpsRequest` and `VpsResponse` were
all unresolvable, which is three of the four types this service puts on the bus.

Found and fixed upstream in SpatialDDS-demo b856788; the same fix is applied here, since
the annotations are idlc's output and the import block is the generator's to patch.

The tree list is read from disk rather than written down. A hand-kept list would check
only the tree somebody remembered, and this repo is about to carry two.
"""

import dataclasses
import importlib
import pkgutil
import sys
import typing
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
VENDOR = HERE / "vendor"
for p in (str(HERE), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def generated_trees() -> list[str]:
    """Generated IDL packages present in vendor/, by what is on disk."""
    return sorted(
        d.name for d in VENDOR.iterdir()
        if d.is_dir() and d.name.startswith("spatialdds_idl")
        and (d / "__init__.py").is_file() and (d / "spatial").is_dir()
    )


class GeneratedTypesIntrospect(unittest.TestCase):
    def test_every_generated_dataclass_resolves_its_annotations(self):
        trees = generated_trees()
        self.assertTrue(trees, f"no generated tree found under {VENDOR}")

        checked, failures = 0, []
        for tree in trees:
            pkg = importlib.import_module(tree)
            for mod in pkgutil.walk_packages(pkg.__path__, f"{tree}."):
                try:
                    m = importlib.import_module(mod.name)
                except Exception:
                    continue          # optional deps are not this test's business
                for name in dir(m):
                    obj = getattr(m, name)
                    # `obj.__module__ == mod.name` keeps re-exports from being
                    # counted twice, and keeps the count a count of definitions.
                    if not (isinstance(obj, type)
                            and dataclasses.is_dataclass(obj)
                            and obj.__module__ == mod.name):
                        continue
                    checked += 1
                    try:
                        typing.get_type_hints(obj)
                    except NameError as e:
                        failures.append(f"{mod.name}.{name}: {e}")

        self.assertEqual(
            failures[:6], [],
            f"{len(failures)} generated dataclass(es) cannot resolve their own "
            f"annotations; first few: {failures[:6]}")
        # A floor, so a walk that silently finds nothing cannot pass. One tree is
        # ~113 dataclasses; the number is checked, not the tree count.
        self.assertGreater(
            checked, 100,
            f"only {checked} dataclasses examined across {trees} — too few to be a "
            f"whole generated tree, so the walk is broken rather than the types")


if __name__ == "__main__":
    unittest.main(verbosity=2)
