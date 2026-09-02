import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { SystemPanel } from './SystemPanel'

test('orders performance plots by CPU, memory, GPU, and VRAM', () => {
  render(
    <SystemPanel
      open
      system={{
        pod_id: 'pod-a',
        blender_version: '5.2.1',
        gpus: [{ name: 'RTX 5090', utilization: 75, memory_used_mb: 4000, memory_total_mb: 32_768 }],
        available_backends: ['OPTIX', 'CUDA', 'CPU'],
        cpu_utilization: 50,
        memory_used_bytes: 8 * 1024 ** 3,
        memory_total_bytes: 16 * 1024 ** 3,
        disk_free_bytes: 1,
        disk_total_bytes: 1,
      }}
      samples={[{
        capturedAt: Date.now(),
        cpuUtilization: 50,
        gpuUtilization: 75,
        memoryUtilization: 50,
        vramUtilization: 12.5,
        memoryUsedBytes: 8 * 1024 ** 3,
        memoryTotalBytes: 16 * 1024 ** 3,
        vramUsedMb: 4000,
        vramTotalMb: 32_768,
      }]}
      onClose={vi.fn()}
    />,
  )

  expect(screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent))
    .toEqual(['CPU', 'MEM', 'GPU', 'VRAM'])
})
