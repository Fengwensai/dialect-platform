/**
 * WAV 头正确性自检（Node 直接复用 miniprogram/utils/wav.js 的纯函数）。
 *
 * 生成 1s 16kHz 单声道 16bit 正弦波 → pcmToWav → 写 out.wav，
 * 自检 44 字节头布局，再用 Python wave 模块交叉验证。
 *
 * 用法：
 *   cd miniprogram/tools && node test_wav.js
 *   python -c "import wave;w=wave.open('out.wav');print(w.getframerate(),w.getnchannels(),w.getsampwidth(),w.getnframes())"
 *   期望输出：16000 1 2 16000
 */
const fs = require('fs')
const path = require('path')
const { pcmToWav } = require('../utils/wav')

const SAMPLE_RATE = 16000
const SECONDS = 1
const N = SAMPLE_RATE * SECONDS // 采样点数

// 1s 440Hz 正弦（幅度 0.5），16bit 有符号
const pcm = new Int16Array(N)
for (let i = 0; i < N; i++) {
  pcm[i] = Math.round(Math.sin((2 * Math.PI * 440 * i) / SAMPLE_RATE) * 0.5 * 32767)
}

const wav = pcmToWav(pcm.buffer, SAMPLE_RATE, 1, 16)
const out = path.join(__dirname, 'out.wav')
fs.writeFileSync(out, Buffer.from(wav))
console.log('[test_wav] written', out, '=>', wav.byteLength, 'bytes (expect', 44 + N * 2 + ')')

// 头字节自检
const view = new DataView(wav)
const tag = (o, n) => String.fromCharCode.apply(null, new Uint8Array(wav, o, n))

const expect = (name, got, want) => {
  const ok = got === want
  console.log(ok ? '  [PASS]' : '  [FAIL]', name, '=', got, ok ? '' : '(expect ' + want + ')')
  if (!ok) process.exitCode = 1
}

expect('RIFF/WAVE tag', tag(0, 4) + '|' + tag(8, 4), 'RIFF|WAVE')
expect('chunkSize (4)', view.getUint32(4, true), 36 + N * 2)
expect('fmt  tag', tag(12, 4), 'fmt ')
expect('subchunk1 size (16)', view.getUint32(16, true), 16)
expect('audioFormat PCM (20)', view.getUint16(20, true), 1)
expect('channels (22)', view.getUint16(22, true), 1)
expect('sampleRate (24)', view.getUint32(24, true), 16000)
expect('byteRate (28)', view.getUint32(28, true), 16000 * 2)
expect('blockAlign (32)', view.getUint16(32, true), 2)
expect('bitsPerSample (34)', view.getUint16(34, true), 16)
expect('data tag (36)', tag(36, 4), 'data')
expect('dataSize (40)', view.getUint32(40, true), N * 2)

console.log(process.exitCode ? '\n[test_wav] 有断言失败！' : '\n[test_wav] 头字节全部通过')
