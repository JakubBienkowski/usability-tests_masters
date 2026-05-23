import { cp, mkdir, rm } from 'fs/promises';
import { resolve } from 'path';

const root = new URL('..', import.meta.url).pathname;
const sourceDir = resolve(root, 'node_modules/webgazer/dist/mediapipe/face_mesh');
const targetDir = resolve(root, 'dist/mediapipe/face_mesh');

await rm(targetDir, { recursive: true, force: true });
await mkdir(resolve(root, 'dist/mediapipe'), { recursive: true });
await cp(sourceDir, targetDir, { recursive: true });
