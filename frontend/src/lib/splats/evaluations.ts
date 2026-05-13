export interface ReprojectionErrorFracs {
    le_1px: number;
    le_2px: number;
    le_4px: number;
}

export interface MeanMedianMinMax {
    mean: number;
    median: number;
    min: number;
    max: number;
}

export interface StatisticsSummary {
    mean: number | null;
    median: number | null;
    p90: number | null;
    p95: number | null;
}

export interface ReconstructionMetrics {
    model_name: string;
    model_path: string; // Using string to represent Path

    num_registered_images: number;
    registered_fraction: number;

    num_points3D: number;
    num_observations: number;

    track_length: MeanMedianMinMax;
    points3D_per_image: MeanMedianMinMax;

    reprojection_error_stats: StatisticsSummary;
    reprojection_error_fracs: ReprojectionErrorFracs;

    first_registered_frame: number | null;
    last_registered_frame: number | null;
    temporal_span: number | null;
    longest_contiguous_run: number;
    num_temporal_segments: number;
    registered_fraction_within_span: number | null;
}

export interface ColmapReconstructionEvaluation {
    metrics: ReconstructionMetrics;

    score: number;

    coverage_score: number;
    continuity_score: number;
    accuracy_score: number;
    points_density_score: number;
    fragmentation: number;
}

export interface ColmapSparseEvaluation {
    sparse_path: string;
    total_input_frames: number | null;
    num_models: number;
    evaluations: ColmapReconstructionEvaluation[];
    best_model_index: number;
    selected_reconstruction_id?: string;
}
