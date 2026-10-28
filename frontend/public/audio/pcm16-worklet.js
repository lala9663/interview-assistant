/**
 * AudioWorklet processor 'pcm16': the microphone (or the sample player) at the device rate, usually
 * 48 kHz, becomes 16 kHz mono signed 16-bit PCM in 100 ms chunks, posted to the page with the
 * chunk's level (RMS, 0..1). The page sends the chunks to the server as they come
 * (src/features/interview/audio/use-microphone.ts).
 *
 * Downsampling averages the input samples that fall into each output sample (a box filter), which
 * keeps most aliasing above 8 kHz out of the speech band; Whisper and the VAD read 16 kHz anyway.
 * Several input channels are mixed to one. A quantum without input (the sample finished) counts as
 * silence, so the server keeps hearing time pass and can close the answer.
 *
 * Plain JavaScript, loaded as is by audioWorklet.addModule('/audio/pcm16-worklet.js'); the tests
 * run this file too (pcm16-worklet.test.ts).
 */
const OUT_RATE = 16000
const CHUNK = 1600 // 100 ms at 16 kHz

class Downsampler {
  constructor(inRate) {
    this.step = inRate / OUT_RATE // input samples per output sample
    this.next = this.step // input position where the current output sample ends
    this.position = 0 // input samples seen
    this.sum = 0
    this.count = 0
  }

  /** Float32 input samples in, output samples (floats, -1..1) out. */
  push(input, out) {
    for (let i = 0; i < input.length; i++) {
      this.sum += input[i]
      this.count++
      this.position++
      if (this.position >= this.next) {
        out.push(this.sum / this.count)
        this.sum = 0
        this.count = 0
        this.next += this.step
      }
    }
    return out
  }
}

class Pcm16Processor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.down = new Downsampler(sampleRate)
    this.chunk = new Int16Array(CHUNK)
    this.filled = 0
    this.squares = 0
    this.silence = new Float32Array(128)
  }

  process(inputs) {
    const input = inputs[0]
    let mono = this.silence
    if (input && input.length === 1) mono = input[0]
    else if (input && input.length > 1) {
      mono = new Float32Array(input[0].length)
      for (const channel of input) for (let i = 0; i < channel.length; i++) mono[i] += channel[i] / input.length
    }
    for (const value of this.down.push(mono, [])) {
      const clipped = Math.max(-1, Math.min(1, value))
      this.chunk[this.filled++] = clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff
      this.squares += clipped * clipped
      if (this.filled === CHUNK) {
        const level = Math.min(1, Math.sqrt(this.squares / CHUNK) * 4)
        this.port.postMessage({ pcm: this.chunk.buffer, level }, [this.chunk.buffer])
        this.chunk = new Int16Array(CHUNK)
        this.filled = 0
        this.squares = 0
      }
    }
    return true
  }
}

registerProcessor('pcm16', Pcm16Processor)
