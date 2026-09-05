<template>
    <q-page class="q-pa-md">
        <div class="wrapper q-gutter-y-md">
            <div>
                <h1 class="text-h5 q-my-none">Workflows API test</h1>
                <div class="text-caption text-grey-7 q-mt-xs">
                    Temporary page for exercising the splat-generation workflow endpoints.
                </div>
            </div>

            <q-banner rounded class="bg-amber-1 text-amber-10">
                This is a developer test route. Uploaded videos are processed by the configured
                workflow service.
            </q-banner>

            <q-card flat bordered>
                <q-card-section>
                    <div class="text-h6">1. Submit splat generation</div>
                    <div class="text-caption text-grey-7">POST /workflows/splat-generation</div>
                </q-card-section>

                <q-separator />

                <q-form class="q-pa-md q-gutter-y-md" @submit="submitSplatGeneration">
                    <q-file
                        v-model="videoFile"
                        outlined
                        accept="video/*"
                        label="Video file"
                        clearable
                    >
                        <template #prepend>
                            <q-icon name="movie" />
                        </template>
                    </q-file>

                    <div class="text-subtitle1 text-weight-medium">ffmpeg settings</div>
                    <div class="row q-col-gutter-md">
                        <q-input
                            v-model.number="settings.ffmpeg.fps"
                            class="col-12 col-sm-4"
                            outlined
                            type="number"
                            min="0.01"
                            step="0.01"
                            label="FPS"
                        />
                        <q-input
                            v-model.number="settings.ffmpeg.fitInWidth"
                            class="col-12 col-sm-4"
                            outlined
                            type="number"
                            min="1"
                            step="1"
                            label="Fit-in width"
                        />
                        <q-input
                            v-model.number="settings.ffmpeg.fitInHeight"
                            class="col-12 col-sm-4"
                            outlined
                            type="number"
                            min="1"
                            step="1"
                            label="Fit-in height"
                        />
                    </div>

                    <q-separator />

                    <frame-picker-settings v-model="framePickerConfig" />

                    <q-separator />

                    <div class="text-subtitle1 text-weight-medium">COLMAP settings</div>
                    <div class="row q-col-gutter-md">
                        <q-select
                            v-model="settings.colmap.dataType"
                            class="col-12 col-sm-4"
                            outlined
                            emit-value
                            map-options
                            :options="colmapDataTypeOptions"
                            label="Data type"
                        />
                        <q-select
                            v-model="settings.colmap.quality"
                            class="col-12 col-sm-4"
                            outlined
                            :options="colmapQualityOptions"
                            label="Quality"
                        />
                        <q-select
                            v-model="settings.colmap.cameraModel"
                            class="col-12 col-sm-4"
                            outlined
                            :options="colmapCameraModelOptions"
                            label="Camera model"
                        />
                    </div>
                    <div class="row q-col-gutter-md">
                        <q-toggle
                            v-model="settings.colmap.singleCamera"
                            class="col-12 col-sm-4"
                            label="Use shared camera intrinsics"
                        />
                        <q-toggle
                            v-model="settings.colmap.useGpu"
                            class="col-12 col-sm-4"
                            label="Use GPU"
                        />
                        <q-toggle
                            v-model="settings.colmap.useGlobalMapper"
                            class="col-12 col-sm-4"
                            label="Use global mapper"
                        />
                    </div>

                    <q-separator />

                    <brush-settings v-model="brushConfig" />

                    <q-btn
                        color="primary"
                        icon="upload"
                        label="Submit workflow"
                        type="submit"
                        :disable="!canSubmit || isBusy"
                        :loading="activeRequest === 'submit'"
                    />
                </q-form>
            </q-card>

            <q-card flat bordered>
                <q-card-section>
                    <div class="text-h6">2. Inspect workflow</div>
                    <div class="text-caption text-grey-7">
                        GET /workflows/status/:id and GET /workflows/result/:id
                    </div>
                </q-card-section>

                <q-separator />

                <q-card-section class="q-gutter-y-md">
                    <q-input
                        v-model.trim="workflowId"
                        outlined
                        label="Workflow ID"
                        hint="Filled automatically after a successful submission"
                    >
                        <template #prepend>
                            <q-icon name="fingerprint" />
                        </template>
                    </q-input>

                    <div class="row q-gutter-sm">
                        <q-btn
                            color="primary"
                            outline
                            icon="sync"
                            label="Check status"
                            :disable="!workflowId || isBusy"
                            :loading="activeRequest === 'status'"
                            @click="checkStatus"
                        />
                        <q-btn
                            color="primary"
                            outline
                            icon="folder"
                            label="Get result"
                            :disable="!workflowId || isBusy"
                            :loading="activeRequest === 'result'"
                            @click="getResult"
                        />
                    </div>

                    <div v-if="workflowStatus" class="row items-center q-gutter-sm">
                        <span class="text-body2">Latest workflow status:</span>
                        <q-chip dense color="primary" text-color="white">
                            {{ workflowStatus.status }}
                        </q-chip>
                        <span v-if="workflowStatus.message" class="text-body2 text-grey-8">
                            {{ workflowStatus.message }}
                        </span>
                    </div>
                </q-card-section>
            </q-card>

            <q-card flat bordered>
                <q-card-section class="row items-center justify-between q-gutter-sm">
                    <div>
                        <div class="text-h6">Live workflow logs</div>
                        <div class="text-caption text-grey-7">GET /workflows/listen/:id</div>
                    </div>
                    <div class="row items-center q-gutter-sm">
                        <q-chip
                            v-if="logStreamState !== 'idle'"
                            dense
                            :color="logStreamStateColor"
                            text-color="white"
                        >
                            {{ logStreamState }}
                        </q-chip>
                        <q-btn
                            v-if="logStreamState === 'connecting' || logStreamState === 'listening'"
                            flat
                            dense
                            color="negative"
                            icon="stop"
                            label="Stop"
                            @click="stopLogStream"
                        />
                    </div>
                </q-card-section>

                <q-separator />

                <q-banner v-if="logStreamError" class="bg-red-1 text-negative">
                    {{ logStreamError }}
                </q-banner>

                <div ref="logsContainer" class="workflow-logs bg-black text-white q-pa-sm">
                    <div v-for="log in workflowLogs" :key="log.id" class="workflow-log-line">
                        {{ log.message }}
                    </div>
                    <div v-if="workflowLogs.length === 0" class="text-grey-6 text-italic">
                        Logs will appear here after submitting a workflow.
                    </div>
                </div>
            </q-card>

            <q-card flat bordered>
                <q-card-section class="row items-center justify-between">
                    <div>
                        <div class="text-h6">Latest response</div>
                        <div class="text-caption text-grey-7">
                            {{ responseLabel || 'No request sent yet' }}
                        </div>
                    </div>
                    <q-chip
                        v-if="responseStatus !== null"
                        dense
                        :color="responseStatus < 400 ? 'positive' : 'negative'"
                        text-color="white"
                    >
                        HTTP {{ responseStatus }}
                    </q-chip>
                </q-card-section>

                <q-separator />

                <q-card-section>
                    <pre class="response-body">{{ formattedResponse }}</pre>
                </q-card-section>
            </q-card>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref } from 'vue';
import { baseUrl } from 'boot/api';
import BrushSettings from 'src/components/BrushSettings.vue';
import FramePickerSettings from 'src/components/FramePickerSettings.vue';
import { authFetch } from 'src/lib/auth';
import { type BrushTrainingConfig, makeDefaultBrushConfig } from 'src/lib/splats/brush';
import { type FramePickerConfig, makeDefaultFramePickerConfig } from 'src/lib/splats/framePicker';

type RequestName = 'submit' | 'status' | 'result';

interface WorkflowStatusResponse {
    workflow_id: string;
    status: string;
    message: string | null;
}

interface CapturedResponse {
    ok: boolean;
    status: number;
    body: unknown;
}

interface WorkflowLog {
    id: string;
    timestamp: string;
    level: number;
    name: string;
    message: string;
    flow_run_id: string | null;
    task_run_id: string | null;
}

type LogStreamState = 'idle' | 'connecting' | 'listening' | 'finished' | 'stopped' | 'error';

const videoFile = ref<File | null>(null);
const settings = reactive({
    ffmpeg: {
        fps: 2,
        fitInWidth: 1920,
        fitInHeight: 1920,
    },
    colmap: {
        dataType: 'video',
        quality: 'low',
        cameraModel: 'OPENCV',
        singleCamera: true,
        useGpu: false,
        useGlobalMapper: false,
    },
});
const framePickerConfig = ref<FramePickerConfig>(makeDefaultFramePickerConfig());
const brushConfig = ref<BrushTrainingConfig>(makeDefaultBrushConfig());
const colmapDataTypeOptions = [
    { label: 'Individual images', value: 'individual' },
    { label: 'Video frames', value: 'video' },
    { label: 'Internet images', value: 'internet' },
];
const colmapQualityOptions = ['low', 'medium', 'high', 'extreme'];
const colmapCameraModelOptions = ['PINHOLE', 'OPENCV', 'OPENCV_FISHEYE', 'RADIAL'];
const workflowId = ref('');
const workflowStatus = ref<WorkflowStatusResponse | null>(null);
const workflowLogs = ref<WorkflowLog[]>([]);
const logStreamState = ref<LogStreamState>('idle');
const logStreamError = ref('');
const logsContainer = ref<HTMLElement | null>(null);
let logStreamController: AbortController | null = null;

const activeRequest = ref<RequestName | null>(null);
const responseLabel = ref('');
const responseStatus = ref<number | null>(null);
const responseBody = ref<unknown>(null);

const isBusy = computed(() => activeRequest.value !== null);
const canSubmit = computed(
    () =>
        videoFile.value !== null &&
        settings.ffmpeg.fps > 0 &&
        settings.ffmpeg.fitInWidth > 0 &&
        settings.ffmpeg.fitInHeight > 0 &&
        (!framePickerConfig.value.enabled ||
            (framePickerConfig.value.min_fps > 0 &&
                framePickerConfig.value.distance_threshold >= 0 &&
                framePickerConfig.value.outlier_sharpness_ratio >= 0 &&
                framePickerConfig.value.outlier_sharpness_ratio <= 1)),
);
const formattedResponse = computed(() => {
    if (!responseLabel.value) return 'Responses will appear here.';
    if (typeof responseBody.value === 'string') return responseBody.value;
    return JSON.stringify(responseBody.value, null, 2);
});
const logStreamStateColor = computed(() => {
    switch (logStreamState.value) {
        case 'listening':
            return 'primary';
        case 'finished':
            return 'positive';
        case 'error':
            return 'negative';
        default:
            return 'grey-7';
    }
});

async function captureRequest(
    name: RequestName,
    label: string,
    request: () => Promise<Response>,
): Promise<CapturedResponse | null> {
    activeRequest.value = name;
    responseLabel.value = label;
    responseStatus.value = null;
    responseBody.value = null;

    try {
        const response = await request();
        const text = await response.text();
        let body: unknown = null;

        if (text) {
            try {
                body = JSON.parse(text) as unknown;
            } catch {
                body = text;
            }
        }

        responseStatus.value = response.status;
        responseBody.value = body;
        return { ok: response.ok, status: response.status, body };
    } catch (error) {
        responseBody.value = {
            network_error: error instanceof Error ? error.message : String(error),
        };
        return null;
    } finally {
        activeRequest.value = null;
    }
}

async function submitSplatGeneration(): Promise<void> {
    if (!videoFile.value || !canSubmit.value) return;

    const formData = new FormData();
    formData.append('file', videoFile.value);
    formData.append(
        'settings',
        JSON.stringify({
            ffmpeg: {
                fps: settings.ffmpeg.fps,
                fit_in_width: settings.ffmpeg.fitInWidth,
                fit_in_height: settings.ffmpeg.fitInHeight,
            },
            frame_picker: framePickerConfig.value.enabled
                ? {
                      min_fps: framePickerConfig.value.min_fps,
                      distance_threshold: framePickerConfig.value.distance_threshold,
                      remove_outliers: framePickerConfig.value.remove_outliers,
                      outlier_sharpness_ratio: framePickerConfig.value.outlier_sharpness_ratio,
                  }
                : null,
            colmap: {
                data_type: settings.colmap.dataType,
                quality: settings.colmap.quality,
                camera_model: settings.colmap.cameraModel,
                single_camera: settings.colmap.singleCamera,
                use_gpu: settings.colmap.useGpu,
                use_global_mapper: settings.colmap.useGlobalMapper,
            },
            brush: {
                total_steps: brushConfig.value.totalSteps,
                render_mode: brushConfig.value.renderMode,
                sh_degree: brushConfig.value.shDegree,
                max_splats: brushConfig.value.maxSplats,
                refine_every: brushConfig.value.refineEvery,
                growth_grad_threshold: brushConfig.value.growthGradThreshold,
                growth_stop_iter: brushConfig.value.growthStopIter,
                max_resolution: brushConfig.value.maxResolution,
                subsample_frames: brushConfig.value.subsampleFrames,
                alpha_mode: brushConfig.value.alphaMode,
                export_every: brushConfig.value.exportEvery,
            },
        }),
    );

    const response = await captureRequest('submit', 'POST /workflows/splat-generation', () =>
        authFetch(`${baseUrl}/workflows/splat-generation`, {
            method: 'POST',
            body: formData,
        }),
    );

    if (response?.ok && isRecord(response.body) && typeof response.body.workflow_id === 'string') {
        workflowId.value = response.body.workflow_id;
        workflowStatus.value = null;
        void listenToWorkflow(response.body.workflow_id);
    }
}

async function listenToWorkflow(runId: string): Promise<void> {
    stopLogStream();
    workflowLogs.value = [];
    logStreamError.value = '';
    logStreamState.value = 'connecting';

    const controller = new AbortController();
    logStreamController = controller;

    try {
        const response = await authFetch(
            `${baseUrl}/workflows/listen/${encodeURIComponent(runId)}`,
            {
                headers: { Accept: 'text/event-stream' },
                signal: controller.signal,
            },
        );
        if (!response.ok) {
            throw new Error(`Workflow log stream returned HTTP ${response.status}`);
        }
        if (!response.body) {
            throw new Error('Workflow log stream did not provide a response body');
        }

        logStreamState.value = 'listening';
        await readServerSentEvents(response.body, handleWorkflowLogEvent);
        if (logStreamController === controller) {
            logStreamState.value = 'finished';
        }
    } catch (error) {
        if (controller.signal.aborted) return;
        logStreamError.value = error instanceof Error ? error.message : String(error);
        logStreamState.value = 'error';
    } finally {
        if (logStreamController === controller) {
            logStreamController = null;
        }
    }
}

async function readServerSentEvents(
    stream: ReadableStream<Uint8Array>,
    onEvent: (event: string, data: unknown) => void,
): Promise<void> {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
        while (true) {
            const { done, value } = await reader.read();
            buffer += decoder.decode(value, { stream: !done });

            let eventBoundary = buffer.indexOf('\n\n');
            while (eventBoundary !== -1) {
                parseServerSentEvent(buffer.slice(0, eventBoundary), onEvent);
                buffer = buffer.slice(eventBoundary + 2);
                eventBoundary = buffer.indexOf('\n\n');
            }

            if (done) {
                if (buffer.trim()) parseServerSentEvent(buffer, onEvent);
                return;
            }
        }
    } finally {
        reader.releaseLock();
    }
}

function parseServerSentEvent(
    rawEvent: string,
    onEvent: (event: string, data: unknown) => void,
): void {
    let event = 'message';
    const dataLines: string[] = [];

    for (const line of rawEvent.split(/\r?\n/)) {
        if (line.startsWith('event:')) {
            event = line.slice('event:'.length).trimStart();
        } else if (line.startsWith('data:')) {
            dataLines.push(line.slice('data:'.length).trimStart());
        }
    }

    if (dataLines.length === 0) return;
    let data: unknown;
    try {
        data = JSON.parse(dataLines.join('\n')) as unknown;
    } catch (error) {
        console.warn('Invalid workflow SSE payload', event, dataLines, error);
        return;
    }
    onEvent(event, data);
}

function handleWorkflowLogEvent(event: string, data: unknown): void {
    if (event === 'snapshot' && isRecord(data) && Array.isArray(data.logs)) {
        workflowLogs.value = data.logs.filter(isWorkflowLog);
        void scrollLogsToBottom();
        return;
    }

    if (event === 'log' && isWorkflowLog(data)) {
        workflowLogs.value.push(data);
        void scrollLogsToBottom();
    }
}

function isWorkflowLog(value: unknown): value is WorkflowLog {
    return (
        isRecord(value) &&
        typeof value.id === 'string' &&
        typeof value.timestamp === 'string' &&
        typeof value.level === 'number' &&
        typeof value.name === 'string' &&
        typeof value.message === 'string' &&
        (typeof value.flow_run_id === 'string' || value.flow_run_id === null) &&
        (typeof value.task_run_id === 'string' || value.task_run_id === null)
    );
}

async function scrollLogsToBottom(): Promise<void> {
    await nextTick();
    if (logsContainer.value) {
        logsContainer.value.scrollTop = logsContainer.value.scrollHeight;
    }
}

function stopLogStream(): void {
    if (!logStreamController) return;
    logStreamController.abort();
    logStreamController = null;
    logStreamState.value = 'stopped';
}

async function checkStatus(): Promise<void> {
    if (!workflowId.value) return;

    const response = await captureRequest('status', 'GET /workflows/status/:id', () =>
        authFetch(`${baseUrl}/workflows/status/${encodeURIComponent(workflowId.value)}`),
    );

    if (
        response?.ok &&
        isRecord(response.body) &&
        typeof response.body.workflow_id === 'string' &&
        typeof response.body.status === 'string'
    ) {
        workflowStatus.value = {
            workflow_id: response.body.workflow_id,
            status: response.body.status,
            message: typeof response.body.message === 'string' ? response.body.message : null,
        };
    }
}

async function getResult(): Promise<void> {
    if (!workflowId.value) return;

    await captureRequest('result', 'GET /workflows/result/:id', () =>
        authFetch(`${baseUrl}/workflows/result/${encodeURIComponent(workflowId.value)}`),
    );
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
}

onBeforeUnmount(stopLogStream);
</script>

<style scoped>
.wrapper {
    max-width: 800px;
    margin: 0 auto;
}

.response-body {
    min-height: 5rem;
    margin: 0;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
}

.workflow-logs {
    min-height: 8rem;
    max-height: 24rem;
    overflow: auto;
    font-family: monospace;
    font-size: 0.8rem;
    white-space: pre-wrap;
    word-break: break-word;
}

.workflow-log-line {
    padding: 0.1rem 0;
}
</style>
