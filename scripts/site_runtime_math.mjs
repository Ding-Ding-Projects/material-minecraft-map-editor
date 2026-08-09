export const DPR_EPSILON = 0.01;

export function dprMatches(actual, expected, epsilon = DPR_EPSILON) {
  return Number.isFinite(actual)
    && Number.isFinite(expected)
    && Number.isFinite(epsilon)
    && epsilon >= 0
    && Math.abs(actual - expected) <= epsilon;
}
