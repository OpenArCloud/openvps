# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

import cv2


def resize_intrinsics(resize_factor, w, h, fx, fy, px, py):
    w_new = int(round(w * resize_factor))
    h_new = int(round(h * resize_factor))
    fx_new = fx * resize_factor
    fy_new = fy * resize_factor
    px_new = px * resize_factor
    py_new = py * resize_factor
    return w_new, h_new, fx_new, fy_new, px_new, py_new


def rotate_intrinsics(degrees, w, h, fx, fy, px, py):
    if degrees == 90:
        w_new = h
        h_new = w
        fx_new = fy
        fy_new = fx
        px_new = py
        py_new = w - px
    elif degrees == 180:
        w_new = w
        h_new = h
        fx_new = fx
        fy_new = fy
        px_new = w - px
        py_new = h - py
    elif degrees == 270:
        w_new = h
        h_new = w
        fx_new = fy
        fy_new = fx
        px_new = h - py
        py_new = px
    else:
        raise ValueError("Rotation degrees must be one of 90, 180, 270")
    return w_new, h_new, fx_new, fy_new, px_new, py_new


def rotate_image(degrees, image):
    # WARNING: the OpenCV rotate() seems to have the CW and CCW directionswapped :(
    if degrees == 270:
        operation = cv2.ROTATE_90_COUNTERCLOCKWISE  # cv2.ROTATE_90_CLOCKWISE
    elif degrees == 180:
        operation = cv2.ROTATE_180
    elif degrees == 90:  # positive 90 degrees means counterclockwise
        operation = cv2.ROTATE_90_CLOCKWISE  # cv2.ROTATE_90_COUNTERCLOCKWISE
    else:
        raise ValueError("Rotation degrees must be one of 90, 180, 270")

    image_rotated = cv2.rotate(image, operation)
    return image_rotated

# crops the image to be square of the middle of the image
def generate_thumbnail(image, targetSize):
    if targetSize%2 !=0:
        raise ValueError(f"Thumbnail target size must be an odd number")

    width = image.shape[1]
    height = image.shape[0]
    smallerSize = width if width < height else height
    halfSmallerSize = int(smallerSize/2)
    halfHeight = int(height/2)
    halfWidth = int(width/2)

    imageCropped = image[halfHeight-halfSmallerSize : halfHeight+halfSmallerSize, halfWidth-halfSmallerSize : halfWidth+halfSmallerSize]
    imageResized = cv2.resize(imageCropped, (targetSize,targetSize))
    return imageResized
