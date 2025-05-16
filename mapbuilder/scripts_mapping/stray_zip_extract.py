# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script extracts a StrayScanner recording from a zip taken from an iPhone

import tempfile
import zipfile
import shutil
import argparse
from pathlib import Path

def extract(path_to_zip_file, directory_to_extract_to):
    filePath = Path(path_to_zip_file)
    filename_without_extension = filePath.stem

    tempdir = tempfile.mkdtemp()
    print("extracting to temporary directory: {}".format(tempdir))

    with zipfile.ZipFile(path_to_zip_file, 'r') as zip_ref:
        zip_ref.extractall(tempdir)
        zip_ref.close()

    extraction_dir = tempdir + "/" + filename_without_extension

    print("moving from temp dir " + extraction_dir  + " to final directory " + directory_to_extract_to)
    shutil.move(extraction_dir, directory_to_extract_to)


def contains_expected_stray_files(path:Path):
    print("verifying " + str(path))
    if not path.is_dir():
        return False
    if not path.joinpath("rgb.mp4").exists():
        return False
    if not path.joinpath("camera_matrix.csv").exists():
        return False
    if not path.joinpath("odometry.csv").exists():
        return False
    if not path.joinpath("imu.csv").exists():
        return False
    if not path.joinpath("depth").exists() or not path.joinpath("depth").is_dir():
        return False
    if not path.joinpath("confidence").exists() or not path.joinpath("confidence").is_dir():
        return False
    return True


def verify_stray_directory_structure(main_dir):
    main_path = Path(main_dir)
    if not main_path.is_dir():
        print("Warning: " + main_dir + " is not a directory")
        return

    # remove __MACOSX garbage
    if main_path.joinpath("__MACOSX").exists():
        shutil.rmtree(str(main_path.joinpath("__MACOSX")))

    # Warning: this is specific to StrayScanner recordings
    print("Checking directory structure...")
    if contains_expected_stray_files(main_path):
        print("The folder structure looks good.")
        return
    print("Stray recording was not found in the main folder " + str(main_path))

    print("Checking subdirectory structure...")
    for child_path in main_path.iterdir():
        if child_path.is_dir() and contains_expected_stray_files(child_path):
            print("Stray recording was found in subdir " + str(child_path))
            print("Moving recording to main path " + str(main_path))
            for content_path in child_path.iterdir():
                new_path = main_path.joinpath(content_path.name)
                if content_path.name == ".DS_Store":
                    continue # skip

                shutil.move(str(content_path), str(new_path)) # Recursively move a file or directory (src) to another location
            shutil.rmtree(child_path) # remove old directory

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zipping and unzipping tools")
    parser.add_argument("--zip_path", type=str, default=None,
                        help="Input zip file", required=True)
    parser.add_argument("--output_dir", type=str, default=None,
                        help="Output directory file", required=True)
    args = parser.parse_args()

    try:
        print("extracting StrayScanner recording " + args.zip_path + " to " + args.output_dir + " ...")
        extract(args.zip_path, args.output_dir)
        verify_stray_directory_structure(args.output_dir)
        print("done.")
    except Exception as e:
        print("An error happened: " + str(e))
        exit(-1)
