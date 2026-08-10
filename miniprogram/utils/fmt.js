/** 格式化小工具 */

/** 毫秒 → "m:ss"，如 93000 → "1:33" */
function formatDuration(ms) {
  if (!ms || ms <= 0) return '0:00'
  const s = Math.round(ms / 1000)
  const m = Math.floor(s / 60)
  const sec = s % 60
  return m + ':' + (sec < 10 ? '0' : '') + sec
}

/** 字节 → 可读大小 */
function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

module.exports = { formatDuration, formatBytes }
