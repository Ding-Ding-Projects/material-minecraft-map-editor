const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

export function normaliseHex(value) {
  const candidate = String(value || '').trim();
  return /^#[0-9a-f]{6}$/i.test(candidate) ? candidate.toLowerCase() : null;
}

export function hexRgb(hex) {
  const value = normaliseHex(hex);
  if (!value) throw new Error('Expected a six-digit HEX colour');
  return [0, 2, 4].map((index) => parseInt(value.slice(index + 1, index + 3), 16));
}

export function rgbHex(rgb) {
  return `#${rgb.map((channel) => clamp(Math.round(channel), 0, 255).toString(16).padStart(2, '0')).join('')}`;
}

export function rgbHsl(rgb) {
  const values = rgb.map((channel) => channel / 255);
  const maximum = Math.max(...values);
  const minimum = Math.min(...values);
  const delta = maximum - minimum;
  const lightness = (maximum + minimum) / 2;
  let hue = 0;
  let saturation = 0;
  if (delta) {
    saturation = delta / (1 - Math.abs(2 * lightness - 1));
    if (maximum === values[0]) hue = 60 * (((values[1] - values[2]) / delta) % 6);
    else if (maximum === values[1]) hue = 60 * ((values[2] - values[0]) / delta + 2);
    else hue = 60 * ((values[0] - values[1]) / delta + 4);
  }
  return [Math.round((hue + 360) % 360), Math.round(saturation * 100), Math.round(lightness * 100)];
}

export function hslRgb(hsl) {
  const hue = ((((Number(hsl[0]) || 0) % 360) + 360) % 360) / 60;
  const saturation = clamp(Number(hsl[1]) || 0, 0, 100) / 100;
  const lightness = clamp(Number(hsl[2]) || 0, 0, 100) / 100;
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const x = chroma * (1 - Math.abs((hue % 2) - 1));
  const offset = lightness - chroma / 2;
  const sector = hue < 1 ? [chroma, x, 0]
    : hue < 2 ? [x, chroma, 0]
      : hue < 3 ? [0, chroma, x]
        : hue < 4 ? [0, x, chroma]
          : hue < 5 ? [x, 0, chroma]
            : [chroma, 0, x];
  return sector.map((channel) => (channel + offset) * 255);
}

export function relativeLuminance(hex) {
  const channels = hexRgb(hex)
    .map((channel) => channel / 255)
    .map((channel) => channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

export function contrastRatio(foreground, background) {
  const first = relativeLuminance(foreground);
  const second = relativeLuminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

function tone(hue, saturation, lightness) {
  return rgbHex(hslRgb([hue, saturation, lightness]));
}

function accessiblePrimary(hue, saturation, surface, dark) {
  const tones = dark
    ? Array.from({ length: 20 }, (_, index) => 76 + index)
    : Array.from({ length: 36 }, (_, index) => 40 - index);
  for (const lightness of tones) {
    const candidate = tone(hue, saturation, lightness);
    const foreground = contrastRatio('#ffffff', candidate) >= 4.5 ? '#ffffff' : '#101116';
    if (contrastRatio(candidate, surface) >= 4.5 && contrastRatio(foreground, candidate) >= 4.5) {
      return { primary: candidate, onPrimary: foreground };
    }
  }
  return dark
    ? { primary: '#c2c7ff', onPrimary: '#182044' }
    : { primary: '#354778', onPrimary: '#ffffff' };
}

function accessibleForeground(background, light, dark) {
  return contrastRatio(light, background) >= contrastRatio(dark, background) ? light : dark;
}

export function deriveThemeRoles(seed, theme = 'light') {
  const value = normaliseHex(seed) || '#4d5f92';
  const [hue, sourceSaturation] = rgbHsl(hexRgb(value));
  const saturation = clamp(sourceSaturation, 35, 78);
  const dark = theme === 'dark';
  const surface = dark ? '#111318' : '#fbf8ff';
  const primaryRole = accessiblePrimary(hue, saturation, surface, dark);
  const primaryContainer = tone(hue, saturation, dark ? 28 : 91);
  const onPrimaryContainer = accessibleForeground(primaryContainer, '#ffffff', '#000000');
  return {
    seed: value,
    surface,
    onSurface: dark ? '#e4e1e9' : '#1b1b20',
    onSurfaceVariant: dark ? '#cbc6d1' : '#47464f',
    primary: primaryRole.primary,
    onPrimary: primaryRole.onPrimary,
    primaryContainer,
    onPrimaryContainer,
  };
}

export function applyThemeRoles(target, seed, theme = 'light') {
  const roles = deriveThemeRoles(seed, theme);
  const names = {
    surface: '--surface',
    onSurface: '--on-surface',
    onSurfaceVariant: '--on-surface-variant',
    primary: '--primary',
    onPrimary: '--on-primary',
    primaryContainer: '--primary-container',
    onPrimaryContainer: '--on-primary-container',
  };
  Object.entries(names).forEach(([role, property]) => target.style.setProperty(property, roles[role]));
  return roles;
}
