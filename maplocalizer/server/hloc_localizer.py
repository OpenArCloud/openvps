# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)


import pycolmap

from hloc import extract_features, match_features, pairs_from_retrieval
from hloc import extractors, matchers
from hloc import extract_features, match_features
from hloc.utils.base_model import dynamic_load
from hloc.utils.parsers import names_to_pair
from hloc.localize_sfm import do_covisibility_clustering

from types import SimpleNamespace
from typing import List, Tuple
from collections import defaultdict

import torch
import numpy as np
import cv2
import h5py
import numpy as np
from scipy.spatial.transform import Rotation

from pathlib import Path
import json
import yaml

from oscp.geopose import GeoPose, Position, Quaternion
from oscp.geoposeprotocol import CameraParameters
from oscp.geopose_utils import enu_to_geodetic


# code adapted from hloc.localize_sfm.QueryLocalizer
# NOTE(soeroesg): pycolmap API changed and the absolute_pose_estimation got removed/renamed.
# Therefore we cannot simply use the QueryLocalizer, but instead copy its code here and change the pose_estimation method
class QueryLocalizerNew:

    def __init__(self, reconstruction, config=None):
        self.reconstruction = reconstruction
        self.config = config or {}

    def localize(self, points2D_all, points2D_idxs, points3D_id, query_camera):
        if len(points2D_idxs) < 4: # Note: not enough points!
            return None

        points2D = points2D_all[points2D_idxs]
        points3D = [self.reconstruction.points3D[j].xyz for j in points3D_id]
        ret = pycolmap.estimate_and_refine_absolute_pose(
            points2D,
            points3D,
            query_camera,
            estimation_options=self.config.get("estimation", {}),
            refinement_options=self.config.get("refinement", {}),
        )
        return ret


class HlocLocalizer():

    def __init__(self, debug=False):
        self.debug=debug
        self.kQueryImageName = 'query'
        self.covisibility_clustering = True
        self.map_to_ENU_transform = np.eye(4)
        self.map_geodetic_ref = Position(0,0,0)


    def get_all_map_ids_and_paths(rootDir:str|Path):
        if isinstance(rootDir, str):
            rootDir = Path(rootDir)
        allMaps = {}
        if not rootDir.exists() or not rootDir.is_dir():
            return allMaps
        dirs = [f for f in rootDir.iterdir() if f.is_dir()]
        for dir in dirs:
            fileNames = [f.name for f in dir.iterdir() if f.is_file()]
            if not 'status.json' in fileNames:
                continue # this dir was not created by our MapBuilder
            subDirNames = [f.name for f in dir.iterdir() if f.is_dir()]
            if not 'hlocMaps' in subDirNames:
                continue # this dir has no hloc maps
            hlocMapsDir = dir / 'hlocMaps'
            hlocMapsSubDirs = [f for f in hlocMapsDir.iterdir() if f.is_dir()]
            for mapPath in hlocMapsSubDirs:
                mapId = mapPath.stem
                allMaps[mapId] = mapPath
        return allMaps


    def load_map_config(configPath:str|Path, rewriteRootDirFrom:str|None=None, rewriteRootDirTo:str|None=None):
        if isinstance(configPath, str):
            configPath = Path(configPath)
        if not configPath.exists() or not configPath.is_file():
            return None
        with open(configPath) as stream:
            try:
                config = yaml.safe_load(stream)
                mapConfig = config['hloc_reconstruction']

                # Note: the root dir is different in/outside docker, so we might want to rewrite it in the paths at loading time
                if rewriteRootDirFrom is not None:
                    for (k,v) in mapConfig.items():
                        if str(v).find(rewriteRootDirFrom) >= 0:
                            mapConfig[k] = str(v).replace(rewriteRootDirFrom, rewriteRootDirTo)

                return mapConfig
            except yaml.YAMLError as err:
                print(err)
                return None


    def load_map(self, config):
        self.config = config

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Device: {self.device}")

        self.feature_conf = extract_features.confs[config['feature_conf']]
        print(f"Feature conf: {self.feature_conf}")

        self.matcher_conf = match_features.confs[config['matcher_conf']]
        print(f"Matcher conf: {self.matcher_conf}")

        if config['retrieval_conf'] is not None:
            self.retrieval_conf = extract_features.confs[config['retrieval_conf']]
            print(f"Retrieval conf: {self.retrieval_conf}")
        else:
            self.retrieval_conf = None

        # Load local feature extractor module
        feature_extractor_module = dynamic_load(extractors, self.feature_conf['model']['name'])
        self.feature_extractor = feature_extractor_module(self.feature_conf['model']).eval().to(self.device)

        # Load global feature extractor / retrieval module
        if self.retrieval_conf is not None:
            global_feature_extractor_module = dynamic_load(extractors, self.retrieval_conf['model']['name'])
            self.global_feature_extractor = global_feature_extractor_module(self.retrieval_conf['model']).eval().to(self.device)

        # Load matcher module
        matcher_module = dynamic_load(matchers, self.matcher_conf['model']['name'])
        self.matcher = matcher_module(self.matcher_conf['model']).eval().to(self.device)


        # Load map (reconstruction)
        map_path = Path(config['reconstruction_path']) # / 'models' / '0'
        if not map_path.exists() or not map_path.is_dir():
            raise FileNotFoundError(f"map path {str(map_path)} does not exist")
        print(f"Map path: {str(map_path)}")
        self.reconstruction = pycolmap.Reconstruction()
        self.reconstruction.read(str(map_path))

        self.map_image_names = [i.name for i in self.reconstruction.images.values()]
        if len(self.map_image_names) == 0:
            raise ValueError("Could not find any map images.")

        self.db_name_to_id = {img.name: i for i, img in self.reconstruction.images.items()}

        # Load map local features
        local_features_path = Path(config['reconstruction_path']) / 'features.h5'
        self.load_map_local_features(local_features_path)

        # Load map global features
        global_features_path = Path(config['reconstruction_path']) / 'global_features.h5'
        if global_features_path.exists():
            self.load_map_global_features(global_features_path)


    def load_map_transform(self, map_transform_path:Path):
        try:
            with open(str(map_transform_path), 'r') as file:
                data = json.load(file)
                self.map_to_ENU_transform = data['matrix']

                # We convert from graphics convention (X right, Y up, Z backwards) to ENU convention (X/E right, Y/N forward, Z/U up)
                # rotation around X with +90deg
                graphics_to_robotics_transform = np.array([
                    [1, 0, 0, 0],
                    [0, 0,-1, 0],
                    [0, 1, 0, 0],
                    [0, 0, 0, 1]
                ])
                self.map_to_ENU_transform = np.matmul(graphics_to_robotics_transform, self.map_to_ENU_transform)

                ref_lat = data['latitude']
                ref_lon = data['longitude']
                ref_h = data['height']
                self.map_geodetic_ref = Position(ref_lat, ref_lon, ref_h)
            print(f"Successfully loaded map transform from {map_transform_path}")
            return True
        except:
            print(f"Could not load map transform from {map_transform_path}")
            return False



    def export_map(self):
        export_path = Path(self.config["reconstruction_path"]) / 'sparse.ply'
        self.reconstruction.export_PLY(str(export_path))
        print(f"Exported map to {str(export_path)}")


    def camera_from_parameters(self, width, height, camera_parameters: CameraParameters):
        camera = pycolmap.Camera()
        camera.camera_id = 0
        camera.width = width
        camera.height = height
        camera.model = camera_parameters.model
        camera.params = camera_parameters.modelParams
        return camera


    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/utils/io.py
    def load_map_local_features(self, local_features_path:Path):
        print(f"Loading map local features from: {str(local_features_path)}")
        # NOTE(soeroesg): we do not load all local features into GPU nor into RAM because they are huge.
        # We only open the file here and we will load the necessary features later on the fly.
        self.map_local_descriptors = h5py.File(local_features_path, 'r')


    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/pairs_from_retrieval.py
    def load_map_global_features(self, global_features_path:Path):
        print(f"Loading map global features from: {str(global_features_path)}")
        # NOTE(soeroesg): we load all global features into RAM because they are used often
        key="global_descriptor"
        with h5py.File(global_features_path, 'r') as fd:
            desc = [fd[n][key].__array__() for n in self.map_image_names]
        self.map_global_descriptors = torch.from_numpy(np.stack(desc, 0)).float()


    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/extract_features.py
    @torch.no_grad()
    def extract_features_preprocess(self, query_image, preproc_conf={}):
        default_preproc_conf = {
            "globs": ["*.jpg", "*.png", "*.jpeg", "*.JPG", "*.PNG"],
            "grayscale": False,
            "resize_max": None,
            "resize_force": False,
            "interpolation": "cv2_area",  # pil_linear is more accurate but slower
        }
        conf = SimpleNamespace(**{**default_preproc_conf, **preproc_conf})

        # NOTE(seoreosg): added the color conversions
        # this is adapted from hloc.utils.io.read_image()
        if len(query_image.shape) == 3:
            if conf.grayscale:
                image_in = cv2.cvtColor(query_image, cv2.COLOR_BGR2GRAY)
            else:
                image_in = query_image[:, :, ::-1]  # BGR to RGB
        else:
            image_in = query_image

        # convert to float
        image = np.array(image_in).astype(np.float32)
        size = image.shape[:2][::-1]

        if conf.resize_max and (
            conf.resize_force or max(size) > conf.resize_max
        ):
            scale = conf.resize_max / max(size)
            size_new = tuple(int(round(x * scale)) for x in size)
            image = extract_features.resize_image(image, size_new, conf.interpolation)

        if conf.grayscale:
            image = image[None] # shape it 1xHxW
        else:
            image = image.transpose((2, 0, 1))  # HxWxC to CxHxW
        image = image / 255.0

        data = {
            "image": image,
            "original_size": np.array(size)
            # NOTE(soeroesg): if we convert to torch already here, the dimension of original_size will be incorrect later at matching
            #"image": torch.from_numpy(np.array([image])),       # need to wrap into an array and then into a tensor
            #"original_size": torch.from_numpy(np.array([size])) # need to wrap into an array and then into a tensor
        }
        return data


    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/extract_features.py
    @torch.no_grad()
    def extract_features_global(self, data):
        # NOTE(soeroesg): data["image"] must be wrapped into an array and into a tensor
        #pred = self.global_feature_extractor({"image": data["image"].to(self.device, non_blocking=True)})
        pred = self.global_feature_extractor({"image": torch.from_numpy(np.array([data["image"]])).to(self.device, non_blocking=True)})
        pred = {k: v[0].cpu().numpy() for k, v in pred.items()}
        #print(pred)
        key="global_descriptor"
        desc = torch.from_numpy( np.array([pred[key].__array__()]) ).float()
        return desc

    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/extract_features.py
    @torch.no_grad()
    def extract_features_local(self, data):
        # NOTE(soeroesg): data["image"] must be wrapped into an array and into a tensor
        #pred = self.feature_extractor({"image": data["image"].to(self.device, non_blocking=True)}) # original hloc
        pred = self.feature_extractor({"image": torch.from_numpy(np.array([data["image"]])).to(self.device, non_blocking=True)}) # soeroesg
        pred = {k: v[0].cpu().numpy() for k, v in pred.items()}

        # NOTE(soeroesg): data["original_size"] must be wrapped into an array and into a tensor
        #pred["image_size"] = original_size = data["original_size"][0].numpy() # original hloc
        pred["image_size"] = original_size = torch.from_numpy(np.array([data["original_size"]]))[0].numpy() # soeroesg
        if "keypoints" in pred:
            # NOTE(soeroesg): for reading the size, we don't need to wrap it again
            size = np.array(data["image"].shape[-2:][::-1])
            scales = (original_size / size).astype(np.float32)
            pred["keypoints"] = (pred["keypoints"] + 0.5) * scales[None] - 0.5
            if "scales" in pred:
                pred["scales"] *= scales.mean()
            # add keypoint uncertainties scaled to the original resolution
            uncertainty = getattr(self.feature_extractor, "detection_noise", 1) * scales.mean()

        return pred, uncertainty


    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/pairs_from_retrieval.py
    @torch.no_grad()
    def pairs_from_retrieval(self, query_global_descriptor, num_matched=20):
        sim = torch.einsum("id,jd->ij", query_global_descriptor.to(self.device), self.map_global_descriptors.to(self.device))

        invalid = np.full(shape=sim.shape, fill_value=False)
        # NOTE(soeroesg): no self-matching can happen in live case. This must be a matrix with the same size as the similarity scores
        if num_matched > sim.shape[1]:
            num_matched = sim.shape[1] # avoid the case when there are less actually similar images than we requested
        pairs = pairs_from_retrieval.pairs_from_score_matrix(sim, invalid, num_matched, min_score=0)

        #pairs = [(query_names[i], db_names[j]) for i, j in pairs] # original hloc
        pairs = [self.map_image_names[j] for i, j in pairs] # soeroesg: adapted because we have only a single query
        return pairs


    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/match_features.py
    @torch.no_grad()
    def match_features(self, query_features, ref_pairs):

        # code pulled out from FeaturePairsDataset
        results = {}
        for ref_name in ref_pairs:
            data = {}
            grp = query_features
            for k, v in grp.items():
                data[k + "0"] = torch.from_numpy(v.__array__()).float()
            data["image0"] = torch.empty((1,) + tuple(grp["image_size"])[::-1])


            grp = self.map_local_descriptors[ref_name]
            for k, v in grp.items():
                data[k + "1"] = torch.from_numpy(v.__array__()).float()
            data["image1"] = torch.empty((1,) + tuple(grp["image_size"])[::-1])

            # NOTE(soeroesg): we are not using the Torch DataLoader, so we need to wrap them into a tensor ourselves
            data2 = {
                #k: v if k.startswith("image") else v.to(self.device, non_blocking=True) for k, v in data.items() # original hloc
                k: torch.from_numpy(np.array([v])) if k.startswith("image") else torch.from_numpy(np.array([v])).to(self.device, non_blocking=True) for k, v in data.items() # soeroesg
            }
            pred = self.matcher(data2)
            #print(pred)

            # NOTE(soerosg): extract from GPU
            ret = {}
            matches = pred["matches0"][0].cpu().short().numpy()
            ret["matches0"] = matches
            if "matching_scores0" in pred:
                scores = pred["matching_scores0"][0].cpu().half().numpy()
                ret["matching_scores0"] =scores

            # NOTE(soeroesg): instead of writing into a file, we collect and return the results here
            pair = names_to_pair(self.kQueryImageName, ref_name)
            results[pair] = ret

        return results

    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/utils/io.py
    # refactored signature that features are passed instead of file name of features database
    def get_keypoints(self, query_local_descriptors) -> np.ndarray:
        p = query_local_descriptors["keypoints"]
        return p

    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/utils/io.py
    # refactored signature that matches are passed instead of file name of matches database
    def get_matches(self, query_matches, name0: str, name1: str) -> Tuple[np.ndarray]:
        pair = names_to_pair(name0, name1)
        matches = query_matches[pair]["matches0"]
        scores = query_matches[pair]["matching_scores0"]
        idx = np.where(matches != -1)[0]
        matches = np.stack([idx, matches[idx]], -1)
        scores = scores[idx]
        return matches, scores

    # code adapted from https://github.com/cvg/Hierarchical-Localization/blob/master/hloc/localize_sfm.py
    # refactored signature that features and matches are passed instead of file names
    def pose_from_cluster(self,
        localizer: QueryLocalizerNew,
        qname: str,
        query_camera: pycolmap.Camera,
        db_ids: List[int],
        query_local_descriptors,
        query_matches
    ):
        #kpq = get_keypoints(features_path, qname) # original hloc
        kpq = self.get_keypoints(query_local_descriptors) # soeroesg

        kpq += 0.5  # COLMAP coordinates

        kp_idx_to_3D = defaultdict(list)
        kp_idx_to_3D_to_db = defaultdict(lambda: defaultdict(list))
        num_matches = 0
        for i, db_id in enumerate(db_ids):
            image = self.reconstruction.images[db_id]
            if image.num_points3D == 0:
                print(f"No 3D points found for {image.name}.")
                continue
            points3D_ids = np.array(
                [p.point3D_id if p.has_point3D() else -1 for p in image.points2D]
            )

            #matches, _ = get_matches(matches_path, qname, image.name) # original hloc
            matches, _ = self.get_matches(query_matches, qname, image.name) # soeroesg

            matches = matches[points3D_ids[matches[:, 1]] != -1]
            num_matches += len(matches)
            for idx, m in matches:
                id_3D = points3D_ids[m]
                kp_idx_to_3D_to_db[idx][id_3D].append(i)
                # avoid duplicate observations
                if id_3D not in kp_idx_to_3D[idx]:
                    kp_idx_to_3D[idx].append(id_3D)

        idxs = list(kp_idx_to_3D.keys())
        mkp_idxs = [i for i in idxs for _ in kp_idx_to_3D[i]]
        mp3d_ids = [j for i in idxs for j in kp_idx_to_3D[i]]


        # NOTE(soeroesg): pycolmap API changed and the absolute_pose_estimation got removed/renamed.
        # Therefore we cannot simply use the QueryLocalizer, but instead we created QueryLocalizerNew
        ret = localizer.localize(kpq, mkp_idxs, mp3d_ids, query_camera)

        if ret is not None:
            ret["camera"] = query_camera

        # mostly for logging and post-processing
        mkp_to_3D_to_db = [
            (j, kp_idx_to_3D_to_db[i][j]) for i in idxs for j in kp_idx_to_3D[i]
        ]
        log = {
            "db": db_ids,
            "PnP_ret": ret,
            "keypoints_query": kpq[mkp_idxs],
            "points3D_ids": mp3d_ids,
            "points3D_xyz": None,  # we don't log xyz anymore because of file size
            "num_matches": num_matches,
            "keypoint_index_to_db": (mkp_idxs, mkp_to_3D_to_db),
        }
        return ret, log


    # NOTE(soeroesg): new code, inspired by hloc.localize_sfm, but this can run online
    def localize(self, query_image, camera_parameters: CameraParameters) -> GeoPose | None:

        print("Camera model parsing...")
        # NOTE(soeroesg): we do not have EXIF as we do not have a photo file :(
        # camera = pycolmap.infer_camera_from_image(query_image)
        query_camera = self.camera_from_parameters(width=query_image.shape[1], height=query_image.shape[0], camera_parameters=camera_parameters)
        print(query_camera)

        # Local feature extraction
        print("Local feature extraction...")
        if self.feature_conf["preprocessing"] is not None:
            preproc_conf = self.feature_conf["preprocessing"]
        else:
            preproc_conf = {}
        print(preproc_conf)
        query_image_data = self.extract_features_preprocess(query_image, preproc_conf)
        query_local_descriptors, query_local_descriptors_uncertainty = self.extract_features_local(query_image_data)
        #print(query_local_descriptors)
        del query_image_data

        # Global feature extraction (optional)
        print("Global feature extraction (optional)...")
        if self.retrieval_conf is not None:
            if self.retrieval_conf["preprocessing"] is not None:
                preproc_conf = self.retrieval_conf["preprocessing"]
            else:
                preproc_conf = {}
            print(preproc_conf)
            query_image_data = self.extract_features_preprocess(query_image, preproc_conf)
            query_global_descriptor = self.extract_features_global(query_image_data)
            #print(query_global_descriptor)
        del query_image_data

        # Map image retrieval (optional)
        print("Map image retrieval...")
        ref_pairs = []
        if self.retrieval_conf is not None:
            ref_pairs = self.pairs_from_retrieval(query_global_descriptor, 20)
            print(f"Retrieval found {len(ref_pairs)} image pairs in the map.")
        else:
            # NOTE: how do we choose which map frames to match with? Let's use all the db images.
            ref_pairs = [image.name for image in self.reconstruction.images.values()]
            print(f"Skipped retreival, took all {len(ref_pairs)} images from the map.")
        db_names = ref_pairs # use another name to be consistent with the rest of the original code

        # Matches
        print("Local feature matching...")
        query_ref_matches = self.match_features(query_local_descriptors, ref_pairs)
        logs = {
            "preproc_conf": preproc_conf,
            "feature_conf": self.config['feature_conf'],
            "matcher_conf": self.config['matcher_conf'],
            "retrieval_conf": self.config['retrieval_conf'],
            "pairs": ref_pairs,
            "loc": {},
        }

        print("Localization...")
        localizer_conf = {
            'estimation': {'ransac': {'max_error': 12}},
            'refinement': {'refine_focal_length': True, 'refine_extra_params': True},
        }
        # NOTE(soeroesg): pycolmap API changed and the absolute_pose_estimation got removed/renamed.
        # Therefore we cannot simply use the QueryLocalizer, but instead we created QueryLocalizerNew
        localizer = QueryLocalizerNew(self.reconstruction, localizer_conf)

        db_ids = []
        for n in db_names:
            if n not in self.db_name_to_id:
                print(f"WARNING: Image {n} was retrieved but not in database")
                continue
            db_ids.append(self.db_name_to_id[n])

        cam_from_world = {}
        qname = self.kQueryImageName
        if self.covisibility_clustering:
            clusters = do_covisibility_clustering(db_ids, self.reconstruction)
            best_inliers = 0
            best_cluster = None
            logs_clusters = []
            for i, cluster_ids in enumerate(clusters):
                #ret, log = pose_from_cluster(lcalizer, qname, qcam, cluster_ids, features_path, matches_path) # original hloc
                ret, log = self.pose_from_cluster(localizer, qname, query_camera, cluster_ids, query_local_descriptors, query_ref_matches) # soeroesg
                if ret is not None and ret["num_inliers"] > best_inliers:
                    best_cluster = i
                    best_inliers = ret["num_inliers"]
                logs_clusters.append(log)
            if best_cluster is not None:
                ret = logs_clusters[best_cluster]["PnP_ret"]
                cam_from_world[qname] = ret["cam_from_world"]
                print(f'Found {ret["num_inliers"]} inlier correspondences for query {qname}.')

                # Reject if too few inlier points
                kMinNumInliers = 20
                if ret["num_inliers"] < kMinNumInliers:
                    print(f'Rejecting solution due to low number of inliers')
                    return None

            logs["loc"][qname] = {
                "db": db_ids,
                "best_cluster": best_cluster,
                "log_clusters": logs_clusters,
                "covisibility_clustering": self.covisibility_clustering,
            }
        else:
            #ret, log = pose_from_cluster(localizer, qname, qcam, db_ids, features_path, matches_path) # original hloc
            ret, log = self.pose_from_cluster(localizer, qname, query_camera, db_ids, query_local_descriptors, query_ref_matches) # soeroesg
            if ret is not None:
                cam_from_world[qname] = ret["cam_from_world"]
            else:
                closest = self.reconstruction.images[db_ids[0]]
                cam_from_world[qname] = closest.cam_from_world
            log["covisibility_clustering"] = self.covisibility_clustering
            logs["loc"][qname] = log

        if self.debug:
            print(logs)
            # For debugging purposes, we visualize the query camera pose in the point cloud map
            # We create a copy of the map point cloud, insert the query image into it, and export it in colmap format
            map_dir = Path(self.config['reconstruction_path'])
            images_dir = Path(self.config['image_path'])
            test_model_dir = map_dir.parent.joinpath('test_model')
            import os
            os.makedirs(str(test_model_dir), exist_ok=True)
            test_model = pycolmap.Reconstruction(map_dir)
            test_model.write_text(test_model_dir)
            test_model_images_txt_path = test_model_dir / 'images.txt'
            cv2.imwrite(str(test_model_dir/'query.png'), query_image)
            print(f"Writing poses to {str(test_model_images_txt_path)}...")
            with open(str(test_model_images_txt_path), "w") as f:
                for query, t in cam_from_world.items():
                    qvec = " ".join(map(str, t.rotation.quat[[3, 0, 1, 2]]))
                    tvec = " ".join(map(str, t.translation))
                    name = query.split("/")[-1]
                    f.write(f"1 {qvec} {tvec} 1 {name}\n\n")

        geoPoses = [] # sometimes we get multiple hypotheses
        for qname, t in cam_from_world.items():
            # Note: t is of type pycolmap.Rigid3d
            pose_c2m = np.eye(4)
            pose_c2m[:3,:4] = t.inverse().matrix()

            if self.debug:
                tvec_c2m = pose_c2m[:3,3]
                print(f"tvec_map: {tvec_c2m}")
                euler_c2m = Rotation.from_matrix(pose_c2m[:3,:3]).as_euler(seq='xyz', degrees=True)
                print(f"euler_map: {euler_c2m}")

            # Multiply with map to ENU transform
            pose_c2enu = np.matmul(self.map_to_ENU_transform, pose_c2m)
            tvec_enu = pose_c2enu[:3,3]
            #quat_enu = Rotation.from_matrix(pose_c2enu[:3,:3]).as_quat() # This is still in vision convention, camera looking upwards
            # We have to convert the orientation from computer vision (X right, Y down, Z forward) to robotics convention (X forward, Y left, Z up)
            rot_enu_cv = Rotation.from_matrix(pose_c2enu[:3,:3])
            rot_cv_to_rob = Rotation.from_matrix([
                [0.0,-1.0, 0.0],
                [0.0, 0.0,-1.0],
                [1.0, 0.0, 0.0]
            ])
            rot_enu_rob = rot_enu_cv * rot_cv_to_rob
            quat_enu = rot_enu_rob.as_quat()

            if self.debug:
                print(f"tvec_enu: {tvec_enu}")
                print(f"quat_enu: {quat_enu}")
                euler_enu = Rotation.from_quat(quat_enu).as_euler(seq='xyz', degrees=True)
                print(f"euler_enu: {euler_enu}")

            # convert to geopose using the reference position of the map
            lat, lon, h = enu_to_geodetic(tvec_enu[0], tvec_enu[1], tvec_enu[2],
                    self.map_geodetic_ref.lat, self.map_geodetic_ref.lon, self.map_geodetic_ref.h)

            geoPose = GeoPose(position=Position(lat, lon, h), quaternion=Quaternion(quat_enu[0], quat_enu[1], quat_enu[2], quat_enu[3]))
            geoPoses.append(geoPose)

        if len(geoPoses) == 0:
            return None
        print(f"Found {len(geoPoses)} pose hypotheses. Returning the first one.")
        return geoPoses[0]
