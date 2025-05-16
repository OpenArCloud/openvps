# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# This script converts a StrayScanner dataset to Colmap format
# Example usage
# python.exe stray_to_colmap.py --input_dir /path/to/StrayScannerRecording --resize_factor 0.25 --rotate_degrees 90

import os
import pathlib
import argparse
import math
import numpy as np
from scipy.spatial.transform import Rotation
import cv2
from image_utils import rotate_image, rotate_intrinsics, resize_intrinsics

kReadWriteModelScriptPath = os.path.dirname(os.path.abspath(__file__)) + "/" + "../../Hierarchical-Localization/hloc/utils"

def read_stray_data(scene):
    intrinsics = np.loadtxt(os.path.join(scene, 'camera_matrix.csv'), delimiter=',')
    odometry = np.loadtxt(os.path.join(scene, 'odometry.csv'), delimiter=',', skiprows=1)
    imu = np.loadtxt(os.path.join(scene, 'imu.csv'), delimiter=',', skiprows=1)
    poses = []
    for line in odometry:
        # timestamp, frame, x, y, z, qx, qy, qz, qw

        #timestamp = line[0]
        #frame_id = int(line[1])
        position = line[2:5]
        quaternion = line[5:]
        T_WC = np.eye(4)
        T_WC[:3, :3] = Rotation.from_quat(quaternion).as_matrix()
        T_WC[:3, 3] = position
        poses.append(T_WC)
    depth_dir = os.path.join(scene, 'depth')
    depth_frames = [os.path.join(depth_dir, p) for p in sorted(os.listdir(depth_dir))]
    depth_frames = [f for f in depth_frames if '.npy' in f or '.png' in f]
    return { 'poses': poses, 'intrinsics': intrinsics, 'depth_frames': depth_frames, 'imu': imu, 'odometry': odometry }




def stray_to_colmap(input_dir:str, output_dir:str, resize_factor=1.0, rotate_degrees=0,
        read_write_model_script_path=kReadWriteModelScriptPath):

    import sys
    sys.path.append(read_write_model_script_path)
    from read_write_model import write_model, qvec2rotmat, rotmat2qvec, Camera, Image


    input_dir_path = pathlib.Path(input_dir)
    if not input_dir_path.exists() or not input_dir_path.is_dir():
        raise ValueError("Invalid input_dir")
    print("Input directory: " + str(input_dir_path))

    output_dir_path = pathlib.Path(output_dir)
    if not output_dir_path.exists():
        output_dir_path.mkdir(parents=True, exist_ok=True)
    elif not output_dir_path.is_dir():
        raise ValueError("Invalid output_dir")
    print("Output directory: " + str(output_dir_path))

    output_images_dir_path = output_dir_path / "images"
    if not output_images_dir_path.exists():
        output_images_dir_path.mkdir(parents=True, exist_ok=True)

    data = read_stray_data(str(input_dir_path))
    timestamps = data['odometry'][:, 0]
    poses = data['poses']

    colmap_cameras = {}
    colmap_images = {}
    colmap_points3D = {}

    try:
        rgb_video_path = input_dir_path / 'rgb.mp4'
        vidcap = cv2.VideoCapture(str(rgb_video_path))
        if not vidcap.isOpened(): # Check if the video opened successfully
            print("Oops! We couldn't open the video.")
        total = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
        print("The video contains " + str(total) + " frames.")
        # we will fill up the counter with zeros so that all filenames are of same length
        image_filename_num_digits = int(math.ceil(math.log10(total)))

        count = 0
        while True:
            # Get an image
            ret, rgb_image = vidcap.read() # this is actually BGR and not RGB...
            if not ret:
                break

            # TODO: only a single camera is supported for now
            # camera calibration
            # http://docs.ros.org/en/melodic/api/sensor_msgs/html/msg/CameraInfo.html
            width = rgb_image.shape[1]
            height = rgb_image.shape[0]
            rgb_intrinsics = data['intrinsics']
            fx = rgb_intrinsics[0][0]
            px = rgb_intrinsics[0][2]
            fy = rgb_intrinsics[1][1]
            py = rgb_intrinsics[1][2]

            # resize (optional)
            if resize_factor != 1.0:
                rgb_image = cv2.resize(rgb_image, (0,0), fx=resize_factor, fy=resize_factor, interpolation=cv2.INTER_LINEAR)
                width, height, fx, fy, px, py = resize_intrinsics(resize_factor, width, height, fx, fy, px, py)

            # rotate (optional)
            if rotate_degrees != 0:
                rgb_image = rotate_image(rotate_degrees, rgb_image)
                width, height, fx, fy, px, py = rotate_intrinsics(rotate_degrees, width, height, fx, fy, px, py)

            # save the camera
            camera_params = [fx, fy, px, py]
            # see https://github.com/colmap/colmap/blob/main/src/colmap/sensor/models.h
            shared_camera_id = 1 # TODO: do not hardcode the ID and allow multiple cameras (ARKit can give per-frame intrinsics)
            shared_camera = Camera(
                id=shared_camera_id,
                model="PINHOLE",
                width=width,
                height=height,
                params=camera_params)
            if not shared_camera_id in colmap_cameras:
                colmap_cameras[shared_camera_id] = shared_camera

            # Get the pose of the image
            # camera in world
            pose_c2w = poses[count]

            # convert from graphics convention (X right, Y up, Z backwards) to vision convention (X right, Y down, Z forward)
            T_gl_to_cv = np.eye(4)
            T_gl_to_cv[1][1] = -1
            T_gl_to_cv[2][2] = -1
            pose_c2w = np.matmul(T_gl_to_cv, pose_c2w)

            # world in camera
            pose_w2c = np.linalg.inv(pose_c2w)

            new_R = pose_w2c[:3,:3]
            new_qvec = rotmat2qvec(new_R)
            new_t = pose_w2c[:3,3]

            new_image_name = "frame_" + str(count).zfill(image_filename_num_digits) + ".jpg"
            image_file_path = output_images_dir_path / new_image_name
            cv2.imwrite(str(image_file_path), rgb_image)
            #cv2.imshow("RGB image", rgb_image)

            new_image_id = count + 1 # NOTE: Colmap starts indexing at 1
            new_camera_id = shared_camera_id # TODO: allow more than a single camera
            new_image = Image(
                id=new_image_id,
                qvec=new_qvec,
                tvec=new_t,
                camera_id=new_camera_id,
                name=new_image_name,
                xys=np.array([]), # we do not have 2D image features
                point3D_ids=np.array([]) # we do not have 3D world points
            )
            colmap_images[new_image_id] = new_image

            if count % 250 == 0:
                print(str(count) + "/" + str(total))
            count += 1

            key = cv2.waitKey(1)
            if key == 27: # Esc
                break

        vidcap.release()


        # Export the colmap model:
        write_model(colmap_cameras, colmap_images, colmap_points3D, str(output_dir_path), ext=".txt")

        print("ALL DONE.")
        return True

    except Exception as ex:
        print("Exception occurred: " + str(ex))
        return False



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_dir', type=str, required=True)
    parser.add_argument('--output_dir', type=str, required=True)
    parser.add_argument('--resize_factor', type=float, default=1.0, required=False, help='optional factor for resizing images')
    parser.add_argument("--rotate_degrees", type=int, default=0, help="optional rotation, given in degrees out of [90,180,270] (counter-clockwise)", required=False)
    parser.add_argument("--read_write_model_script_path", default=kReadWriteModelScriptPath)
    args = parser.parse_args()

    if not stray_to_colmap(args.input_dir, args.output_dir, args.resize_factor, args.rotate_degrees, args.read_write_model_script_path):
        exit(-1)
