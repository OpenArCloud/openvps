# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script generates a config file that specifies the parameters for an HLOC mapping pipeline

import yaml
from pathlib import Path
import os
import argparse


def hloc_generate_config(hloc_dir, input_model_dir, output_dir, output_config_file, feature_conf="superpoint_aachen", matcher_conf="superglue", retrieval_conf="netvlad", pairs_strategy="from_retrieval"):
    try:
        hloc_dir_path = Path(hloc_dir)
        if not hloc_dir_path.exists() or not hloc_dir_path.is_dir():
            print("Error: invalid HLOC dir: " + str(hloc_dir_path))
            return False

        input_model_dir_path = Path(input_model_dir)
        if not input_model_dir_path.exists() or not input_model_dir_path.is_dir():
            print("Error: invalid input model dir: " + str(input_model_dir_path))
            return False

        output_dir_path = Path(output_dir)
        os.makedirs(output_dir_path, exist_ok=True)

        output_config_file_path = Path(output_config_file)

        # TODO: hardcoded config for now, but these values could be passed from the Web GUI
        config = {
            "program_steps": {
                "hloc_extract_features": True,
                "hloc_find_image_pairs": True,
                "hloc_matches_from_pairs": True,
                "hloc_build_model": True,
            },
            "hloc_reconstruction" : {
                "hloc_path": hloc_dir,
                "image_path": str(input_model_dir_path/"images"),
                "feature_conf": feature_conf,
                "matcher_conf": matcher_conf,
                "retrieval_conf": retrieval_conf,
                "pairs_strategy": pairs_strategy, # from_exhaustive # from_retrieval # from_poses,
                "prior_model_path": str(input_model_dir_path),
                "reconstruction_path": str(output_dir),
                "optimize_poses": True,
            },
        }

        with open(str(output_config_file_path), 'w') as file:
            yaml.dump(config, file)

        print("HLOC config written to " + str(output_config_file_path))
        return True

    except Exception as ex:
        print("Exception occurred: " + str(ex))
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Extract frames from video.")
    parser.add_argument('--hloc_dir', type=str, default=None,
                        help="Direcotry of HLoc code", required=True)
    parser.add_argument("--input_model_dir", type=str, default=None,
                        help="Input directory of dataset", required=True)
    parser.add_argument("--output_dir", type=str, default=None,
                        help="Output directory where the HLOC results will be written", required=True)
    parser.add_argument("--output_config_file", type=str, default=None,
                        help="Output config file", required=True)
    args = parser.parse_args()

    if not hloc_generate_config(args.hloc_dir, args.input_model_dir, args.output_dir, args.output_config_file):
        exit(-1)
