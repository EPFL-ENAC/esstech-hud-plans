export interface ContentRange {
    start: number;
    end: number; // Inclusive.
    total: number;
}

export function parseContentRange(value: string | null): ContentRange {
    const match = value?.match(/^bytes (\d+)-(\d+)\/(\d+)$/);
    if (!match) throw new Error('Invalid Content-Range.');

    const start = Number(match[1]);
    const end = Number(match[2]);
    const total = Number(match[3]);

    if (![start, end, total].every(Number.isSafeInteger) || end < start || end >= total) {
        throw new Error('Invalid Content-Range.');
    }

    return { start, end, total };
}
