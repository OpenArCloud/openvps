/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useState } from "react";
import Map from "react-map-gl/dist/esm/exports-maplibre.js";
import { Canvas as MapLibreCanvas } from "react-three-map/dist/maplibre/es/main.mjs";
import { PLYLoader } from "three-stdlib";
import { Euler, Matrix4, Points, PointsMaterial, Quaternion, Vector3 } from "three";
import { useMap } from "react-three-map";
import { PivotControls } from "./pivotcontrols";
import { MAX_PROGRESS } from "./page";

export default function ThreeJsViewer({
  url,
  latitude,
  longitude,
  onPick,
  position,
  setPosition,
  rotation,
  setRotation,
  scale,
  pointSize,
  setProgress,
  debugGeoPose,
}) {
  //console.log(session);
  const darkMode = useDarkMode();
  const mapStyleUrl = darkMode
    ? "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
    : "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

  const [viewState, setViewState] = useState({
    longitude,
    latitude,
    zoom: 19,
    pitch: 30,
  });

  useEffect(() => {
    setViewState((viewState) => {
      return {
        ...viewState,
        longitude,
        latitude,
      };
    });
  }, [longitude, latitude]);

  return (
    <div style={{ height: "100%" }}>
      <Map
        antialias
        {...viewState}
        maxPitch={85}
        mapStyle={mapStyleUrl}
        onMove={(evt) => setViewState(evt.viewState)}
        onMouseDown={(event) => onPick(event)}
      >
        {debugGeoPose ? (
          <MapLibreCanvas latitude={debugGeoPose.position.lat} longitude={debugGeoPose.position.lon}>
            <group rotate-x={-Math.PI / 2}>
              <hemisphereLight args={["#ffffff", "#60666C"]} position={[1, 4.5, 3]} />
              <DebugPly quaternion={debugGeoPose.quaternion} />
            </group>
          </MapLibreCanvas>
        ) : (
          <MapLibreCanvas latitude={latitude} longitude={longitude}>
            <group>
              <hemisphereLight args={["#ffffff", "#60666C"]} position={[1, 4.5, 3]} />
              <PlyObject
                url={url}
                position={position}
                rotation={rotation}
                scale={scale}
                setPosition={setPosition}
                setRotation={setRotation}
                pointSize={pointSize}
                setProgress={setProgress}
              />
            </group>
          </MapLibreCanvas>
        )}
      </Map>
    </div>
  );
}

function DebugPly(props) {
  const quaternion = [props.quaternion.x, props.quaternion.y, props.quaternion.z, props.quaternion.w];

  // PivotControls needs the matrix to be changed, quaternion is not enough
  const matrix = new Matrix4().compose(
    new Vector3(0, 0, 0),
    new Quaternion(...quaternion),
    new Vector3(1, 1, 1)
  );

  return (
    <>
      <PivotControls
        fixed
        scale={150}
        disableScaling
        depthTest={false}
        matrix={matrix}
        autoTransform={false}
      >
        <mesh>
          <boxGeometry args={[1, 1, 1]} />
          <meshBasicMaterial color={0x00ff00} />
        </mesh>
      </PivotControls>
    </>
  );
}

function PlyObject({
  url,
  position,
  setPosition,
  rotation,
  setRotation,
  scale,
  pointSize,
  setProgress,
}) {
  const [ply, setPly] = useState(null);

  const map = useMap();

  useEffect(() => {
    console.log("LOADING");
    setProgress(0);
    const loader = new PLYLoader();
    loader.load(
      url,
      function (geometry) {
        geometry.computeVertexNormals();
        const material = new PointsMaterial({ size: pointSize, vertexColors: true });
        const mesh = new Points(geometry, material);
        console.log("LOADED");
        setPly(mesh);
        setProgress(MAX_PROGRESS);
      },
      (xhr) => {
        console.log((xhr.loaded / xhr.total) * 100 + "% loaded");
        setProgress(xhr.loaded / xhr.total);
      },
      (error) => {
        console.log(error);
      }
    );
  }, [url, pointSize]);

  const onDragStart = useCallback(() => {
    map.dragPan.disable();
    map.dragRotate.disable();
  }, [map]);
  const onDragEnd = useCallback(() => {
    map.dragPan.enable();
    map.dragRotate.enable();
  }, [map]);

  const onDrag = useCallback(
    /** @param {Matrix4} m4 */
    (m4) => {
      const position = new Vector3();
      const quaternion = new Quaternion();
      const scale = new Vector3();
      m4.decompose(position, quaternion, scale);
      const euler = new Euler().setFromQuaternion(quaternion);
      setPosition(position);
      setRotation(euler);
    },
    []
  );

  const matrix = new Matrix4().compose(
    position,
    new Quaternion().setFromEuler(rotation),
    new Vector3(scale, scale, scale)
  );

  return (
    <>
      <PivotControls
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDrag={onDrag}
        fixed
        scale={150}
        disableScaling
        depthTest={false}
        matrix={matrix}
        autoTransform={false}
      >
        {ply && <primitive object={ply} />}
      </PivotControls>
    </>
  );
}

const useDarkMode = () => {
  const getCurrentTheme = () => window.matchMedia("(prefers-color-scheme: dark)").matches;
  const [isDarkTheme, setIsDarkTheme] = useState(getCurrentTheme());
  const mqListener = (e) => {
    setIsDarkTheme(e.matches);
  };

  useEffect(() => {
    const darkThemeMq = window.matchMedia("(prefers-color-scheme: dark)");
    darkThemeMq.addEventListener("change", mqListener);
    return () => darkThemeMq.removeEventListener("change", mqListener);
  }, []);
  return isDarkTheme;
};
