import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export type BuildingStatus = 'ready' | 'processing';

export interface Building {
    id: string;
    name: string;
    recordedDate: string;
    status: BuildingStatus;
    progress: number;
    address: string;
    size: string;
    duration: string;
    description: string;
    environment: 'indoors' | 'outdoors';
    buildingType: string;
    intendedUse: string;
    materials: string[];
    x: number;
    y: number;
}

const INITIAL_BUILDINGS: Building[] = [
    {
        id: '1',
        name: 'Building 1',
        recordedDate: '16/07',
        status: 'processing',
        progress: 68,
        address: 'Avenue de la gare 5',
        size: '253mb',
        duration: '2:34',
        description:
            'Capture Description about this wonderful building with built with impeccable taste.',
        environment: 'indoors',
        buildingType: '',
        intendedUse: '',
        materials: ['Brick_1', 'Concrete_1'],
        x: 160,
        y: 220,
    },
    {
        id: '2',
        name: 'My Building',
        recordedDate: '16/07',
        status: 'ready',
        progress: 100,
        address: 'Rue du Lac 12',
        size: '198mb',
        duration: '1:45',
        description: 'A compact residential block captured for renovation planning.',
        environment: 'outdoors',
        buildingType: '',
        intendedUse: '',
        materials: ['Brick_1'],
        x: 120,
        y: 140,
    },
    {
        id: '3',
        name: 'Building 2',
        recordedDate: '16/07',
        status: 'ready',
        progress: 100,
        address: 'Avenue du Mont 8',
        size: '312mb',
        duration: '3:12',
        description: 'Commercial facade captured in the morning light.',
        environment: 'indoors',
        buildingType: '',
        intendedUse: '',
        materials: ['Concrete_1'],
        x: 210,
        y: 180,
    },
    {
        id: '4',
        name: 'Building 3',
        recordedDate: '16/07',
        status: 'ready',
        progress: 100,
        address: 'Chemin des Roses 3',
        size: '145mb',
        duration: '1:10',
        description: 'Small annex for energy retrofit study.',
        environment: 'outdoors',
        buildingType: '',
        intendedUse: '',
        materials: ['Wood_1'],
        x: 250,
        y: 260,
    },
];

export const useBuildingsStore = defineStore('buildings', () => {
    const buildings = ref<Building[]>(INITIAL_BUILDINGS);
    const selectedId = ref<string | null>(null);

    const readyBuildings = computed(() => buildings.value.filter((b) => b.status === 'ready'));
    const inProgressBuildings = computed(() =>
        buildings.value.filter((b) => b.status === 'processing'),
    );
    const selectedBuilding = computed(() => buildings.value.find((b) => b.id === selectedId.value));

    function getById(id: string) {
        return buildings.value.find((b) => b.id === id);
    }

    function remove(id: string) {
        const index = buildings.value.findIndex((b) => b.id === id);
        if (index >= 0) {
            buildings.value.splice(index, 1);
        }
    }

    function add(building: Building) {
        buildings.value.unshift(building);
    }

    function startProcessing(
        partial: Partial<Omit<Building, 'id' | 'status' | 'progress' | 'recordedDate'>> &
            Pick<Building, 'name' | 'size' | 'duration'>,
    ): string {
        const id = `${Date.now()}`;
        const recordedDate = new Date().toLocaleDateString('en-GB', {
            day: '2-digit',
            month: '2-digit',
        });
        const newBuilding: Building = {
            id,
            name: partial.name,
            recordedDate,
            status: 'processing',
            progress: 0,
            address: partial.address ?? '',
            size: partial.size,
            duration: partial.duration,
            description: partial.description ?? '',
            environment: partial.environment ?? 'indoors',
            buildingType: partial.buildingType ?? '',
            intendedUse: partial.intendedUse ?? '',
            materials: partial.materials ?? [],
            x: 40 + Math.floor(Math.random() * 240),
            y: 40 + Math.floor(Math.random() * 340),
        };
        buildings.value.unshift(newBuilding);
        return id;
    }

    function updateProgress(id: string, progress: number) {
        const building = getById(id);
        if (building) {
            building.progress = Math.min(100, Math.max(0, progress));
        }
    }

    function setStatus(id: string, status: BuildingStatus) {
        const building = getById(id);
        if (building) {
            building.status = status;
        }
    }

    return {
        buildings,
        selectedId,
        readyBuildings,
        inProgressBuildings,
        selectedBuilding,
        getById,
        remove,
        add,
        startProcessing,
        updateProgress,
        setStatus,
    };
});
