# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script loads a Colmap model and writes the 3D points into a PLY file.

import os
import argparse
from pathlib import Path
from pycolmap import Reconstruction

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Colmap model export to PLY")
    parser.add_argument("--input_model_dir", type=str, default=None,
                        help="Input zip file", required=True)
    parser.add_argument("--output_ply_path", type=str, default=None,
                        help="Output directory file", required=True)
    args = parser.parse_args()

    input_model_dir = Path(args.input_model_dir)
    if not input_model_dir.exists() or not input_model_dir.is_dir():
        print("Error: invalid model dir: " + str(input_model_dir))
        exit(-1)

    try:
        output_ply_path = Path(args.output_ply_path)
        os.makedirs(output_ply_path.parent, exist_ok=True)
        reconstruction = Reconstruction(str(input_model_dir))
        reconstruction.export_PLY(str(output_ply_path))
    except Exception as ex:
        print("Exception occurred: " + str(ex))
        exit(-1)
