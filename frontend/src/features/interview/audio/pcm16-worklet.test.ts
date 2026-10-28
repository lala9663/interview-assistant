import { describe, expect, it, vi } from 'vitest'

import code from '../../../../public/audio/pcm16-worklet.js?raw'

interface Processor {
  process: (inputs: Float32Array[][]) => boolean
  port: { postMessage: ReturnType<typeof vi.fn> }
}

/** The worklet file as the browser runs it, with the AudioWorkletGlobalScope it needs stubbed. */
function processorAt(rate: number): Processor {
  let Registered: (new () => Processor) | undefined
  class Base {
    port = { postMessage: vi.fn() }
  }
  new Function('AudioWorkletProcessor', 'registerProcessor', 'sampleRate', code)(Base, (_name: string, cls: new () => Processor) => (Registered = cls), rate)
  return new Registered!()
}

function feed(processor: Processor, samples: Float32Array, channels = 1) {
  for (let i = 0; i < samples.length; i += 128) {
    const quantum = samples.slice(i, i + 128)
    processor.process([Array.from({ length: channels }, () => quantum)])
  }
}

function sine(rate: number, seconds: number, hz: number, amplitude: number) {
  return Float32Array.from({ length: Math.round(rate * seconds) }, (_, i) => amplitude * Math.sin((2 * Math.PI * hz * i) / rate))
}

const chunks = (p: Processor) => p.port.postMessage.mock.calls.map(([m]) => new Int16Array((m as { pcm: ArrayBuffer }).pcm))

describe('pcm16 AudioWorklet', () => {
  it('turns 48 kHz into 16 kHz PCM16 chunks of 100 ms, keeping the pitch and the level', () => {
    const p = processorAt(48000)
    feed(p, sine(48000, 0.21, 440, 0.5))
    const [first, second] = chunks(p)
    expect(chunks(p)).toHaveLength(2)
    expect(first).toHaveLength(1600)
    const crossings = second!.slice(1).filter((v, i) => Math.sign(v) !== Math.sign(second![i]!)).length
    expect(crossings).toBeGreaterThanOrEqual(86) // 440 Hz: 88 sign changes in 100 ms
    expect(crossings).toBeLessThanOrEqual(90)
    expect(Math.max(...second!)).toBeGreaterThan(0.48 * 32767)
    const level = (p.port.postMessage.mock.calls[1]![0] as { level: number }).level
    expect(level).toBeCloseTo(Math.min(1, (0.5 / Math.SQRT2) * 4), 1)
  })

  it('handles 44.1 kHz devices, mixes stereo, and counts missing input as silence', () => {
    const p = processorAt(44100)
    feed(p, sine(44100, 0.5, 300, 0.3), 2)
    expect(chunks(p).length).toBeGreaterThanOrEqual(4) // 0.5 s -> five 100 ms chunks, the last one partly filled
    const silent = processorAt(48000)
    for (let i = 0; i < 75; i++) silent.process([[]]) // the sample ended: inputs are empty (0.2 s)
    expect(chunks(silent)).toHaveLength(2)
    expect(chunks(silent).every((c) => c.every((v) => v === 0))).toBe(true)
  })
})
