/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import { useFrame, useThree } from "@react-three/fiber";
import * as React from "react";
import * as THREE from "three";
import { AxisArrow } from "@react-three/drei/web/pivotControls/AxisArrow";
import { PlaneSlider } from "@react-three/drei/web/pivotControls/PlaneSlider";
import { ScalingSphere } from "@react-three/drei/web/pivotControls/ScalingSphere";
import { context } from "@react-three/drei/web/pivotControls/context";
import { calculateScaleFactor, Html, Line } from "@react-three/drei";
const mL0 = /* @__PURE__ */ new THREE.Matrix4();
const mW0 = /* @__PURE__ */ new THREE.Matrix4();
const mP = /* @__PURE__ */ new THREE.Matrix4();
const mPInv = /* @__PURE__ */ new THREE.Matrix4();
const mW = /* @__PURE__ */ new THREE.Matrix4();
const mL = /* @__PURE__ */ new THREE.Matrix4();
const mL0Inv = /* @__PURE__ */ new THREE.Matrix4();
const mdL = /* @__PURE__ */ new THREE.Matrix4();
const mG = /* @__PURE__ */ new THREE.Matrix4();
const bb = /* @__PURE__ */ new THREE.Box3();
const bbObj = /* @__PURE__ */ new THREE.Box3();
const vCenter = /* @__PURE__ */ new THREE.Vector3();
const vSize = /* @__PURE__ */ new THREE.Vector3();
const vAnchorOffset = /* @__PURE__ */ new THREE.Vector3();
const vPosition = /* @__PURE__ */ new THREE.Vector3();
const vScale = /* @__PURE__ */ new THREE.Vector3();
const xDir = /* @__PURE__ */ new THREE.Vector3(1, 0, 0);
const yDir = /* @__PURE__ */ new THREE.Vector3(0, 1, 0);
const zDir = /* @__PURE__ */ new THREE.Vector3(0, 0, 1);
export const PivotControls = /* @__PURE__ */ React.forwardRef(
  (
    {
      enabled = true,
      matrix,
      onDragStart,
      onDrag,
      onDragEnd,
      autoTransform = true,
      anchor,
      disableAxes = false,
      disableSliders = false,
      disableRotations = false,
      disableScaling = false,
      activeAxes = [true, true, true],
      offset = [0, 0, 0],
      rotation = [0, 0, 0],
      scale = 1,
      lineWidth = 4,
      fixed = false,
      translationLimits,
      rotationLimits,
      scaleLimits,
      depthTest = true,
      axisColors = ["#ff2060", "#20df80", "#2080ff"],
      hoveredColor = "#ffff40",
      annotations = false,
      annotationsClass,
      opacity = 1,
      visible = true,
      userData,
      children,
      ...props
    },
    fRef
  ) => {
    const invalidate = useThree((state) => state.invalidate);
    const parentRef = React.useRef(null);
    const ref = React.useRef(null);
    const gizmoRef = React.useRef(null);
    const childrenRef = React.useRef(null);
    const translation = React.useRef([0, 0, 0]);
    const cameraScale = React.useRef(new THREE.Vector3(1, 1, 1));
    const gizmoScale = React.useRef(new THREE.Vector3(1, 1, 1));
    React.useLayoutEffect(() => {
      if (!anchor) return;
      childrenRef.current.updateWorldMatrix(true, true);
      mPInv.copy(childrenRef.current.matrixWorld).invert();
      bb.makeEmpty();
      childrenRef.current.traverse((obj) => {
        if (!obj.geometry) return;
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
        mL.copy(obj.matrixWorld).premultiply(mPInv);
        bbObj.copy(obj.geometry.boundingBox);
        bbObj.applyMatrix4(mL);
        bb.union(bbObj);
      });
      vCenter.copy(bb.max).add(bb.min).multiplyScalar(0.5);
      vSize.copy(bb.max).sub(bb.min).multiplyScalar(0.5);
      vAnchorOffset
        .copy(vSize)
        .multiply(new THREE.Vector3(...anchor))
        .add(vCenter);
      vPosition.set(...offset).add(vAnchorOffset);
      gizmoRef.current.position.copy(vPosition);
      invalidate();
    });
    const config = React.useMemo(
      () => ({
        onDragStart: (props) => {
          mL0.copy(ref.current.matrix);
          mW0.copy(ref.current.matrixWorld);
          onDragStart && onDragStart(props);
          invalidate();
        },
        onDrag: (mdW) => {
          mP.copy(parentRef.current.matrixWorld);
          mPInv.copy(mP).invert();
          // After applying the delta
          mW.copy(mW0).premultiply(mdW);
          mL.copy(mW).premultiply(mPInv);
          mL0Inv.copy(mL0).invert();
          mdL.copy(mL).multiply(mL0Inv);
          if (autoTransform) {
            ref.current.matrix.copy(mL);
          }
          onDrag && onDrag(mL, mdL, mW, mdW);
          invalidate();
        },
        onDragEnd: () => {
          if (onDragEnd) onDragEnd();
          invalidate();
        },
        translation,
        translationLimits,
        rotationLimits,
        axisColors,
        hoveredColor,
        opacity,
        scale,
        lineWidth,
        fixed,
        depthTest,
        userData,
        annotations,
        annotationsClass,
      }),
      [
        onDragStart,
        onDrag,
        onDragEnd,
        translation,
        translationLimits,
        rotationLimits,
        scaleLimits,
        depthTest,
        scale,
        lineWidth,
        fixed,
        ...axisColors,
        hoveredColor,
        opacity,
        userData,
        autoTransform,
        annotations,
        annotationsClass,
      ]
    );
    const vec = new THREE.Vector3();
    useFrame((state) => {
      if (fixed) {
        const sf = calculateScaleFactor(
          gizmoRef.current.getWorldPosition(vec),
          scale,
          state.camera,
          state.size
        );
        cameraScale.current.setScalar(sf);
      }
      if (matrix && matrix instanceof THREE.Matrix4) {
        ref.current.matrix = matrix;
      }
      // Update gizmo scale in accordance with matrix changes
      // Without this, there might be noticable turbulences if scaling happens fast enough
      ref.current.updateWorldMatrix(true, true);
      mG.makeRotationFromEuler(gizmoRef.current.rotation)
        .setPosition(gizmoRef.current.position)
        .premultiply(ref.current.matrixWorld);
      gizmoScale.current.setFromMatrixScale(mG);
      vScale.copy(cameraScale.current).divide(gizmoScale.current);
      if (
        Math.abs(gizmoRef.current.scale.x - vScale.x) > 1e-4 ||
        Math.abs(gizmoRef.current.scale.y - vScale.y) > 1e-4 ||
        Math.abs(gizmoRef.current.scale.z - vScale.z) > 1e-4
      ) {
        gizmoRef.current.scale.copy(vScale);
        state.invalidate();
      }
    });
    React.useImperativeHandle(fRef, () => ref.current, []);
    return (
      <context.Provider value={config}>
        <group ref={parentRef}>
          <group ref={ref} matrix={matrix} matrixAutoUpdate={false} {...props}>
            <group visible={visible} ref={gizmoRef} position={offset} rotation={rotation}>
              {enabled && (
                <>
                  {!disableAxes && activeAxes[0] && <AxisArrow axis={0} direction={xDir} />}
                  {!disableAxes && activeAxes[1] && <AxisArrow axis={1} direction={yDir} />}
                  {!disableAxes && activeAxes[2] && <AxisArrow axis={2} direction={zDir} />}
                  {!disableSliders && activeAxes[0] && activeAxes[1] && (
                    <PlaneSlider axis={2} dir1={xDir} dir2={yDir} />
                  )}
                  {!disableSliders && activeAxes[0] && activeAxes[2] && (
                    <PlaneSlider axis={1} dir1={zDir} dir2={xDir} />
                  )}
                  {!disableSliders && activeAxes[2] && activeAxes[1] && (
                    <PlaneSlider axis={0} dir1={yDir} dir2={zDir} />
                  )}
                  {!disableRotations && activeAxes[0] && activeAxes[1] && (
                    <AxisRotator axis={2} dir1={xDir} dir2={yDir} />
                  )}
                  {!disableRotations && activeAxes[0] && activeAxes[2] && (
                    <AxisRotator axis={1} dir1={zDir} dir2={xDir} />
                  )}
                  {!disableRotations && activeAxes[2] && activeAxes[1] && (
                    <AxisRotator axis={0} dir1={yDir} dir2={zDir} />
                  )}
                  {!disableScaling && activeAxes[0] && <ScalingSphere axis={0} direction={xDir} />}
                  {!disableScaling && activeAxes[1] && <ScalingSphere axis={1} direction={yDir} />}
                  {!disableScaling && activeAxes[2] && <ScalingSphere axis={2} direction={zDir} />}
                </>
              )}
            </group>
            <group ref={childrenRef}>{children}</group>
          </group>
        </group>
      </context.Provider>
    );
  }
);
const clickDir = /* @__PURE__ */ new THREE.Vector3();
const intersectionDir = /* @__PURE__ */ new THREE.Vector3();
const toDegrees = (radians) => (radians * 180) / Math.PI;
const toRadians = (degrees) => (degrees * Math.PI) / 180;
const calculateAngle = (clickPoint, intersectionPoint, origin, e1, e2) => {
  clickDir.copy(clickPoint).sub(origin);
  intersectionDir.copy(intersectionPoint).sub(origin);
  const dote1e1 = e1.dot(e1);
  const dote2e2 = e2.dot(e2);
  const uClick = clickDir.dot(e1) / dote1e1;
  const vClick = clickDir.dot(e2) / dote2e2;
  const uIntersection = intersectionDir.dot(e1) / dote1e1;
  const vIntersection = intersectionDir.dot(e2) / dote2e2;
  const angleClick = Math.atan2(vClick, uClick);
  const angleIntersection = Math.atan2(vIntersection, uIntersection);
  return angleIntersection - angleClick;
};
const fmod = (num, denom) => {
  let k = Math.floor(num / denom);
  k = k < 0 ? k + 1 : k;
  return num - k * denom;
};
const minimizeAngle = (angle) => {
  let result = fmod(angle, 2 * Math.PI);
  if (Math.abs(result) < 1e-6) {
    return 0.0;
  }
  if (result < 0.0) {
    result += 2 * Math.PI;
  }
  return result;
};
const rotMatrix = /* @__PURE__ */ new THREE.Matrix4();
const posNew = /* @__PURE__ */ new THREE.Vector3();
const ray = /* @__PURE__ */ new THREE.Ray();
const intersection = /* @__PURE__ */ new THREE.Vector3();
export const AxisRotator = ({ dir1, dir2, axis }) => {
  const {
    rotationLimits,
    annotations,
    annotationsClass,
    depthTest,
    scale,
    lineWidth,
    fixed,
    axisColors,
    hoveredColor,
    opacity,
    onDragStart,
    onDrag,
    onDragEnd,
    userData,
  } = React.useContext(context);
  // @ts-expect-error new in @react-three/fiber@7.0.5
  const camControls = useThree((state) => state.controls);
  const divRef = React.useRef(null);
  const objRef = React.useRef(null);
  const angle0 = React.useRef(0);
  const angle = React.useRef(0);
  const clickInfo = React.useRef(null);
  const [isHovered, setIsHovered] = React.useState(false);
  const onPointerDown = React.useCallback(
    (e) => {
      if (annotations) {
        divRef.current.innerText = `${toDegrees(angle.current).toFixed(0)}º`;
        divRef.current.style.display = "block";
      }
      e.stopPropagation();
      const clickPoint = e.point.clone();
      const origin = new THREE.Vector3().setFromMatrixPosition(objRef.current.matrixWorld);
      const e1 = new THREE.Vector3().setFromMatrixColumn(objRef.current.matrixWorld, 0).normalize();
      const e2 = new THREE.Vector3().setFromMatrixColumn(objRef.current.matrixWorld, 1).normalize();
      const normal = new THREE.Vector3().setFromMatrixColumn(objRef.current.matrixWorld, 2).normalize();
      const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, origin);
      clickInfo.current = { clickPoint, origin, e1, e2, normal, plane };
      onDragStart({ component: "Rotator", axis, origin, directions: [e1, e2, normal] });
      camControls && (camControls.enabled = false);
      // @ts-ignore
      e.target.setPointerCapture(e.pointerId);
    },
    [annotations, camControls, onDragStart, axis]
  );
  const onPointerMove = React.useCallback(
    (e) => {
      e.stopPropagation();
      if (!isHovered) setIsHovered(true);
      if (clickInfo.current) {
        const { clickPoint, origin, e1, e2, normal, plane } = clickInfo.current;
        const [min, max] = rotationLimits?.[axis] || [undefined, undefined];
        ray.copy(e.ray);
        ray.intersectPlane(plane, intersection);
        ray.direction.negate();
        ray.intersectPlane(plane, intersection);
        let deltaAngle = calculateAngle(clickPoint, intersection, origin, e1, e2);
        let degrees = toDegrees(deltaAngle);
        // @ts-ignore
        if (e.shiftKey) {
          degrees = Math.round(degrees / 10) * 10;
          deltaAngle = toRadians(degrees);
        }
        if (min !== undefined && max !== undefined && max - min < 2 * Math.PI) {
          deltaAngle = minimizeAngle(deltaAngle);
          deltaAngle = deltaAngle > Math.PI ? deltaAngle - 2 * Math.PI : deltaAngle;
          deltaAngle = THREE.MathUtils.clamp(deltaAngle, min - angle0.current, max - angle0.current);
          angle.current = angle0.current + deltaAngle;
        } else {
          angle.current = minimizeAngle(angle0.current + deltaAngle);
          angle.current = angle.current > Math.PI ? angle.current - 2 * Math.PI : angle.current;
        }
        if (annotations) {
          degrees = toDegrees(angle.current);
          divRef.current.innerText = `${degrees.toFixed(0)}º`;
        }
        rotMatrix.makeRotationAxis(normal, deltaAngle);
        posNew.copy(origin).applyMatrix4(rotMatrix).sub(origin).negate();
        rotMatrix.setPosition(posNew);
        onDrag(rotMatrix);
      }
    },
    [annotations, onDrag, isHovered, rotationLimits, axis]
  );
  const onPointerUp = React.useCallback(
    (e) => {
      if (annotations) {
        divRef.current.style.display = "none";
      }
      e.stopPropagation();
      angle0.current = angle.current;
      clickInfo.current = null;
      onDragEnd();
      camControls && (camControls.enabled = true);
      // @ts-ignore
      e.target.releasePointerCapture(e.pointerId);
    },
    [annotations, camControls, onDragEnd]
  );
  const onPointerOut = React.useCallback((e) => {
    e.stopPropagation();
    setIsHovered(false);
  }, []);
  const matrixL = React.useMemo(() => {
    const dir1N = dir1.clone().normalize();
    const dir2N = dir2.clone().normalize();
    return new THREE.Matrix4().makeBasis(dir1N, dir2N, dir1N.clone().cross(dir2N));
  }, [dir1, dir2]);
  const r = fixed ? 0.65 : scale * 0.65;
  const arc = React.useMemo(() => {
    const segments = 32;
    const points = [];
    for (let j = 0; j <= segments; j++) {
      const angle = (j * (Math.PI / 2)) / segments;
      points.push(new THREE.Vector3(Math.cos(angle) * r, Math.sin(angle) * r, 0));
    }
    return points;
  }, [r]);
  const hitboxWidth = lineWidth * (fixed ? 0.015 : 0.1);
  return (
    <group
      ref={objRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerOut={onPointerOut}
      matrix={matrixL}
      matrixAutoUpdate={false}
    >
      {annotations && (
        <Html position={[r, r, 0]}>
          <div
            style={{
              display: "none",
              background: "#151520",
              color: "white",
              padding: "6px 8px",
              borderRadius: 7,
              whiteSpace: "nowrap",
            }}
            className={annotationsClass}
            ref={divRef}
          />
        </Html>
      )}
      {/* The invisible mesh being raycast */}
      {/*<Line points={arc} lineWidth={lineWidth * 4} visible={false} userData={userData} />*/}
      <mesh visible={false} userData={userData}>
        <torusGeometry args={[r, hitboxWidth, 6, 6, Math.PI / 2]} />
      </mesh>
      {/* The visible mesh */}
      <Line
        transparent
        raycast={() => null}
        depthTest={depthTest}
        points={arc}
        lineWidth={lineWidth}
        side={THREE.DoubleSide}
        color={isHovered ? hoveredColor : axisColors[axis]}
        opacity={opacity}
        polygonOffset
        polygonOffsetFactor={-10}
        fog={false}
      />
    </group>
  );
};
