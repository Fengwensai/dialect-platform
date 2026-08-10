/**
 * 区划名解析（省+市）：把 speaker 的属地代码解析成「辽宁·沈阳」之类的中文名。
 * 依赖后端 /api/mp/regions（省列表）与 /api/mp/regions?parent_code=（市列表）。
 * 带缓存，避免每页重复请求。
 */
const api = require('./api')

let provCache = [] // [{code,name}]
const cityCache = {} // provinceCode -> [{code,name}]

function getProvinces() {
  if (provCache.length) return Promise.resolve(provCache)
  return api.request('/api/mp/regions').then((list) => {
    provCache = list || []
    return provCache
  })
}

function getCities(provinceCode) {
  if (!provinceCode) return Promise.resolve([])
  if (cityCache[provinceCode]) return Promise.resolve(cityCache[provinceCode])
  return api.request('/api/mp/regions?parent_code=' + provinceCode).then((list) => {
    cityCache[provinceCode] = list || []
    return cityCache[provinceCode]
  })
}

/**
 * 属地显示文本。
 * @param {string} provinceCode 省码
 * @param {string} [cityCode] 市码（可空）
 * @returns {Promise<string>} 如「辽宁·沈阳」；解析失败兜底返回原始码
 */
function regionText(provinceCode, cityCode) {
  if (!provinceCode) return Promise.resolve('')
  return getProvinces()
    .then((provs) => {
      const p = provs.find((x) => x.code === provinceCode)
      if (!cityCode) return p ? p.name : provinceCode
      return getCities(provinceCode).then((cities) => {
        const c = cities.find((x) => x.code === cityCode)
        const pName = p ? p.name : provinceCode
        return pName + '·' + (c ? c.name : cityCode)
      })
    })
    .catch(() => (cityCode ? provinceCode + '·' + cityCode : provinceCode))
}

module.exports = { getProvinces, getCities, regionText }
