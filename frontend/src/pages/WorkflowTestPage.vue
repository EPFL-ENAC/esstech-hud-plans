<template>
    <q-page class="q-pa-md">
        <div class="wrapper q-gutter-y-md">
            <div>
                <h1 class="text-h5 q-my-none">Workflows API test</h1>
                <div class="text-caption text-grey-7 q-mt-xs">
                    Temporary page for exercising the frame-extraction workflow endpoints.
                </div>
            </div>

            <q-banner rounded class="bg-amber-1 text-amber-10">
                This is a developer test route. Uploaded videos are processed by the configured
                workflow service.
            </q-banner>

            <q-card flat bordered>
                <q-card-section>
                    <div class="text-h6">1. Submit frame extraction</div>
                    <div class="text-caption text-grey-7">POST /workflows/frame-extraction</div>
                </q-card-section>

                <q-separator />

                <q-form class="q-pa-md q-gutter-y-md" @submit="submitFrameExtraction">
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

                    <div class="row q-col-gutter-md">
                        <q-input
                            v-model.number="settings.fps"
                            class="col-12 col-sm-4"
                            outlined
                            type="number"
                            min="0.01"
                            step="0.01"
                            label="FPS"
                        />
                        <q-input
                            v-model.number="settings.fitInWidth"
                            class="col-12 col-sm-4"
                            outlined
                            type="number"
                            min="1"
                            step="1"
                            label="Fit-in width"
                        />
                        <q-input
                            v-model.number="settings.fitInHeight"
                            class="col-12 col-sm-4"
                            outlined
                            type="number"
                            min="1"
                            step="1"
                            label="Fit-in height"
                        />
                    </div>

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
import { computed, reactive, ref } from 'vue';
import { baseUrl } from 'boot/api';
import { authFetch } from 'src/lib/auth';

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

const videoFile = ref<File | null>(null);
const settings = reactive({
    fps: 2,
    fitInWidth: 1920,
    fitInHeight: 1920,
});
const workflowId = ref('');
const workflowStatus = ref<WorkflowStatusResponse | null>(null);

const activeRequest = ref<RequestName | null>(null);
const responseLabel = ref('');
const responseStatus = ref<number | null>(null);
const responseBody = ref<unknown>(null);

const isBusy = computed(() => activeRequest.value !== null);
const canSubmit = computed(
    () =>
        videoFile.value !== null &&
        settings.fps > 0 &&
        settings.fitInWidth > 0 &&
        settings.fitInHeight > 0,
);
const formattedResponse = computed(() => {
    if (!responseLabel.value) return 'Responses will appear here.';
    if (typeof responseBody.value === 'string') return responseBody.value;
    return JSON.stringify(responseBody.value, null, 2);
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

async function submitFrameExtraction(): Promise<void> {
    if (!videoFile.value || !canSubmit.value) return;

    const formData = new FormData();
    formData.append('file', videoFile.value);
    formData.append('fps', String(settings.fps));
    formData.append('fit_in_width', String(settings.fitInWidth));
    formData.append('fit_in_height', String(settings.fitInHeight));

    const response = await captureRequest('submit', 'POST /workflows/frame-extraction', () =>
        authFetch(`${baseUrl}/workflows/frame-extraction`, {
            method: 'POST',
            body: formData,
        }),
    );

    if (response?.ok && isRecord(response.body) && typeof response.body.workflow_id === 'string') {
        workflowId.value = response.body.workflow_id;
        workflowStatus.value = null;
    }
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
</style>
