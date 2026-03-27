<script setup lang="ts">
import { Notify } from 'quasar';
import { onMounted, ref, watch } from 'vue';
import { baseUrl } from 'boot/api';

interface QualityRating {
    category: 'colmap' | 'splats' | 'blueprint';
    rating: number;
}

interface GenerationFeedback {
    ratings: QualityRating[];
    notes: string;
}

const props = defineProps<{
    generationId: string;
}>();

const colmapRating = ref(3);
const splatsRating = ref(3);
const blueprintRating = ref(3);
const notes = ref('');

let saveTimeout: ReturnType<typeof setTimeout> | null = null;

async function saveFeedback(): Promise<void> {
    const feedback: GenerationFeedback = {
        ratings: [
            { category: 'colmap', rating: colmapRating.value },
            { category: 'splats', rating: splatsRating.value },
            { category: 'blueprint', rating: blueprintRating.value },
        ],
        notes: notes.value,
    };

    try {
        const response = await fetch(`${baseUrl}/splats/feedback/${props.generationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(feedback),
        });

        if (!response.ok) {
            throw new Error(`Failed to save feedback: ${response.statusText}`);
        }

        Notify.create({
            message: 'Feedback saved successfully',
            color: 'positive',
            icon: 'check',
            position: 'top',
            timeout: 2000,
        });
    } catch (error) {
        console.error('Failed to save feedback:', error);
        Notify.create({
            message: 'Failed to save feedback',
            color: 'negative',
            icon: 'error',
            position: 'top',
            timeout: 3000,
        });
    }
}

function scheduleFeedbackSave(): void {
    if (saveTimeout) {
        clearTimeout(saveTimeout);
    }
    saveTimeout = setTimeout(() => {
        void saveFeedback();
    }, 500);
}

async function loadFeedback(): Promise<void> {
    try {
        const response = await fetch(`${baseUrl}/splats/feedback/${props.generationId}`);
        if (!response.ok) {
            throw new Error(`Failed to load feedback: ${response.statusText}`);
        }

        const data: GenerationFeedback = await response.json();

        data.ratings.forEach((rating: QualityRating) => {
            if (rating.category === 'colmap') colmapRating.value = rating.rating;
            else if (rating.category === 'splats') splatsRating.value = rating.rating;
            else if (rating.category === 'blueprint') blueprintRating.value = rating.rating;
        });

        if (data.notes) notes.value = data.notes;
    } catch (error) {
        console.error('Failed to load feedback:', error);
        Notify.create({
            message: 'Failed to load saved feedback',
            color: 'warning',
            icon: 'warning',
            position: 'top',
            timeout: 3000,
        });
    }
}

watch([colmapRating, splatsRating, blueprintRating, notes], () => {
    scheduleFeedbackSave();
});

onMounted(() => {
    void loadFeedback();
});
</script>

<template>
    <div class="form-container">
        <q-card class="feedback-form-card">
            <q-card-section>
                <div class="text-h6 q-mb-md">Quality Feedback</div>

                <div class="feedback-row q-mb-sm">
                    <div class="feedback-label">
                        <q-icon name="location_searching" size="sm" class="q-mr-xs" />
                        COLMAP Tracking Quality
                    </div>
                    <div class="star-rating">
                        <q-icon
                            v-for="star in 5"
                            :key="star"
                            :name="star <= colmapRating ? 'star' : 'star_border'"
                            size="lg"
                            color="warning"
                            class="cursor-pointer"
                            @click="colmapRating = star"
                        />
                    </div>
                    <div class="feedback-value">{{ colmapRating }}/5</div>
                </div>

                <div class="feedback-row q-mb-sm">
                    <div class="feedback-label">
                        <q-icon name="view_in_ar" size="sm" class="q-mr-xs" />
                        Gaussian Splats Reconstruction Quality
                    </div>
                    <div class="star-rating">
                        <q-icon
                            v-for="star in 5"
                            :key="star"
                            :name="star <= splatsRating ? 'star' : 'star_border'"
                            size="lg"
                            color="warning"
                            class="cursor-pointer"
                            @click="splatsRating = star"
                        />
                    </div>
                    <div class="feedback-value">{{ splatsRating }}/5</div>
                </div>

                <div class="feedback-row q-mb-md">
                    <div class="feedback-label">
                        <q-icon name="map" size="sm" class="q-mr-xs" />
                        2D Blueprint Quality
                    </div>
                    <div class="star-rating">
                        <q-icon
                            v-for="star in 5"
                            :key="star"
                            :name="star <= blueprintRating ? 'star' : 'star_border'"
                            size="lg"
                            color="warning"
                            class="cursor-pointer"
                            @click="blueprintRating = star"
                        />
                    </div>
                    <div class="feedback-value">{{ blueprintRating }}/5</div>
                </div>

                <div class="feedback-notes">
                    <div class="text-subtitle2 q-mb-sm">Notes</div>
                    <q-input
                        v-model="notes"
                        type="textarea"
                        outlined
                        rows="4"
                        maxlength="1000"
                        hint="Max 1000 characters"
                        counter
                        dense
                    />
                </div>
            </q-card-section>
        </q-card>
    </div>
</template>

<style scoped>
.form-container {
    display: flex;
    justify-content: center;
    width: 100%;
}

.feedback-form-card {
    max-width: 900px;
    width: 100%;
    border-radius: 12px;
    background: white;
}

.feedback-row {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.feedback-label {
    flex: 1;
    font-size: 0.95rem;
    font-weight: 500;
    display: flex;
    align-items: center;
}

.star-rating {
    display: flex;
    gap: 2px;
}

.star-rating :deep(.q-icon) {
    font-size: 1.2rem;
}

.feedback-value {
    width: 40px;
    text-align: right;
    font-weight: bold;
    color: #1976d2;
}

.feedback-notes {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid #e0e0e0;
}
</style>
