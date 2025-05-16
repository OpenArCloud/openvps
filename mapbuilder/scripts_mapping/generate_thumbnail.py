# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script generates a thumbnail image from the alphabetically first image of a folder

# Example usage:
#python generate_thumbnail.py --input_path /maps/mapId/stray_recording/rgb.mp4 --output_path /maps/mapId/thumbnail.png
#python generate_thumbnail.py --input_path /maps/mapId/stray_colmap/images --output_path /maps/mapId//thumbnail.png


import cv2
from pathlib import Path
import argparse
import os
from image_utils import rotate_image, generate_thumbnail


# loads the alphabetically first image from a directory, or the first frame of a video
def load_first_image_from(imageSearchPath:str|Path):
    if not isinstance(imageSearchPath, Path):
        imageSearchPath = Path(imageSearchPath)

    if not imageSearchPath.exists():
        raise ValueError(f"Invalid path for image search: {str(imageSearchPath)}")

    if imageSearchPath.is_file():
        if imageSearchPath.suffix != '.mp4':
            raise ValueError(f"This script can extract frames only from mp4 files")

        vidcap = cv2.VideoCapture(str(imageSearchPath))
        if not vidcap.isOpened(): # Check if the video opened successfully
            raise ValueError(f"Could not open the video {imageSearchPath}.")
        _, image = vidcap.read() # this is actually BGR and not RGB...
        return image

    if not imageSearchPath.is_dir():
        raise ValueError(f"invalid directory path: {str(imageSearchPath)}")

    # collect all image file names in this directory
    imageFiles = []
    for child_path in imageSearchPath.iterdir():
        if child_path.is_dir():
            continue
        if child_path.is_file() and (child_path.suffix == '.png' or child_path.suffix == '.jpg'):
            imageFiles.append(child_path)

    if len(imageFiles) == 0:
        raise ValueError(f"Could not find any jpg or png images in folder {imageSearchPath}")

    # take the first image path alphabetically
    firstImageFile = sorted(imageFiles)[0]

    image = cv2.imread(str(firstImageFile))
    return image


def save_image(path:str|Path, image):
    if not isinstance(path, Path):
        path = Path(path)
    os.makedirs(path.parent, exist_ok=True)
    cv2.imwrite(str(path), image)

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--input_path', help=' path to a folder with images or to a video', type=str, required=True)
        parser.add_argument('--output_path', help='path to the output thumbnail image', type=str, required=True)
        parser.add_argument('--target_size', help="target size, odd number", default=128)
        parser.add_argument("--rotate_degrees", type=int, default=0, help="optional rotation, given in degrees out of [90,180,270] (counter-clockwise)", required=False)
        args = parser.parse_args()

        image = load_first_image_from(args.input_path)
        imageThumbnail = generate_thumbnail(image, args.target_size)

        if args.rotate_degrees != 0:
            imageThumbnail = rotate_image(args.rotate_degrees, imageThumbnail)

        save_image(args.output_path, imageThumbnail)

    except Exception as e:
        print("An error happened: " + str(e))
        exit(-1)
