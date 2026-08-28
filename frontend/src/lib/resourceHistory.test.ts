import { deserializeResourceHistory } from './resourceHistory'
import type { TelemetrySample } from '../types'

const telemetry: TelemetrySample = {
  captured_at: '2026-08-29T12:00:00.000Z',
  cpu_utilization: 45,
  gpu_utilization: 81,
  memory_used_bytes: 6 * 1024 ** 3,
  memory_total_bytes: 16 * 1024 ** 3,
  vram_used_mb: 4000,
  vram_total_mb: 12000,
}

test('deserializes server telemetry into chart samples', () => {
  const [sample] = deserializeResourceHistory([telemetry])
  expect(sample.gpuUtilization).toBe(81)
  expect(sample.vramUsedMb).toBe(4000)
  expect(sample.vramTotalMb).toBe(12000)
  expect(sample.vramUtilization).toBeCloseTo(100 / 3)
  expect(sample.memoryUtilization).toBe(37.5)
  expect(sample.capturedAt).toBe(Date.parse(telemetry.captured_at))
})

test('preserves server ordering and unavailable GPU metrics', () => {
  const history = deserializeResourceHistory([
    { ...telemetry, captured_at: '2026-08-29T11:59:50.000Z', gpu_utilization: null, vram_used_mb: null, vram_total_mb: null },
    telemetry,
  ])
  expect(history).toHaveLength(2)
  expect(history[0].gpuUtilization).toBeNull()
  expect(history[0].vramUtilization).toBeNull()
  expect(history[1].capturedAt).toBeGreaterThan(history[0].capturedAt)
})
