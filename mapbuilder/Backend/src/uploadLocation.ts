/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import path from "node:path";
import {ProcessMetadata} from "./dataSet";

export class UploadLocation {
    private fileStem: string;
    private extension: string | undefined;

    constructor(
        protected backendUploadDir: string,
        protected metadata: ProcessMetadata,
    ) {
        const {fileStem, extension} = this.getFilenameWithoutExtension(this.metadata.zip);
        this.fileStem = fileStem;
        this.extension = extension;
    }

    public getId(): string {
        return this.metadata.id;
    }

    public getZipFile(): string {
        return this.metadata.zip;
    }

    public getExtension() {
        return this.extension;
    }

    public getName(): string {
        return this.metadata.name;
    }

    public getSize(): number {
        return this.metadata.size;
    }

    public getDataSetRoot() {
        return path.join(this.backendUploadDir, this.metadata.id);
    }

    public getStrayRecordingDir() {
        return path.join(this.getDataSetRoot(), "stray_recording");
    }

    public getStrayColmapDir() {
        return path.join(this.getDataSetRoot(), "stray_colmap");
    }

    public getZipFilePath() {
        return path.join(this.getDataSetRoot(), this.metadata.zip);
    }

    public getStatusFilePath() {
        return path.join(this.getDataSetRoot(), "status.json");
    }

    public getThumbnailFilePath() {
        return path.join(this.getDataSetRoot(), "thumbnail.png");
    }

    private getFilenameWithoutExtension(filename: string): {fileStem: string; extension: string | undefined} {
        const extension = filename.split(".").pop();
        console.log(` [uploadLocation] Extension of file is ${extension}`);

        if (extension) {
            return {fileStem: filename.substring(0, filename.length - (extension.length + 1)), extension};
        } else {
            return {fileStem: filename, extension: undefined};
        }
    }
}
