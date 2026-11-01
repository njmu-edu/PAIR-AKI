import type { Comparison } from './types'

const comparisonUnits: Record<string, string> = {
  age_days: '天', hours_since_admission: 'h', latest_umol_l: 'µmol/L', reference168_umol_l: 'µmol/L',
  ratio168: '倍', rise48_umol_l: 'µmol/L', slope24_per_hour: 'µmol/L/h', slope72_per_hour: 'µmol/L/h', range72_umol_l: 'µmol/L',
}

export const comparisonLabel = (item: Comparison) => item.label + (comparisonUnits[item.key] ? '（' + comparisonUnits[item.key] + '）' : '')
