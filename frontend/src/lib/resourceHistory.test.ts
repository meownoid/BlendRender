import { appendResourceSample, RESOURCE_HISTORY_MS, sampleResources } from './resourceHistory'
import type { SystemInfo } from '../types'

const system: SystemInfo = {
  blender_version: '5.2.1',
  gpus: [
    { name: 'GPU 0', utilization: 22, memory_used_mb: 1000, memory_total_mb: 4000 },
    { name: 'GPU 1', utilization: 81, memory_used_mb: 3000, memory_total_mb: 8000 },
  ],
  available_backends: ['CPU', 'CUDA'],
  cpu_utilization: 45,
  memory_used_bytes: 6 * 1024 ** 3,
  memory_total_bytes: 16 * 1024 ** 3,
  disk_free_bytes: 1,
  disk_total_bytes: 2,
}

test('creates aggregate GPU and VRAM samples', () => {
  const sample = sampleResources(system, 10)
  expect(sample.gpuUtilization).toBe(81)
  expect(sample.vramUsedMb).toBe(4000)
  expect(sample.vramTotalMb).toBe(12000)
  expect(sample.vramUtilization).toBeCloseTo(100 / 3)
  expect(sample.memoryUtilization).toBe(37.5)
})

test('keeps only the configured rolling history window', () => {
  const now = RESOURCE_HISTORY_MS + 100
  const old = sampleResources(system, 0)
  const history = appendResourceSample([old], system, now)
  expect(history).toHaveLength(1)
  expect(history[0].capturedAt).toBe(now)
})
