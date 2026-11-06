/** English source messages are type-safe keys; Chinese is maintained centrally.
 * Commands, model names, source paths and scientific data are never translated.
 */
import { zh } from './zh';
export const locales = ['en', 'zh'] as const;
export type Locale = typeof locales[number];
export type MessageKey = keyof typeof zh;
export const languageTag = { en: 'en-US', zh: 'zh-CN' } as const;
export function t(locale: Locale, key: MessageKey): string {
  return locale === 'zh' ? zh[key] : key;
}
/** Strict dynamic lookup for editorial resources: missing copy fails the build. */
export function translate(locale: Locale, key: string): string {
  if (!Object.prototype.hasOwnProperty.call(zh, key)) throw new Error('Missing website translation: ' + key);
  return t(locale, key as MessageKey);
}
export function format(locale: Locale, key: MessageKey, values: Record<string, string | number>): string {
  return t(locale, key).replace(/\{(\w+)\}/g, (_, name: string) => {
    if (!(name in values)) throw new Error('Missing translation parameter');
    return String(values[name]);
  });
}
export function number(locale: Locale, value: number, digits = 2): string {
  return new Intl.NumberFormat(languageTag[locale], { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false }).format(value);
}
export function pathFor(locale: Locale, page = '', base = '/vulnloc'): string {
  return `${base.replace(/\/$/, '')}/${locale}/${page ? page + '/' : ''}`;
}
