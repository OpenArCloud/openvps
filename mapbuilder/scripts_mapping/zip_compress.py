# Copyright 2025 Nokia
# Licensed under the MIT License
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script compresses a directory into a zip file

import os
import argparse
import shutil
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compressing a folder")
    parser.add_argument("--input_dir", type=str, default=None,
                        help="Input directory", required=True)
    parser.add_argument("--zip_path", type=str, default=None,
                        help="Output file", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        print("Error: invalid input dir: " + str(input_dir))
        exit(-1)

    try:
        zip_path = Path(args.zip_path)
        os.makedirs(zip_path.parent, exist_ok=True)

        if zip_path.suffix == '.zip':
            zip_path_nosuffix = zip_path.with_suffix('') # remove extension because make_archive will add it to the name
        shutil.make_archive(base_name=str(zip_path_nosuffix), format="zip", root_dir=str(input_dir))
        print("Successfully created zip file: " + str(zip_path))
    except Exception as ex:
        print("Exception occurred: " + str(ex))
        exit(-1)
