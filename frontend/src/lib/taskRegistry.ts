import type { NetworkDependentTask, TaskFiles, TaskSnapshot } from 'src/lib/networkDependentTasks';
import {
    ReconstructionSubmissionTask,
    type ReconstructionSubmissionData,
} from 'src/lib/reconstructionSubmissionTask';
import { VideoUploadTask, type VideoUploadData } from 'src/lib/videoUploadTask';

export type StoredTaskSnapshot =
    | (TaskSnapshot<VideoUploadData> & { type: 'video-upload' })
    | (TaskSnapshot<ReconstructionSubmissionData> & { type: 'reconstruction-submission' });

export async function deserializeTask(
    snapshot: StoredTaskSnapshot,
    files: TaskFiles,
): Promise<NetworkDependentTask<unknown>> {
    switch (snapshot.type) {
        case 'video-upload':
            return VideoUploadTask.deserialize(snapshot, files);
        case 'reconstruction-submission':
            return ReconstructionSubmissionTask.deserialize(snapshot);
        default:
            throw new Error('Unknown saved task type.');
    }
}
