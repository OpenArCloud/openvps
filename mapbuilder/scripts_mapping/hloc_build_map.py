# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script walks through the HLOC mapping pipeline with a given configuration

# Setup
# mkdir ~/dev/oarc && cd ~/dev/oarc
# git clone --recursive https://github.com/cvg/Hierarchical-Localization/
# conda create --name hloc python==3.10
# conda activate hloc
# cd Hierarchical-Localization
# python -m pip install -e .
#
# pip install transforms3d
# pip install pyyaml
#
# Note(09.12.2024): due to pycolmap incompatibility of Rigid3D in Triangulation, we need to downgrade manually:
# pip uninstall pycolmap
# pip install pycolmap==3.10.0
# see https://github.com/cvg/Hierarchical-Localization/issues/438
#
# Note(09.12.2024): there is another issue with Triangulation
# see https://github.com/colmap/pycolmap/issues/289
#
# Install open3d for visualization
# pip install open3d

## Usage:
# conda activate hloc
# python hloc_build_map.py --config_file <config/filename>

import os
import yaml # conda install -c conda-forge pyyaml
import argparse
from pathlib import Path

from hloc import extract_features, match_features
from hloc import pairs_from_exhaustive, pairs_from_retrieval, pairs_from_poses
from hloc import reconstruction
from pycolmap import CameraMode

def read_yaml(file_path):
    with open(file_path, "r") as f:
        return yaml.safe_load(f)


def program_includes(step):
    if step in config['program_steps']:
        if config['program_steps'][step] == True:
            return True
    return False


def hloc_build_map(config):
    try:
        outputs = Path(config['hloc_reconstruction']['reconstruction_path'])
        features_path = outputs / 'features.h5'
        global_features_path = outputs / 'global_features.h5'
        pairs_path = outputs / str('pairs_' + config['hloc_reconstruction']['pairs_strategy'] + '.txt')
        matches_path = outputs / 'matches.h5'

        if program_includes('hloc_extract_features'):
            cfg = config['hloc_reconstruction']
            feature_conf = extract_features.confs[cfg['feature_conf']]
            matcher_conf = match_features.confs[cfg['matcher_conf']]

            images_path = Path(cfg['image_path'])
            image_names = [str(p.relative_to(images_path)) for p in (images_path).iterdir()]
            print(len(image_names), "mapping images")

            extract_features.main(feature_conf, images_path, image_list=image_names, feature_path=features_path)

        if program_includes('hloc_find_image_pairs'):
            cfg = config['hloc_reconstruction']
            pairs_strategy = cfg['pairs_strategy']
            print("Searching image pairs with strategy: " + pairs_strategy)
            if pairs_strategy == 'from_exhaustive':

                pairs_from_exhaustive.main(pairs_path, image_list=image_names)

            elif pairs_strategy == 'from_retrieval':

                print("Using retrieval configuration " + cfg['retrieval_conf'])
                retrieval_conf = extract_features.confs[cfg['retrieval_conf']]
                extract_features.main(retrieval_conf, images_path, feature_path=global_features_path)
                pairs_from_retrieval.main(global_features_path, pairs_path, num_matched=10)

            elif pairs_strategy == 'from_poses':

                txt_model_path = cfg['prior_model_path']
                bin_model_path = cfg['prior_model_path']

                # Note: pairs_from_poses can only read binary models, so we convert our text to binary
                print("Converting from text to binary model ...")
                print("  Input: " + str(txt_model_path))
                print("  Output: " + str(bin_model_path))
                os.system('python ' + cfg['hloc_path'] + '/utils/read_write_model.py' +
                    ' --input_model ' + str(txt_model_path) +
                    ' --input_format .txt' +
                    ' --output_model ' + str(bin_model_path) +
                    ' --output_format .bin')

                print("Pairs from poses ...")
                prior_model_path = Path(bin_model_path)
                print("  Input: " + str(prior_model_path))
                print("  Output: " + str(pairs_path))
                pairs_from_poses.main(
                    model=prior_model_path,
                    output=pairs_path,
                    num_matched=15,
                    rotation_threshold=30
                )

            else:
                raise ValueError("Invalid pairs strategy: " + pairs_strategy)


        if program_includes('hloc_matches_from_pairs'):

            match_features.main(matcher_conf, pairs_path, features=features_path, matches=matches_path)


        if program_includes('hloc_build_model'):
            cfg = config['hloc_reconstruction']
            images_path = Path(cfg['image_path'])
            prior_model_path = Path(cfg['prior_model_path'])
            reconstruction_path = Path(cfg['reconstruction_path'])

            print("Reconstruction...")
            reconstruction.main(
                sfm_dir=reconstruction_path,
                image_dir=images_path,
                pairs=pairs_path,
                features=features_path,
                matches=matches_path,
                skip_geometric_verification=True,
                verbose=True,
                min_match_score=None,
                camera_mode=CameraMode.SINGLE
            )
        print("ALL DONE.")
        return True
    except Exception as ex:
        print("Exception occurred: " + str(ex))
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automatic HLoc mapping pipeline for OpenVPS")
    parser.add_argument("--config_file", type=str, default="config.yml",
                        help="Full path to a configuration file",
                        required=True)
    args = parser.parse_args()
    config_file = Path(args.config_file)
    if not config_file.exists() or not config_file.is_file():
        print("Error: invalid dataset dir: " + str(config_file))
        exit(-1)

    config = read_yaml(file_path=str(config_file))

    if not hloc_build_map(config):
        print("hloc_build_map failed")
        exit(-1)

