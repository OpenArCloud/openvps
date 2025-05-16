/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { Vector3, Matrix4, Euler, Quaternion } from "three";
import dynamic from "next/dynamic";
import { SessionProvider, signOut } from "next-auth/react";
import { useSearchParams } from "next/navigation.js";
import { Allotment } from "allotment";

export const MAX_PROGRESS = 1.2;

// Disable SSR to speed up page load
const ThreeJsViewer = dynamic(() => import("./viewer.js"), { ssr: false });

/**
 * @param {number[]} seq
 * @returns {number[][]}
 */
function reshape4x4(seq) {
  const output = [];
  for (let i = 0; i < seq.length; i += 4) {
    const row = JSON.parse(JSON.stringify(seq.slice(i, i + 4)));
    output.push(row);
  }
  return output;
}

/** @typedef {{matrix:number[][], longitude:number, latitude:number, height:number}} Data */

/** @typedef {{id: string, name: string, size:number}} DataSet */

export default function Matcher() {
  const [translation, setTranslation] = useState(new Vector3());
  const [rotation, setRotation] = useState(new Euler());
  const [scale, setScale] = useState(1);
  const [pointSize, setPointSize] = useState(1);
  const [progress, setProgress] = useState(0);

  const initialLatitude = parseFloat(process.env.NEXT_PUBLIC_DEFAULT_LATITUDE);
  const initialLongitude = parseFloat(process.env.NEXT_PUBLIC_DEFAULT_LONGITUDE);
  const initialHeight = parseFloat(process.env.NEXT_PUBLIC_DEFAULT_HEIGHT ?? "0");

  const [latitude, setLatitude] = useState(initialLatitude);
  const [longitude, setLongitude] = useState(initialLongitude);
  const [height, setHeight] = useState(initialHeight);

  const [refMouseEnabled, setRefMouseEnabled] = useState(false);

  /** @type {ReturnType<typeof useState<DataSet[]>>} */
  const [maps, setMaps] = useState([]);
  const [selectedMap, setSelectedMap] = useState(null);

  const [debugGeoPose, setDebugGeoPose] = useState(null);

  const [modified, setModified] = useState(false);

  const watchedStates = useRef([translation, rotation, scale, latitude, longitude]);

  useEffect(() => {
    const currentState = [translation, rotation, scale, latitude, longitude];
    if (watchedStates.current.some((value, index) => value !== currentState[index])) {
      if (progress === MAX_PROGRESS) {
        setModified(true);
      }
      watchedStates.current = [translation, rotation, scale, latitude, longitude];
    }
  }, [translation, rotation, scale, longitude, latitude, progress]);

  useEffect(() => {
    function onBeforeUnload(e) {
      if (modified) {
        e.preventDefault();
        e.returnValue = "";
        return;
      }

      delete e["returnValue"];
    }

    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [modified]);

  useEffect(() => {
    (async () => {
      try {
        /** @type {DataSet[]} */
        const dataQuery = await fetch(`/api/maps`, {
          credentials: "include",
        });
        if (dataQuery.ok) {
          const data = await dataQuery.json();
          setMaps(data);
        } else {
          console.error(await dataQuery.text());
        }
      } catch (error) {
        console.error(error);
      }
    })();
  }, []);

  function pickReference(event) {
    if (refMouseEnabled) {
      const { lat, lng } = event.lngLat;
      setLongitude(lng);
      setLatitude(lat);
      document.getElementById("poi-selector").value = "custom";
      setRefMouseEnabled(false);
    }
  }

  console.log("longitude", longitude);
  console.log("latitude", latitude);
  console.log("translation", translation);
  console.log("rotatiton", rotation);
  console.log("scale", scale);

  const matrix = new Matrix4().compose(
    translation,
    new Quaternion().setFromEuler(rotation),
    new Vector3(scale, scale, scale)
  );
  const matrix4x4 = reshape4x4(matrix.clone().transpose().toArray());
  console.log("matrix4x4", matrix4x4);

  // prettier-ignore
  const output = JSON.stringify(
    {
      latitude,
      longitude,
      height,
      matrix: matrix4x4
    },
    null,
    2
  );

  async function save() {
    if (!selectedMap) {
      console.error("No map selected");
      return;
    }
    console.log(output);
    const params = new URLSearchParams({ type: selectedMap.type, dataSetId: selectedMap.dataSetId });
    const saveQuery = await fetch(`/api/maps/${selectedMap.id}/transform?${params}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: output,
    });
    if (saveQuery.ok) {
      alert("Saved");
      setModified(false);
    } else {
      const error = await saveQuery.text();
      console.error("Could not upload transformation matrix:", error);
    }
  }

  useEffect(() => {
    setProgress(0);
    setModified(false);
    if (!selectedMap) {
      return;
    }
    (async () => {
      try {
        const params = new URLSearchParams({ type: selectedMap.type, dataSetId: selectedMap.dataSetId });
        /** @type {Data} */
        const data = await fetch(`/api/maps/${selectedMap.id}/transform?${params}`, {
          credentials: "include",
        }).then((response) => response.json());

        setLatitude(data.latitude);
        setLongitude(data.longitude);
        setHeight(data.height);
        const matrix = new Matrix4().fromArray(data.matrix.flat()).transpose();
        const position = new Vector3();
        const quaternion = new Quaternion();
        const scale = new Vector3();
        matrix.decompose(position, quaternion, scale);
        setTranslation(position);
        setRotation(new Euler().setFromQuaternion(quaternion));
        setScale(scale.x);
      } catch (error) {
        console.error(error);
      }
    })();
  }, [selectedMap]);

  let pointCloudUrl;
  if (selectedMap) {
    const params = new URLSearchParams({ type: selectedMap.type, dataSetId: selectedMap.dataSetId });
    pointCloudUrl = `/api/maps/${selectedMap.id}?${params}`;
  } else {
    pointCloudUrl = "";
  }

  return (
    <div className="h-screen">
      <Allotment>
        <Allotment.Pane minSize={200} preferredSize={400}>
          <div className="h-screen overflow-auto">
            <div className="p-2">
              <div className="form-control gap-2">
                <Suspense fallback={null}>
                  <LoadFile
                    maps={maps}
                    selectedMap={selectedMap}
                    setSelectedMap={setSelectedMap}
                    progress={progress}
                    modified={modified}
                  />
                </Suspense>
                <LoadConfig
                  setTranslation={setTranslation}
                  setRotation={setRotation}
                  setScale={setScale}
                  setLatitude={setLatitude}
                  setLongitude={setLongitude}
                />
                <details className="collapse collapse-arrow border border-base-300 dark:border-neutral">
                  <summary className="collapse-title">Set reference origin</summary>
                  <div className="collapse-content flex flex-col gap-2">
                    <ReferenceInput
                      longitude={longitude}
                      latitude={latitude}
                      height={height}
                      setLongitude={setLongitude}
                      setLatitude={setLatitude}
                      setHeight={setHeight}
                    />
                    <ReferenceMouse enabled={refMouseEnabled} setEnabled={setRefMouseEnabled} />
                  </div>
                </details>
                <details className="collapse collapse-arrow border border-base-300 dark:border-neutral">
                  <summary className="collapse-title">Change transform values</summary>
                  <div className="collapse-content flex flex-col gap-2">
                    <TranslationInput
                      component="x"
                      componentIndex={0}
                      translation={translation}
                      setTranslation={setTranslation}
                    />
                    <TranslationInput
                      component="y"
                      componentIndex={1}
                      translation={translation}
                      setTranslation={setTranslation}
                    />
                    <TranslationInput
                      component="z"
                      componentIndex={2}
                      translation={translation}
                      setTranslation={setTranslation}
                    />
                    <RotationInput component="x" rotation={rotation} setRotation={setRotation} />
                    <RotationInput component="y" rotation={rotation} setRotation={setRotation} />
                    <RotationInput component="z" rotation={rotation} setRotation={setRotation} />
                    <TransformInput
                      title="Scale"
                      value={scale}
                      setter={setScale}
                      min={0.1}
                      max={5}
                      step={0.01}
                    />
                    <TransformInput
                      title="Point Size"
                      value={pointSize}
                      setter={setPointSize}
                      min={1}
                      max={6}
                      step={1}
                    />
                  </div>
                </details>
                Matrix:
                <MatrixTable matrix4x4={matrix4x4} />
                <JsonOutput output={output} save={save} />
                {/* <DebugGeoPose debugGeoPose={debugGeoPose} setDebugGeoPose={setDebugGeoPose} /> */}
                <button onClick={() => signOut()} className="btn btn-accent">
                  Sign out
                </button>
              </div>
            </div>
          </div>
        </Allotment.Pane>
        <Allotment.Pane minSize={200}>
          <div className="h-screen relative min-w-96">
            <SessionProvider>
              <ThreeJsViewer
                url={pointCloudUrl}
                latitude={latitude}
                longitude={longitude}
                onPick={pickReference}
                position={translation}
                rotation={rotation}
                scale={scale}
                setPosition={setTranslation}
                setRotation={setRotation}
                pointSize={pointSize}
                setProgress={setProgress}
                debugGeoPose={debugGeoPose}
              />
            </SessionProvider>
          </div>
        </Allotment.Pane>
      </Allotment>
    </div>
  );
}

function LoadFile({ maps, selectedMap, setSelectedMap, progress, modified }) {
  const defaultId = useSearchParams().get("id");

  function setSelectedMapTo(id) {
    console.log("Changing map to ", id);
    setSelectedMap(maps.find((map) => map.id === id) ?? null);
  }

  useEffect(() => {
    if (defaultId) {
      setSelectedMapTo(defaultId);
    }
  }, [defaultId, maps]);

  return (
    <>
      <div>
        <div className="indicator w-full">
          {modified && <span className="indicator-item badge badge-primary badge-xs"></span>}
          <select
            onChange={(event) => setSelectedMapTo(event.target.value)}
            value={selectedMap?.id || ""}
            className={"select select-bordered w-full"}
          >
            <option value="">Choose map</option>
            {maps.map((map) => (
              <option value={map.id} key={map.id}>
                {map.name}
              </option>
            ))}
          </select>
        </div>
        <progress
          className="progress progress-primary w-full"
          value={progress}
          max={MAX_PROGRESS}
        ></progress>
      </div>
    </>
  );
}

function LoadConfig({ setTranslation, setRotation, setScale, setLatitude, setLongitude }) {
  const textArea = useRef(null);
  function load() {
    /** @type {Data} */
    const input = JSON.parse(textArea.current.value);
    const matrix = new Matrix4(...input.matrix.flat());
    const translation = new Vector3();
    const quaternion = new Quaternion();
    const scale = new Vector3();
    matrix.decompose(translation, quaternion, scale);
    setTranslation(translation);
    setRotation(new Euler().setFromQuaternion(quaternion));
    setScale(scale.x);
    setLatitude(input.latitude);
    setLongitude(input.longitude);
  }
  return (
    <>
      <details className="collapse collapse-arrow border border-base-300 dark:border-neutral">
        <summary className="collapse-title">Load parameters from JSON</summary>
        <div className="collapse-content">
          <textarea
            rows={10}
            ref={textArea}
            className="textarea textarea-bordered w-full font-mono leading-4 mb-1"
          />
          <button onClick={() => load()} className="btn btn-primary w-full">
            Load
          </button>
        </div>
      </details>
    </>
  );
}

function ReferenceInput({ longitude, latitude, height, setLongitude, setLatitude, setHeight }) {
  return (
    <>
      <div className="grid grid-cols-[min-content_auto] gap-3 items-center">
        <div className="text-nowrap">Ref. latitude:</div>
        <div>
          <input
            className="input input-bordered w-full"
            value={latitude}
            onChange={(event) => setLatitude(parseFloat(event.target.value || "0"))}
          />
        </div>
        <div className="text-nowrap">Ref. longitude:</div>
        <div>
          <input
            className="input input-bordered w-full"
            value={longitude}
            onChange={(event) => setLongitude(parseFloat(event.target.value || "0"))}
          />
        </div>
        <div className="text-nowrap">Ref. height:</div>
        <div>
          <input
            className="input input-bordered w-full"
            value={height}
            onChange={(event) => setHeight(parseFloat(event.target.value || "0"))}
          />
        </div>
      </div>
    </>
  );
}

function ReferenceMouse({ enabled, setEnabled }) {
  return (
    <>
      <label className="label cursor-pointer justify-start gap-3">
        <input
          type="checkbox"
          className="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        <span>Set reference origin with mouse click</span>
      </label>
    </>
  );
}

function TranslationInput({ translation, setTranslation, component, componentIndex }) {
  return (
    <TransformInput
      title={"Translation " + component.toUpperCase()}
      setter={(value) => {
        setTranslation((translation) =>
          translation.clone().setComponent(componentIndex, parseFloat(value))
        );
      }}
      value={translation[component]}
      min={-30}
      max={30}
    />
  );
}

function RotationInput({ rotation, setRotation, component }) {
  return (
    <TransformInput
      title={"Rotation " + component.toUpperCase()}
      setter={(value) => {
        setRotation((rotation) => {
          const next = rotation.clone();
          next[component] = parseFloat(value);
          return next;
        });
      }}
      value={rotation[component]}
      display={(value) => Math.trunc((value / Math.PI) * 180)}
      step={0.01}
      min={-Math.PI * 2}
      max={Math.PI * 2}
    />
  );
}

function TransformInput({ value, setter, title, min, max, step = 0.1, display = (value) => value }) {
  return (
    <>
      <div>
        {title}: {display(value)}
        <input
          type="range"
          className="range w-full"
          onChange={(event) => setter(event.target.value)}
          value={value}
          min={min}
          max={max}
          step={step}
          style={{ width: "100%", marginLeft: 0, marginRight: 0 }}
        />
      </div>
    </>
  );
}

function MatrixTable({ matrix4x4 }) {
  return (
    <div style={{ overflow: "auto" }}>
      <table border={1} style={{ borderCollapse: "collapse" }} className="w-full">
        <tbody>
          {matrix4x4.map((row, rowKey) => (
            <tr key={rowKey}>
              {row.map((cell, cellKey) => (
                <td key={cellKey} className="border text-center align-middle w-1/4">
                  {cell.toFixed(4)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JsonOutput({ output, save }) {
  return (
    <>
      <details className="collapse collapse-arrow border border-base-300 dark:border-neutral">
        <summary className="collapse-title">JSON output</summary>
        <div className="collapse-content flex flex-col gap-2">
          <button
            className="btn btn-primary w-fit"
            onClick={(event) => {
              navigator.clipboard.writeText(output);
              event.target.innerText = "Copied";
            }}
          >
            Copy
          </button>
          <textarea
            className="textarea textarea-bordered font-mono leading-4 w-full"
            rows={15}
            value={output}
            readOnly
          />
        </div>
      </details>
      <button onClick={() => save()} className="btn btn-primary w-full">
        Save
      </button>
    </>
  );
}

function DebugGeoPose({ debugGeoPose, setDebugGeoPose }) {
  console.log("debugGeoPose", debugGeoPose);

  function loadGeoPose(value) {
    try {
      let geoPose = JSON.parse(value);
      setDebugGeoPose(geoPose);
    } catch (error) {
      setDebugGeoPose(null);
    }
  }

  return (
    <>
      <details className="collapse collapse-arrow border border-base-300 dark:border-neutral">
        <summary className="collapse-title">Visualize GeoPose</summary>
        <div className="collapse-content flex flex-col gap-2">
          <div className="text-xs italic">Enter GeoPose as valid JSON</div>
          <textarea
            className={
              "textarea font-mono leading-4 w-full " +
              (debugGeoPose === null ? "textarea-error" : "textarea-success")
            }
            rows={15}
            //value={JSON.stringify(debugGeoPose, null, 2)}
            defaultValue={
              '{\n  "position":{\n    "lon":,\n    "lat":,\n    "h":\n  },\n  "quaternion":{\n    "x":,\n    "y":,\n    "z":,\n    "w":\n  }\n}'
            }
            onChange={(event) => loadGeoPose(event.target.value)}
          />
        </div>
      </details>
    </>
  );
}
