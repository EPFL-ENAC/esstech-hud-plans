export interface HistogramBin {
    binStart: number;
    binEnd: number;
    count: number;
}

export class Histogram {
    public readonly bins: ReadonlyArray<HistogramBin>;
    public readonly dataLength: number;
    public readonly min: number;
    public readonly max: number;

    constructor(data: Float64Array, numBins: number) {
        this.dataLength = data.length;

        // 1. Calculate Range
        let min = Infinity;
        let max = -Infinity;
        for (const value of data) {
            if (value < min) min = value;
            if (value > max) max = value;
        }
        this.min = min;
        this.max = max;

        // 2. Initialize Bins
        const binSize = (max - min) / numBins;
        const bins: HistogramBin[] = Array.from({ length: numBins }, (_, i) => ({
            binStart: min + i * binSize,
            binEnd: min + (i + 1) * binSize,
            count: 0,
        }));

        // 3. Populate Bins
        if (data.length > 0 && binSize > 0) {
            for (const value of data) {
                // Calculate index and clamp to handle the edge case where value === max
                const index = Math.floor((value - min) / binSize);
                const binIndex = Math.min(index, numBins - 1);
                if (bins[binIndex]) {
                    bins[binIndex].count++;
                }
            }
        }

        this.bins = bins;
    }

    /**
     * Returns the bin with the highest frequency.
     */
    public getHighestBin(): HistogramBin | null {
        if (this.bins.length === 0) return null;

        let bestBin = this.bins[0];
        for (let i = 1; i < this.bins.length; i++) {
            if (this.bins[i]!.count > bestBin!.count) {
                bestBin = this.bins[i];
            }
        }

        return bestBin ?? null;
    }

    /**
     * Returns the top K bins sorted by count descending.
     */
    public getTopKBins(k: number): HistogramBin[] {
        return [...this.bins].sort((a, b) => b.count - a.count).slice(0, k);
    }

    /**
     * Utility to get the average count per bin.
     */
    public getAverageCount(): number {
        return this.dataLength / this.bins.length;
    }
}
