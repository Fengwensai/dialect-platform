/**
 * PCM → WAV（44 字节 RIFF 头）。
 *
 * 微信 RecorderManager 以 format:'PCM'（大写，有效值 aac/mp3/wav/PCM）录制时返回裸 PCM 数据（无文件头），
 * 语音学软件（Praat 等）只认 WAV，必须在 JS 层手动补头。切记：不能在服务端转，
 * 服务端转换会被重采样，破坏原始数据。
 *
 * 致命坑：微信 PCM 为小端（Little-Endian）。WAV 头各字段必须按小端写入，
 * 否则播放全是杂音。DataView.setUint16/setUint32 的第 3 参 true = littleEndian。
 *
 * 本文件为纯函数，不依赖任何 wx API，可在 Node 中直接单测（见 tools/test_wav.js）。
 */

const HEADER_SIZE = 44

/**
 * 把裸 PCM ArrayBuffer 打包为完整 WAV ArrayBuffer。
 * @param {ArrayBuffer} pcmAB 裸 PCM 数据（16bit 有符号小端采样）
 * @param {number} sampleRate 采样率，默认 16000
 * @param {number} channels 声道数，默认 1
 * @param {number} bitsPerSample 位深，默认 16
 * @returns {ArrayBuffer}
 */
function pcmToWav(pcmAB, sampleRate = 16000, channels = 1, bitsPerSample = 16) {
  let pcm
  if (pcmAB instanceof ArrayBuffer) pcm = pcmAB
  else if (pcmAB && ArrayBuffer.isView(pcmAB)) pcm = pcmAB.buffer
  else throw new Error('PCM 数据不是二进制数据')
  const dataSize = pcm.byteLength
  const byteRate = (sampleRate * channels * bitsPerSample) / 8
  const blockAlign = (channels * bitsPerSample) / 8

  const ab = new ArrayBuffer(HEADER_SIZE + dataSize)
  const view = new DataView(ab)

  const writeStr = (offset, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i))
  }

  // RIFF 块
  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true) // 文件总长 - 8
  writeStr(8, 'WAVE')
  // fmt 子块
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 子块长度（PCM 固定 16）
  view.setUint16(20, 1, true) // 编码格式：1 = PCM
  view.setUint16(22, channels, true) // 声道数
  view.setUint32(24, sampleRate, true) // 采样率
  view.setUint32(28, byteRate, true) // 每秒字节数 = sampleRate*channels*bits/8
  view.setUint16(32, blockAlign, true) // 采样对齐 = channels*bits/8
  view.setUint16(34, bitsPerSample, true) // 位深
  // data 子块
  writeStr(36, 'data')
  view.setUint32(40, dataSize, true) // PCM 数据长度

  new Uint8Array(ab, HEADER_SIZE).set(new Uint8Array(pcm))
  return ab
}

/**
 * 读取 .pcm 临时文件 → 写出 .wav 文件（依赖微信文件系统 API，录音流程中调用）。
 * @param {object} opts { pcmPath, wavPath, sampleRate?, channels?, bitsPerSample? }
 * @returns {Promise<string>} wavPath
 */
function pcmFileToWavFile(opts) {
  const { pcmPath, wavPath, sampleRate = 16000, channels = 1, bitsPerSample = 16 } = opts
  const fs = wx.getFileSystemManager()
  return new Promise((resolve, reject) => {
    fs.readFile({
      filePath: pcmPath,
      success(res) {
        try {
          const data = res && res.data
          if (!data) {
            throw new Error(
              '录音文件为空：开发者工具是模拟录音，无法读取真实 PCM，请在真机上预览测试'
            )
          }
          const pcm = _toArrayBuffer(data)
          if (!pcm) {
            throw new Error(
              '录音文件格式无法识别：开发者工具录音与真机格式不同，请在真机上预览测试'
            )
          }
          const wav = pcmToWav(pcm, sampleRate, channels, bitsPerSample)
          fs.writeFile({
            filePath: wavPath,
            data: wav,
            success: () => resolve(wavPath),
            fail: reject
          })
        } catch (e) {
          reject(e)
        }
      },
      fail: (e) => reject(e || new Error('读取录音文件失败'))
    })
  })
}

/**
 * 把 readFile 返回的各类数据归一化为 ArrayBuffer。
 * 真机：默认返回 ArrayBuffer；开发者工具模拟录音可能返回字符串（base64）或空值。
 */
function _toArrayBuffer(data) {
  if (data instanceof ArrayBuffer) return data
  if (data && ArrayBuffer.isView(data)) return data.buffer
  if (typeof data === 'string' && data) {
    try {
      // 兼容 base64 字符串（部分环境 readFile 返回 base64）
      if (typeof wx !== 'undefined' && wx.base64ToArrayBuffer) {
        return wx.base64ToArrayBuffer(data)
      }
    } catch (e) {
      // 不是 base64，落到下方返回 null
    }
  }
  return null
}

module.exports = { pcmToWav, pcmFileToWavFile, HEADER_SIZE }
