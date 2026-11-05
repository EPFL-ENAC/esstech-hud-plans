import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BLOCK_BYTES, DOWNLOAD_URL, downloadFixture } from './helpers/resumable-download.mjs';

for (const storage of ['memory', 'disk']) {
    async function fixture(t) {
        const f = await downloadFixture(t, { persistent: storage === 'disk' });
        const file =
            storage === 'disk'
                ? await f.DiskDownloadFile.open(DOWNLOAD_URL)
                : new f.MemoryDownloadFile();
        return { ...f, file };
    }

    test(`${storage}: buffering snapshots caller bytes and commits across boundaries`, async (t) => {
        const { file } = await fixture(t);
        const commits = [];
        file.onCommit = async (size) => commits.push(size);
        const first = new Uint8Array([1, 2, 3]);
        await file.append(first);
        first.fill(99);
        assert.equal(file.size, 3);
        assert.equal(file.committedBytes, 0);
        const tail = new Uint8Array(BLOCK_BYTES * 2 + 7).fill(42);
        await file.append(tail);
        tail.fill(99);
        assert.equal(file.committedBytes, BLOCK_BYTES * 2);
        const blob = await file.toBlob();
        const expected = new Uint8Array(BLOCK_BYTES * 2 + 10).fill(42);
        expected.set([1, 2, 3]);
        assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), expected);
        assert.deepEqual(commits, [BLOCK_BYTES, BLOCK_BYTES * 2, expected.length]);
        await file.flush();
        assert.equal(commits.length, 3);
    });

    test(`${storage}: failed notification retries without repeating the write`, async (t) => {
        const { file, events } = await fixture(t);
        const error = new Error('checkpoint failed');
        let attempts = 0;
        file.onCommit = async () => {
            if (++attempts === 1) throw error;
        };
        await file.append(new Uint8Array([1, 2]));
        await assert.rejects(file.flush(), (value) => value === error);
        assert.equal(file.committedBytes, 2);
        assert.equal(file.size, 2);
        await file.append(new Uint8Array([3]));
        assert.deepEqual(
            new Uint8Array(await (await file.toBlob()).arrayBuffer()),
            new Uint8Array([1, 2, 3]),
        );
        assert.equal(attempts, 3);
        if (storage === 'disk') {
            assert.deepEqual(
                events.filter(([type]) => type === 'commit'),
                [
                    ['commit', 2],
                    ['commit', 3],
                ],
            );
        }
    });

    test(`${storage}: truncation and removal own all bytes without notifications`, async (t) => {
        const { file } = await fixture(t);
        let notifications = 0;
        file.onCommit = async () => {
            notifications++;
        };
        await file.append(new Uint8Array([1, 2, 3]));
        await file.truncate(2);
        assert.equal(file.size, 2);
        assert.equal(notifications, 0);
        await file.flush();
        await file.append(new Uint8Array([4, 5]));
        await file.truncate(1);
        assert.equal(file.committedBytes, 1);
        assert.equal(file.size, 1);
        assert.equal(notifications, 1);
        assert.deepEqual(
            new Uint8Array(await (await file.toBlob()).arrayBuffer()),
            new Uint8Array([1]),
        );
        for (const size of [-1, 2, 0.5, NaN]) await assert.rejects(file.truncate(size), RangeError);
        await file.remove();
        assert.equal(file.size, 0);
        assert.equal(notifications, 1);
        await file.append(new Uint8Array([9]));
        assert.equal((await file.toBlob()).size, 1);
    });
}

test('disk: a failed write retains the buffer for retry', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    const file = await f.DiskDownloadFile.open(DOWNLOAD_URL);
    const error = new Error('disk full');
    let notifications = 0;
    file.onCommit = async () => {
        notifications++;
    };
    await file.append(new Uint8Array([1, 2, 3]));
    f.failWrites(error);
    await assert.rejects(file.flush(), (value) => value === error);
    assert.equal(file.size, 3);
    assert.equal(file.committedBytes, 0);
    assert.equal(notifications, 0);
    f.failWrites(undefined);
    assert.deepEqual(
        new Uint8Array(await (await file.toBlob()).arrayBuffer()),
        new Uint8Array([1, 2, 3]),
    );
    assert.equal(notifications, 1);
});
