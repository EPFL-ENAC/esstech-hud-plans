export function formatFileSize(bytes: number, locale: string): string {
    const units = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const;
    const unitIndex = Math.min(Math.floor(Math.log10(Math.max(bytes, 1)) / 3), units.length - 1);
    return new Intl.NumberFormat(locale, {
        style: 'unit',
        unit: units[unitIndex] ?? 'byte',
        maximumFractionDigits: 1,
    }).format(bytes / 1000 ** unitIndex);
}
