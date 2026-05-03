export type LogCategory = 'info' | 'warning' | 'error';

export interface ProcessedLog {
    line: string;
    index: number;
    category: LogCategory;
}

export type LogParser = (line: string) => LogCategory;

export class LogProcessor {
    private processedLogs: ProcessedLog[] = [];
    private lastProcessedIndex = 0;
    private parseFn: LogParser;

    constructor(parseFn?: LogParser) {
        this.parseFn = parseFn || (() => 'info');
    }

    /**
     * Processes only the new lines added to the array.
     * If the array is shorter than before, it resets.
     */
    public update(rawLogs: string[]): ProcessedLog[] {
        // Handle potential log resets or clearings
        if (rawLogs.length < this.lastProcessedIndex) {
            this.processedLogs = [];
            this.lastProcessedIndex = 0;
        }

        if (rawLogs.length > this.lastProcessedIndex) {
            const newLines = rawLogs.slice(this.lastProcessedIndex);

            const processedNewLines = newLines.map((line, i) => ({
                line,
                index: this.lastProcessedIndex + i,
                category: this.parseFn(line),
            }));

            this.processedLogs.push(...processedNewLines);
            this.lastProcessedIndex = rawLogs.length;
        }

        return this.processedLogs;
    }

    public get logs() {
        return this.processedLogs;
    }
}

export function colmapLogsParser(line: string): LogCategory {
    const lowerLine = line.toLowerCase();
    if (lowerLine.startsWith('f') && !lowerLine.startsWith('feature')) return 'error'; // F for Fatal
    if (lowerLine.startsWith('e')) return 'error';
    if (lowerLine.startsWith('w')) return 'warning';
    return 'info';
}
