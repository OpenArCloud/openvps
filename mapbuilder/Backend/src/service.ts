/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import express, {NextFunction, Request, type Response} from "express";
import http from "node:http";
import {Server, Socket} from "socket.io";
import cors from "cors";
import busboy from "connect-busboy";
import bodyparser from "body-parser";
import {v4 as uuidv4} from "uuid";
import fs from "fs-extra";
import {TaskManager} from "./taskManager";
import {ExpressAuth, getSession} from "@auth/express";

import path from "node:path";
import {EnvironmentalConfig} from "./index";
import {DataSetStatus, DataSet, TaskStatus} from "./dataSet";
import {ExtractTask} from "./processing/extractTask";
import {ThumbnailTask} from "./processing/thumbnailTask";
import {authConfig} from "./auth";
import {readHlocTransform, saveHlocTransform} from "./transform";
import {map} from "lodash";

function handleUpload(taskManager: TaskManager, uploadsRoot: string) {
    return async (req: Request, resp: Response) => {
        let zipFile: string | null = null;

        let mapName: string | undefined;

        req.busboy.on("field", (fieldname: string, val: string) => {
            // We're just going to capture the form data in a JSON document.
            console.log(" [service] Field [" + fieldname + "]: value: " + val);
            if (fieldname == "map-name") {
                mapName = val;
            }
        });

        req.pipe(req.busboy);

        req.busboy.on("file", function (name, file, info) {
            const uploadStartTime = Date.now();
            const {filename} = info;
            console.log(" [service] File being uploaded: " + filename);
            zipFile = filename;

            const id = uuidv4().toString();
            fs.mkdirSync(path.join(uploadsRoot, id));

            let fileSize = 0;
            file.on("data", function (chunk) {
                fileSize += chunk.length;
            });

            const fstream = fs.createWriteStream(path.join(uploadsRoot, id, filename));
            file.pipe(fstream);
            // TODO: handle file writing error and send back unsuccessdul notification
            fstream.on("close", function () {
                console.log(` [service] Finished saving ${filename} with id ${id}`);
                const uploadFinishTime = Date.now();
                resp.status(200).send();

                if (zipFile) {
                    const newStatus: DataSetStatus = {
                        metadata: {
                            id: id,
                            zip: zipFile,
                            name: mapName ? mapName : "<noname>",
                            size: fileSize,
                        },
                        [DataSet.uploadTaskName]: {
                            type: DataSet.uploadTaskName,
                            startTime: uploadStartTime,
                            runTime: uploadFinishTime - uploadStartTime,
                            status: TaskStatus.completed,
                        },
                        [ExtractTask.stageName]: {
                            type: ExtractTask.stageName,
                            status: TaskStatus.notStarted,
                        },
                        [ThumbnailTask.stageName]: {
                            type: ThumbnailTask.stageName,
                            status: TaskStatus.notStarted,
                        },
                    };

                    taskManager.add(newStatus);

                    taskManager.startExtractTask(id).then((result) => {
                        if (result?.[ExtractTask.stageName].status != TaskStatus.completed) {
                            return;
                        }
                        taskManager.startThumbnailTask(id);
                    });
                }
            });
        });
    };
}

export function startRestService(statuses: DataSetStatus[], config: EnvironmentalConfig) {
    const app = express();
    const httpServer = http.createServer(app);

    const io = new Server(httpServer, {
        cors: {
            origin: "*",
            methods: ["GET", "POST"],
        },
    });

    io.on("connection", (socket: Socket) => {
        console.log(" [service] frontend connected");
        socket.on("disconnect", () => {
            console.log(" [service] user disconnected");
        });
    });

    const taskManager = new TaskManager(config, io);

    taskManager.addMultiple(statuses);

    app.use(express.json());
    app.use(cors());
    app.use(bodyparser.text({type: ["application/yaml", "application/x-yaml", "application/yml", "application/x-yml", "text/yaml", "text/yml", "text/x-yaml", "text/x-yml"]}));

    app.set("trust proxy", true);
    app.use("/auth/*", ExpressAuth(authConfig));

    app.use(busboy());

    app.post("/uploadStrayRecordingZip", protectedRoute, handleUpload(taskManager, config.uploadsDir));

    app.get("/maps", protectedRoute, (req: Request, res: Response) => {
        console.log(" [service] All status retrieval request");

        const statuses = taskManager.getAllStatuses();
        const response = {
            statuses: statuses,
        };

        res.status(200).send(response);
    });

    app.get("/maps/selected", protectedRoute, async (req: Request, res: Response) => {
        const MAPLOCALIZER_URL = process.env.MAPLOCALIZER_URL;
        let selectQuery, selectResponse;
        try{
            selectQuery = await fetch(`${MAPLOCALIZER_URL}/current_map_id`);
            selectResponse = await selectQuery.json();
        }catch(error){
            console.error("Could not connect to MapLocalizer. Is it running?")
            console.error(error);
            res.status(500).send("Could not connect to MapLocalizer. Is it running?");
            return;
        }

        if (!selectQuery.ok) {
            if (selectResponse.detail === "Not Found") {
                res.status(200).send("");
                return;
            }
            res.status(500).send("Error querying selected map:" + JSON.stringify(selectResponse));
            return;
        } else {
            let mapId = selectResponse.id;
            let hlocStatus = taskManager.getAllStatuses().filter((dataSetStatus) => {
                return dataSetStatus.hloc?.[0]?.mapId === mapId;
            });
            if (hlocStatus.length >= 0 && hlocStatus[0]) {
                let dataSetId = hlocStatus[0].metadata.id;
                if (dataSetId) {
                    res.status(200).send(dataSetId);
                    return;
                } else {
                    console.log("hlocStatus", hlocStatus);
                    res.status(500).send("Dataset not found for HLOC Map ID " + mapId);
                    console.error("Dataset not found for HLOC Map ID " + mapId);
                    return;
                }
            } else {
                console.log("hlocStatus", hlocStatus);
                res.status(500).send("Hloc task not found for Map ID " + mapId);
                console.error("Hloc task not found for Map ID " + mapId);
                return;
            }
        }
    });

    app.get("/maps/:id", protectedRoute, (req: Request, res: Response) => {
        const id = req.params.id;

        const statusOfTask = taskManager.getStatusOfProcess(id);

        if (statusOfTask) {
            res.status(200).send(statusOfTask);
        } else {
            res.status(404).send("Not found");
        }
    });

    app.delete("/maps/:id", protectedRoute, (req: Request, res: Response) => {
        const id = req.params.id;

        const success = taskManager.delete(id);

        if (success) {
            res.status(200).send(success);
        } else {
            res.status(404).send("Not found");
        }
    });

    app.get("/maps/:id/thumbnail", protectedRoute, (req: Request, res: Response) => {
        const id = req.params.id;

        const success = taskManager.getThumbnailFilePath(id);

        if (success && fs.existsSync(success)) {
            res.status(200).sendFile(success);
        } else {
            let img =
                '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="#AAAAAA" viewBox="0 0 256 256"><path d="M216,40H40A16,16,0,0,0,24,56V200a16,16,0,0,0,16,16h64a8,8,0,0,0,7.59-5.47l14.83-44.48L163,151.43a8.07,8.07,0,0,0,4.46-4.46l14.62-36.55,44.48-14.83A8,8,0,0,0,232,88V56A16,16,0,0,0,216,40ZM112.41,157.47,98.23,200H40V172l52-52,30.42,30.42L117,152.57A8,8,0,0,0,112.41,157.47ZM216,82.23,173.47,96.41a8,8,0,0,0-4.9,4.62l-14.72,36.82L138.58,144l-35.27-35.27a16,16,0,0,0-22.62,0L40,149.37V56H216Zm12.68,33a8,8,0,0,0-7.21-1.1l-23.8,7.94a8,8,0,0,0-4.9,4.61l-14.31,35.77-35.77,14.31a8,8,0,0,0-4.61,4.9l-7.94,23.8A8,8,0,0,0,137.73,216H216a16,16,0,0,0,16-16V121.73A8,8,0,0,0,228.68,115.24ZM216,200H148.83l3.25-9.75,35.51-14.2a8.07,8.07,0,0,0,4.46-4.46l14.2-35.51,9.75-3.25Z"></path></svg>';

            res.status(200).setHeader("Content-Type", "image/svg+xml").send(img);
        }
    });

    app.put("/maps/:id/rename", protectedRoute, (req: Request, res: Response) => {
        const id = req.params.id;

        const success = taskManager.rename(id, req.body.name);

        if (success) {
            res.status(200).send(success);
        } else {
            res.status(404).send("Not found");
        }
    });

    app.put("/maps/:id/select", protectedRoute, async (req: Request, res: Response) => {
        const id = req.params.id;
        const MAPLOCALIZER_URL = process.env.MAPLOCALIZER_URL;

        let mapId = taskManager.getStatusOfProcess(id)?.hloc?.[0].mapId;
        if (!mapId) {
            console.error("Hloc map not found for dataset " + id);
            res.status(404).send("Hloc map not found for dataset " + id);
            return;
        }

        try{
            const selectQuery = await fetch(`${MAPLOCALIZER_URL}/load_map/${mapId}`, {
                signal: AbortSignal.timeout(3000)
            });
            if(!selectQuery.ok){
                const selectResponse = await selectQuery.json();
                res.status(500).send(selectResponse.ERROR);
            }else{
                res.status(200).send("OK");
            }
        }catch(error){
            if(error.name === "TimeoutError"){
                res.status(200).send("Loading localization map.\nThis may take several minutes, please wait.");
            }else{
                res.status(500).send(error.toString());
                console.error(error);
            }
        }
    });

    app.get("/maps/:id/extract", protectedRoute, async (req: Request, res: Response) => {
        const id = req.params.id;

        const statusOfTask = await taskManager.startExtractTask(id);

        if (statusOfTask) {
            res.status(200).send(statusOfTask);
        } else {
            res.status(404).send("Not found");
        }
    });

    app.post("/maps/:id/hloc/registerConfig", protectedRoute, (req: Request, res: Response) => {
        const datasetId = req.params.id;
        const hlocMappingConfig = req.body; // WARNING: for some reason, this here is already parsed from JSON string into a dict.
        const createdHlocMappingConfigStatus = taskManager.registerHlocConfig(datasetId, hlocMappingConfig);
        if (createdHlocMappingConfigStatus) {
            res.status(200).send(JSON.stringify(createdHlocMappingConfigStatus));
        } else {
            res.status(404).send("Not found");
        }
    });

    app.post("/maps/:id/hloc/:mapId/process", protectedRoute, (req: Request, res: Response) => {
        const datasetId = req.params.id;
        const mapId = req.params.mapId;
        const status = taskManager.startHlocProcessing(datasetId, mapId);

        if (status) {
            res.status(200).send(status);
        } else {
            res.status(404).send("Not found");
        }
    });

    app.get("/maps/:id/hloc/:mapId/download", protectedRoute, (req: Request, res: Response) => {
        const datasetId = req.params.id;
        const mapId = req.params.mapId;
        const file = taskManager.getHlocSparsePlyDownloadLink(datasetId, mapId);
        const filename = mapId + ".ply";
        if (file) {
            console.log("[hloc] Downloading", file);
            res.download(file, filename, function (error) {
                if (error) {
                    console.log("Download error:", error);
                    res.status(500).send("Download error");
                }
            });
        } else {
            res.status(404).send("Not found");
        }
    });

    app.get("/maps/:id/hloc/:mapId/transform", protectedRoute, (req: Request, res: Response) => {
        const datasetId = req.params.id;
        const mapId = req.params.mapId;
        try {
            const geoPose = readHlocTransform(datasetId, mapId, config);
            res.status(200).send(geoPose);
        } catch (error) {
            console.error("Error loading transform", error);
            res.status(500).send(`Error loading transform`);
        }
    });

    app.post("/maps/:id/hloc/:mapId/transform", protectedRoute, (req: Request, res: Response) => {
        const datasetId = req.params.id;
        const mapId = req.params.mapId;
        try {
            saveHlocTransform(datasetId, mapId, req.body, config);
            res.status(200).send(req.body);
        } catch (error) {
            console.error("Error saving transform:", error);
            res.status(500).send(`Error saving transform`);
        }
    });

    app.get("/healthcheck", (req: Request, res: Response) => {
        res.status(200).send("OK");
    });

    httpServer.listen(3000, () => {
        console.log("Server is running on port 3000");
    });
}

async function protectedRoute(req: Request, res: Response, next: NextFunction) {
    const session = res.locals.session ?? (await getSession(req, authConfig));
    if (!session?.user) {
        res.status(401).send("Unauthorized");
    } else {
        next();
    }
}
