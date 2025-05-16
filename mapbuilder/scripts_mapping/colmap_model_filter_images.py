# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script skips/removes images of a colmap model that are too close to previous ones

# min_pos_dif is in meters
# min_ori_dif is in degrees


import pathlib
import argparse
import os
import numpy as np
import shutil
import math
import transforms3d as t3d # pip install transforms3d

kReadWriteModelScriptPath = os.path.dirname(os.path.abspath(__file__)) + "/" + "../../Hierarchical-Localization/hloc/utils"

# reject if too close in position
def reject_due_position_distance_small(vec1, vec2, min_pos_distance):
    return np.linalg.norm(vec1 - vec2) < min_pos_distance

# reject if too close in orientation
def reject_due_orientation_distance_small(quat1, quat2, min_ori_distance):
    qdiff = t3d.quaternions.qmult(t3d.quaternions.qconjugate(quat1), quat2)
    axis, angle = t3d.quaternions.quat2axangle(qdiff)
    return angle < math.radians(min_ori_distance)

def colmap_model_filter_images(input_colmap_model_dir=None, input_images_dir=None, output_colmap_model_dir=None, output_images_dir=None,
                               output_format='.txt', min_pos_distance=0.10, min_ori_distance=5, verbose=False,
                               read_write_model_script_path=kReadWriteModelScriptPath):
    input_colmap_model_dir = pathlib.Path(input_colmap_model_dir)
    if not input_colmap_model_dir.exists() or not input_colmap_model_dir.is_dir():
        raise ValueError("Invalid input_colmap_model_dir: " + str(input_colmap_model_dir))

    input_images_dir = pathlib.Path(input_images_dir)
    if not input_images_dir.exists() or not input_images_dir.is_dir():
        raise ValueError("Invalid input_images_dir: " + str(input_images_dir))

    output_colmap_model_dir = pathlib.Path(output_colmap_model_dir)
    if input_colmap_model_dir == output_colmap_model_dir:
        raise ValueError("input_colmap_model_dir and output_colmap_model_dir must be different")
    if not output_colmap_model_dir.exists():
        output_colmap_model_dir.mkdir(parents=True, exist_ok=True)
    elif not output_colmap_model_dir.is_dir():
        raise ValueError("Invalid output_colmap_model_dir: " + str(output_colmap_model_dir))

    output_images_dir = pathlib.Path(output_images_dir)
    if output_images_dir == input_images_dir:
        raise ValueError("input_images_dir and output_images_dir must be different")
    if not output_images_dir.exists():
        output_images_dir.mkdir(parents=True, exist_ok=True)
    elif not output_images_dir.is_dir():
        raise ValueError("Invalid output_images_dir: " + str(output_images_dir))

    print("Input colmap model dir: " + str(input_colmap_model_dir))
    print("Input images dir: " + str(input_images_dir))
    print("Output colmap model dir: " + str(output_colmap_model_dir))
    print("Output images dir: " + str(output_images_dir))
    print("read_write_model_script_path: " + str(read_write_model_script_path))

    import sys
    sys.path.append(read_write_model_script_path)
    from read_write_model import read_model, qvec2rotmat, write_model


    try:
        print("Loading colmap model from " + str(input_colmap_model_dir))
        cameras, images, points3D = read_model(str(input_colmap_model_dir))


        print("The input model has")
        print("  " + str(len(cameras)) + " cameras")
        print("  " + str(len(images)) + " images")
        print("  " + str(len(points3D)) + " points3D")
        if verbose:
            print("Cameras:")
            print(cameras.values())

        print("Filtering images based on their poses ...")
        trajectory = {}
        out_images = {}
        counter = 0
        for image_id, image in images.items():
            counter = counter + 1
            if counter % 250 == 0:
                print(" " + str(counter) + "/" + str(len(images)))

            if verbose:
                print("# " + str(image_id))

            # rotation
            R = qvec2rotmat(image.qvec)

            # translation
            t = image.tvec

            # invert to get camera pose in world
            t = -R.T @ t
            R = R.T

            q = t3d.quaternions.mat2quat(R) # transforms3d uses WXYZ convention!
            cur_pose = {
                "tvec": t,
                "qvec": q
            }

            if verbose:
                print("   " + str(t) + "   " + str(q))

            if len(trajectory) == 0:
                trajectory[image_id] = cur_pose
                continue

            reject = False
            for prev_id, prev_pose in trajectory.items():
                if reject_due_position_distance_small(cur_pose["tvec"], prev_pose["tvec"], min_pos_distance):
                    if reject_due_position_distance_small(cur_pose["qvec"], prev_pose["qvec"], min_ori_distance):
                        reject = True
                    # note: we still keep those that are close in position but have large orientation distance

            if reject:
                # TODO: we should also delete points and cameras that are only connected with this image
                # TODO: at least we should remove the image ID from the points3D index lists
                continue


            # This frame's pose is significantly different from any other seen so far, so keep it and its pose
            trajectory[image_id] = cur_pose
            out_images[image_id] = image



        print("The filtered model has")
        print("  " + str(len(out_images)) + " images")

        print("Writing output model ...")
        write_model(cameras, out_images, points3D, path=output_colmap_model_dir, ext=output_format)

        print(f"Copying selected images from " + str(input_images_dir) + " to " + str(output_images_dir) + " ...")
        counter = 0
        for image_id, image in out_images.items():
           counter = counter + 1
           if counter % 250 == 0:
                print(" " + str(counter) + "/" + str(len(out_images)))

           input_image_path = input_images_dir / image.name
           output_image_path = output_images_dir / image.name
           shutil.copy(input_image_path, output_image_path)

        print("All done.")
        return True
    except Exception as e:
        print("Exception: " + str(e))
        return False



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Reducing the number of images in a colmap model")
    parser.add_argument("--input_colmap_model_dir", type=str, default=None,
                        help="Input directory of original colmap model",
                        required=True)
    parser.add_argument("--input_images_dir", type=str, default=None,
                        help="Input directory of original images",
                        required=True)
    parser.add_argument("--output_colmap_model_dir", type=str, default=None,
                        help="Output directory for the reduced colmap model",
                        required=True)
    parser.add_argument("--output_images_dir", type=str, default=None,
                        help="Output directory for the reduced model",
                        required=True)
    parser.add_argument("--output_format", type=str, default='.txt',
                        help="Output format for the reduced colmap model",
                        required=False)
    parser.add_argument("--min_pos_distance", type=float, default=0.10,
                        help="minimum position distance between two frames in meters",
                        required=False)
    parser.add_argument("--min_ori_distance", type=float, default=5,
                        help="minimum orientation distance between two frames in degrees",
                        required=False)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--read_write_model_script_path", type=str,
                        default=kReadWriteModelScriptPath,
                        help="path to the python scripts of the original colmap repository",
                        required=False)
    args = parser.parse_args()

    if not colmap_model_filter_images(args.input_colmap_model_dir, args.input_images_dir,
                               args.output_colmap_model_dir, args.output_images_dir,
                               args.output_format, args.min_pos_distance, args.min_ori_distance,
                               args.verbose, args.read_write_model_script_path):
        exit(-1)

