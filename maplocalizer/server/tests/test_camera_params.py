# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
"""
Intrinsics translation for every COLMAP camera model.

This is the function that produced the worst defect of this branch: it took the first four
parameters of a SIMPLE_RADIAL camera — which are (f, cx, cy, k) — and passed them off as
(fx, fy, cx, cy). The query localized, cleared the inlier threshold, returned VPS_SUCCESS
and was 9.6 m out. Nothing errored, so only a comparison against the HTTP path found it.

The expectations below are transcribed from COLMAP's own model definitions
(src/colmap/sensor/models/*.h), where each model declares a params_info string. A model
whose string begins "f, cx, cy" has one focal length; one beginning "fx, fy, cx, cy" has
two. Writing this test is what revealed the fix had missed SIMPLE_DIVISION and
SIMPLE_FISHEYE, so the list is kept whole here rather than sampled.
"""

import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
for p in (str(HERE), str(HERE / "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

# Import _pinhole_params without dragging in torch, hloc, cv2 or a DDS stack.
for _n in ("cv2", "hloc_localizer", "test_gpu", "hloc", "torch", "pycolmap", "h5py",
           "yaml", "base_localizer"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
sys.modules["cv2"].imdecode = lambda *a, **k: None
sys.modules["cv2"].IMREAD_COLOR_BGR = 1
sys.modules["test_gpu"].getGpuInfo = lambda: "stub"
sys.modules["base_localizer"].BaseLocalizer = object
sys.modules["base_localizer"].LocalizationResult = object
sys.modules["hloc_localizer"].HlocLocalizer = type("H", (), {
    "get_all_map_ids_and_paths": staticmethod(lambda *a, **k: {}),
    "load_map_config": staticmethod(lambda *a, **k: None)})

from main import _pinhole_params                                  # noqa: E402

F, CX, CY = 680.5, 360.0, 480.0
FX, FY = 700.0, 710.0
D = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12]

# model -> (params as COLMAP packs them, expected (fx, fy, cx, cy))
SINGLE = {
    "SIMPLE_PINHOLE":        [F, CX, CY],
    "SIMPLE_RADIAL":         [F, CX, CY, D[0]],
    "SIMPLE_RADIAL_FISHEYE": [F, CX, CY, D[0]],
    "SIMPLE_FISHEYE":        [F, CX, CY],
    "SIMPLE_DIVISION":       [F, CX, CY, D[0]],
    "RADIAL":                [F, CX, CY, D[0], D[1]],
    "RADIAL_FISHEYE":        [F, CX, CY, D[0], D[1]],
}
TWO = {
    "PINHOLE":                    [FX, FY, CX, CY],
    "OPENCV":                     [FX, FY, CX, CY] + D[:4],
    "OPENCV_FISHEYE":             [FX, FY, CX, CY] + D[:4],
    "FULL_OPENCV":                [FX, FY, CX, CY] + D[:8],
    "FOV":                        [FX, FY, CX, CY, D[0]],
    "FISHEYE":                    [FX, FY, CX, CY] + D[:4],
    "DIVISION":                   [FX, FY, CX, CY, D[0]],
    "EUCM":                       [FX, FY, CX, CY, D[0], D[1]],
    "THIN_PRISM_FISHEYE":         [FX, FY, CX, CY] + D[:8],
    "RAD_TAN_THIN_PRISM_FISHEYE": [FX, FY, CX, CY] + D[:12],
}


class _Cam:
    def __init__(self, name, params):
        self.model = types.SimpleNamespace(name=name)
        self.params = params


class PinholeParams(unittest.TestCase):

    def test_single_focal_models_duplicate_f(self):
        for name, params in SINGLE.items():
            with self.subTest(model=name):
                self.assertEqual(_pinhole_params(_Cam(name, params)), [F, F, CX, CY])

    def test_two_focal_models_pass_the_first_four_through(self):
        for name, params in TWO.items():
            with self.subTest(model=name):
                self.assertEqual(_pinhole_params(_Cam(name, params)), [FX, FY, CX, CY])

    def test_the_regression_that_caused_a_9m_error(self):
        """SIMPLE_RADIAL must not be read as PINHOLE: cx would arrive as fy."""
        got = _pinhole_params(_Cam("SIMPLE_RADIAL", [F, CX, CY, 0.000626]))
        self.assertEqual(got, [F, F, CX, CY])
        self.assertNotEqual(got, [F, CX, CY, 0.000626], "the original defect")

    def test_equirectangular_is_refused_not_guessed(self):
        """It carries (w, h) and no focal length; a guess here is a confident wrong pose."""
        with self.assertRaises(ValueError):
            _pinhole_params(_Cam("EQUIRECTANGULAR", [1920.0, 960.0]))

    def test_an_unknown_model_is_refused(self):
        with self.assertRaises(ValueError):
            _pinhole_params(_Cam("SOME_FUTURE_MODEL", [1.0, 2.0, 3.0, 4.0, 5.0]))

    def test_every_colmap_model_is_classified(self):
        """
        All 18 models COLMAP defines are accounted for, so a camera cannot fall through to
        a guess. EQUIRECTANGULAR is deliberately in neither set — it has no focal length.
        """
        import main
        known = main._SINGLE_FOCAL_MODELS | main._TWO_FOCAL_MODELS | {"EQUIRECTANGULAR"}
        self.assertEqual(len(known), 18)
        self.assertEqual(set(SINGLE), set(main._SINGLE_FOCAL_MODELS))
        self.assertEqual(set(TWO), set(main._TWO_FOCAL_MODELS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
