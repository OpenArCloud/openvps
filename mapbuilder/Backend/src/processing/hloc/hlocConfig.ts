/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

export interface HlocConfig {
    program_steps?: HlocProgramSteps;
    hloc_reconstruction?: HlocReconstruction;
}

export interface HlocProgramSteps {
    hloc_extract_features?: boolean;
    hloc_find_image_pairs?: boolean;
    hloc_matches_from_pairs?: boolean;
    hloc_build_model?: boolean;
}

export type HlocMetricAlignmentMode = "none" | "rescale_model" | "coord_scale_only";

export interface HlocReconstruction {
    hloc_path?: string;
    image_path?: string;
    feature_conf?: string;
    matcher_conf?: string;
    retrieval_conf?: string;
    pairs_strategy?: string;
    prior_model_path?: string;
    reconstruction_path?: string;
}
